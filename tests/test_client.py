"""Synthetic tests for a provisional Necto HTTP client."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

path = Path(__file__).parents[1] / "custom_components" / "necto" / "client.py"
spec = importlib.util.spec_from_file_location("necto_client", path)
client_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = client_module
spec.loader.exec_module(client_module)


def run_immediate(coro):
    try:
        coro.send(None)
    except StopIteration as result:
        return result.value
    raise AssertionError("Fake transport unexpectedly suspended")


class Response:
    def __init__(self, status, headers=None, text="", body=None):
        self.status, self.headers, self._text, self._body = status, headers or {}, text, body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def text(self):
        return self._text

    async def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.cookie_jar = SimpleNamespace(filter_cookies=lambda _url: {"XSRF-TOKEN": SimpleNamespace(value="a%2Bb")})

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return next(self.responses)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return next(self.responses)


class ClientTests(unittest.TestCase):
    def test_dispose_clears_cookie_jar_and_detaches_session(self):
        state = {"cleared": False, "detached": False}
        def clear():
            state["cleared"] = True
        def detach():
            state["detached"] = True
        session = SimpleNamespace(cookie_jar=SimpleNamespace(clear=clear), detach=detach)
        run_immediate(client_module.NectoClient(session).close())
        self.assertEqual(state, {"cleared": True, "detached": True})

    def login_page(self):
        return Response(200, text='<div id="app" data-page="{&quot;component&quot;:&quot;Auth/Login&quot;,&quot;version&quot;:&quot;v1&quot;}"></div>')

    def test_login_and_read_are_separate_and_read_does_not_refresh_device(self):
        response_body = {"props": {"devices": {"data": []}}}
        session = FakeSession([self.login_page(), Response(302, {"Location": "/devices"}),
                               Response(200, body=response_body)])
        client = client_module.NectoClient(session)
        run_immediate(client.login("example@example.invalid", "synthetic"))
        self.assertEqual(run_immediate(client.get_device_page(1)), response_body)
        self.assertEqual(session.calls[1][2]["headers"]["X-XSRF-TOKEN"], "a+b")
        self.assertEqual(session.calls[1][2]["json"], {"email": "example@example.invalid", "password": "synthetic", "remember": False})
        self.assertEqual(session.calls[2][1], "https://app.getnecto.com/devices")
        self.assertEqual(session.calls[2][2]["params"], {"page": 1})

    def test_rejects_redirect_to_other_host(self):
        session = FakeSession([self.login_page(), Response(302, {"Location": "https://elsewhere.invalid/devices"})])
        with self.assertRaises(client_module.NectoError):
            run_immediate(client_module.NectoClient(session).login("x", "y"))

    def test_expired_session_is_not_followed(self):
        session = FakeSession([Response(302, {"Location": "/login"})])
        with self.assertRaises(client_module.NectoAuthError):
            run_immediate(client_module.NectoClient(session).get_device_page(1))

    def test_expired_session_reauthenticates_once_and_retries(self):
        body = {"props": {"devices": {"data": []}}}
        session = FakeSession([Response(302, {"Location": "/login"}), self.login_page(),
                               Response(302, {"Location": "/devices"}), Response(200, body=body)])
        client = client_module.NectoClient(session, "example@example.invalid", "synthetic")
        self.assertEqual(run_immediate(client.get_device_page(1)), body)
        self.assertEqual([call[0] for call in session.calls], ["GET", "GET", "POST", "GET"])

    def test_failed_login_does_not_leak_credentials_or_response(self):
        secret = "synthetic-super-secret"
        session = FakeSession([self.login_page(), Response(302, {"Location": "/login"}, text=secret)])
        with self.assertRaises(client_module.NectoAuthError) as caught:
            run_immediate(client_module.NectoClient(session).login("sample@example.invalid", secret))
        self.assertNotIn(secret, str(caught.exception))
        self.assertNotIn("sample@example.invalid", str(caught.exception))

    def test_session_still_expired_after_retry_does_not_loop(self):
        session = FakeSession([Response(302, {"Location": "/login"}), self.login_page(),
                               Response(302, {"Location": "/devices"}), Response(302, {"Location": "/login"})])
        client = client_module.NectoClient(session, "example@example.invalid", "synthetic")
        with self.assertRaises(client_module.NectoAuthError):
            run_immediate(client.get_device_page(1))
        self.assertEqual(len(session.calls), 4)

    def test_server_failure_is_not_misclassified_as_bad_credentials(self):
        session = FakeSession([self.login_page(), Response(503)])
        with self.assertRaises(client_module.NectoError) as caught:
            run_immediate(client_module.NectoClient(session).login("x", "y"))
        self.assertNotIsInstance(caught.exception, client_module.NectoAuthError)

    def test_bad_json_response_does_not_leak_nested_error(self):
        class MalformedResponse(Response):
            async def json(self):
                raise ValueError("synthetic-sensitive-payload")
        session = FakeSession([MalformedResponse(200)])
        with self.assertRaises(client_module.NectoError) as caught:
            run_immediate(client_module.NectoClient(session).get_device_page(1))
        self.assertTrue(caught.exception.__suppress_context__)
        self.assertNotIn("synthetic-sensitive-payload", str(caught.exception))

    def test_version_change_reloads_page_and_retries_once(self):
        body = {"props": {"devices": {"data": []}}}
        html = '<div id="app" data-page="{&quot;component&quot;:&quot;Devices&quot;,&quot;version&quot;:&quot;v2&quot;,&quot;props&quot;:{&quot;devices&quot;:{&quot;data&quot;:[]}}}"></div>'
        session = FakeSession([Response(409, {"X-Inertia-Location": "/devices?page=1"}),
                               Response(200, text=html), Response(200, body=body)])
        client = client_module.NectoClient(session)
        client._version = "v1"
        self.assertEqual(run_immediate(client.get_device_page(1)), body)
        self.assertEqual(session.calls[-1][2]["headers"]["X-Inertia-Version"], "v2")
        self.assertNotIn("X-Inertia", session.calls[1][2].get("headers", {}))
        self.assertFalse(session.calls[1][2]["allow_redirects"])

    def test_version_redirect_to_other_host_is_rejected(self):
        session = FakeSession([Response(409, {"X-Inertia-Location": "https://elsewhere.invalid/devices"})])
        with self.assertRaises(client_module.NectoError):
            run_immediate(client_module.NectoClient(session).get_device_page(1))
        self.assertEqual(len(session.calls), 1)

    def test_repeated_version_change_does_not_loop(self):
        html = '<div id="app" data-page="{&quot;component&quot;:&quot;Devices&quot;,&quot;version&quot;:&quot;v2&quot;,&quot;props&quot;:{&quot;devices&quot;:{&quot;data&quot;:[]}}}"></div>'
        mismatch = Response(409, {"X-Inertia-Location": "/devices"})
        session = FakeSession([mismatch, Response(200, text=html), mismatch])
        with self.assertRaises(client_module.NectoError):
            run_immediate(client_module.NectoClient(session).get_device_page(1))
        self.assertEqual(len(session.calls), 3)

    def test_expired_session_during_version_reload_reauthenticates(self):
        body = {"props": {"devices": {"data": []}}}
        session = FakeSession([Response(409, {"X-Inertia-Location": "/devices"}),
                               Response(302, {"Location": "/login"}), self.login_page(),
                               Response(302, {"Location": "/devices"}), Response(200, body=body)])
        client = client_module.NectoClient(session, "example@example.invalid", "synthetic")
        self.assertEqual(run_immediate(client.get_device_page(1)), body)
        self.assertEqual(len(session.calls), 5)
