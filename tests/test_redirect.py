"""Synthetic regression tests for safe redirect categories."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parent
COMPONENT = ROOT if (ROOT / "client.py").exists() else ROOT.parent / "custom_components" / "necto"
sys.path.insert(0, str(ROOT.parent / "tests"))
from test_client import FakeSession, Response, run_immediate
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("focused_necto_client", COMPONENT / "client.py")
client = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = client
spec.loader.exec_module(client)


class RedirectTests(unittest.TestCase):
    def test_redirects_are_classified_without_leaking_or_following(self):
        cases = [("/", "root"), ("/devices/", "devices_trailing_slash"),
                 ("/login/", "login_trailing_slash"),
                 ("/other/synthetic-secret?token=synthetic-secret", "other_path"),
                 ("http://app.getnecto.com/devices", "same_host_http"),
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

    def test_expected_login_outcomes_remain_unchanged(self):
        login = '<div id="app" data-page="{&quot;component&quot;:&quot;Auth/Login&quot;,&quot;version&quot;:&quot;v1&quot;}"></div>'
        accepted = FakeSession([Response(200, text=login), Response(302, {"Location": "/devices"})])
        run_immediate(client.NectoClient(accepted).login("sample@example.invalid", "synthetic"))
        rejected = FakeSession([Response(200, text=login), Response(302, {"Location": "/login"})])
        with self.assertRaises(client.NectoAuthError):
            run_immediate(client.NectoClient(rejected).login("sample@example.invalid", "synthetic"))

    def test_flow_logs_only_fixed_redirect_category(self):
        import test_config_flow as stubs
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
