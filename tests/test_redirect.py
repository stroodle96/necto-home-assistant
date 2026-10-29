"""Synthetic regression tests for safe redirect categories."""
import importlib.util
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace, ModuleType
import unittest

ROOT = Path(__file__).resolve().parent
COMPONENT = ROOT if (ROOT / "client.py").exists() else ROOT.parent / "custom_components" / "necto"
sys.path.insert(0, str(ROOT.parent / "tests"))
from test_client import FakeSession, Response, run_immediate
from unittest.mock import patch

package = ModuleType("focused_necto")
package.__path__ = [str(COMPONENT)]
sys.modules[package.__name__] = package
spec = importlib.util.spec_from_file_location("focused_necto.client", COMPONENT / "client.py")
client = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = client
spec.loader.exec_module(client)


class RedirectTests(unittest.TestCase):
    def test_redirects_are_classified_without_leaking_or_following(self):
        cases = [("http://app.getnecto.com/devices", "same_host_http"),
                 ("https://external.invalid/synthetic-secret", "other_origin")]
        login = '<div id="app" data-page="{&quot;component&quot;:&quot;Auth/Login&quot;,&quot;version&quot;:&quot;v1&quot;}"></div>'
        for location, expected in cases:
            with self.subTest(category=expected):
                session = FakeSession([Response(200, text=login), Response(302, {"Location": location})])
                with self.assertRaises(client.NectoRedirectError) as caught:
                    run_immediate(client.NectoClient(session).login("sample@example.invalid", "synthetic-secret"))
                self.assertEqual(caught.exception.category, expected)
                self.assertNotIn("synthetic-secret", str(caught.exception))
                self.assertEqual(len(session.calls), 2)

    def test_same_origin_other_path_verifies_fixed_devices_endpoint(self):
        login = '<div id="app" data-page="{&quot;component&quot;:&quot;Auth/Login&quot;,&quot;version&quot;:&quot;v1&quot;}"></div>'
        body = {"component": "Devices", "props": {"devices": {"data": [{"device_id": "example"}],
                   "meta": {"current_page": 1, "last_page": 1}}}}
        session = FakeSession([Response(200, text=login),
                               Response(302, {"Location": "/unrecognized?token=synthetic-secret"}),
                               Response(200, body=body)])
        run_immediate(client.NectoClient(session).login("sample@example.invalid", "synthetic-secret"))
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(session.calls[2][1], "https://app.getnecto.com/devices")
        self.assertEqual(session.calls[2][2]["params"], {"page": 1})
        self.assertFalse(session.calls[2][2]["allow_redirects"])

    def test_unverified_session_never_accepts_redirect_or_invalid_page(self):
        login = '<div id="app" data-page="{&quot;component&quot;:&quot;Auth/Login&quot;,&quot;version&quot;:&quot;v1&quot;}"></div>'
        invalid = [Response(302, {"Location": "https://external.invalid/"}),
                   Response(200, body={"component": "Auth/Login"}),
                   Response(200, body={"props": {"devices": {"data": "bad"}}}),
                   Response(200, body={"props": {"devices": {"data": [], "meta": {"current_page": 1, "last_page": 101}}}}),
                   Response(200, body={"props": {"devices": {"data": [{}], "meta": {"current_page": 1, "last_page": 1}}}})]
        for response in invalid:
            with self.subTest(status=response.status, body=response._body):
                session = FakeSession([Response(200, text=login), Response(302, {"Location": "/other"}), response])
                with self.assertRaises(client.NectoError) as caught:
                    run_immediate(client.NectoClient(session).login("sample@example.invalid", "synthetic-secret"))
                self.assertNotIn("synthetic-secret", str(caught.exception))
                self.assertEqual(len(session.calls), 3)

    def test_login_verification_recovers_one_application_version_change(self):
        login = '<div id="app" data-page="{&quot;component&quot;:&quot;Auth/Login&quot;,&quot;version&quot;:&quot;v1&quot;}"></div>'
        html = '<div id="app" data-page="{&quot;component&quot;:&quot;Devices&quot;,&quot;version&quot;:&quot;v2&quot;,&quot;props&quot;:{&quot;devices&quot;:{&quot;data&quot;:[]}}}"></div>'
        body = {"component": "Devices", "props": {"devices": {"data": [],
                    "meta": {"current_page": 1, "last_page": 1}}}}
        session = FakeSession([Response(200, text=login), Response(302, {"Location": "/other"}),
                               Response(409, {"X-Inertia-Location": "/devices"}),
                               Response(200, text=html), Response(200, body=body)])
        run_immediate(client.NectoClient(session).login("sample@example.invalid", "synthetic"))
        self.assertEqual(session.calls[-1][2]["headers"]["X-Inertia-Version"], "v2")
        self.assertEqual(len(session.calls), 5)

    def test_expected_login_outcomes_remain_unchanged(self):
        login = '<div id="app" data-page="{&quot;component&quot;:&quot;Auth/Login&quot;,&quot;version&quot;:&quot;v1&quot;}"></div>'
        accepted = FakeSession([Response(200, text=login), Response(302, {"Location": "/devices"})])
        run_immediate(client.NectoClient(accepted).login("sample@example.invalid", "synthetic"))
        rejected = FakeSession([Response(200, text=login), Response(302, {"Location": "/login"})])
        with self.assertRaises(client.NectoAuthError):
            run_immediate(client.NectoClient(rejected).login("sample@example.invalid", "synthetic"))

    def test_flow_logs_only_fixed_redirect_category(self):
        import test_config_flow as stubs
        importlib.reload(stubs)  # Restore HA stubs after other test modules replace them.
        name = "necto_flowdraft.client"
        spec = importlib.util.spec_from_file_location(name, COMPONENT / "client.py")
        focused_client = importlib.util.module_from_spec(spec)
        sys.modules[name] = focused_client
        spec.loader.exec_module(focused_client)
        spec = importlib.util.spec_from_file_location("necto_flowdraft.config_flow", COMPONENT / "config_flow.py")
        flow = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(flow)
        class Session:
            cookie_jar = SimpleNamespace(clear=lambda: None)
            def detach(self):
                pass
        class BrokenClient:
            def __init__(self, session):
                pass
            async def login(self, username, password):
                raise focused_client.NectoRedirectError("root")
        with patch.object(flow, "async_create_clientsession", return_value=Session()), patch.object(flow, "NectoClient", BrokenClient):
            with self.assertLogs("necto_flowdraft.config_flow", level="WARNING") as logs:
                with self.assertRaises(focused_client.NectoRedirectError):
                    run_immediate(flow._validate(object(), "sample@example.invalid", "synthetic-secret"))
        self.assertIn("stage=login reason=login_redirect_root", logs.output[0])
        self.assertNotIn("synthetic-secret", repr(logs.output))
        self.assertNotIn("sample@example.invalid", repr(logs.output))
