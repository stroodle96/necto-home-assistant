"""Exercise configuration behavior with stubs, not Home Assistant itself."""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parents[1] / "custom_components" / "necto"


def module(name, **values):
    result = ModuleType(name)
    result.__dict__.update(values)
    sys.modules[name] = result
    return result


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


def run_immediate(coro):
    try:
        coro.send(None)
    except StopIteration as result:
        return result.value
    raise AssertionError("Fake operation unexpectedly suspended")


class Flow:
    def __init_subclass__(cls, **kwargs):
        return None

    async def async_set_unique_id(self, value):
        self.unique_id = value

    def _abort_if_unique_id_configured(self):
        pass

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}

    def _get_reauth_entry(self):
        return SimpleNamespace(data={"username": "test@example.invalid"})

    def _get_reconfigure_entry(self):
        return SimpleNamespace(data={"username": "test@example.invalid"})

    def async_update_reload_and_abort(self, entry, **kwargs):
        return {"type": "abort", **kwargs}


module("aiohttp", ClientError=type("ClientError", (Exception,), {}),
       ClientTimeout=lambda **kwargs: None, CookieJar=lambda: None)
class Marker:
    def __init__(self, value):
        self.value = value


module("voluptuous", Required=Marker, Schema=lambda value: value)
module("homeassistant", config_entries=SimpleNamespace(ConfigFlow=Flow))
module("homeassistant.const", CONF_USERNAME="username", CONF_PASSWORD="password")
module("homeassistant.helpers", selector=SimpleNamespace(
    TextSelector=lambda value: value, TextSelectorConfig=lambda **kwargs: kwargs,
    TextSelectorType=SimpleNamespace(PASSWORD="password")))
module("homeassistant.helpers.aiohttp_client", async_create_clientsession=lambda *args, **kwargs: None)
package = module("necto_flowdraft")
package.__path__ = [str(ROOT)]
load("necto_flowdraft.const", "const.py")
client = load("necto_flowdraft.client", "client.py")
load("necto_flowdraft.model", "model.py")
flow_module = load("necto_flowdraft.config_flow", "config_flow.py")


class ConfigFlowTests(unittest.TestCase):
    def test_validation_closes_session_even_when_login_fails(self):
        class Session:
            closed = False
            async def close(self):
                self.closed = True
        class RejectingClient:
            def __init__(self, session):
                pass
            async def login(self, username, password):
                raise client.NectoAuthError("synthetic")
        session = Session()
        with patch.object(flow_module, "async_create_clientsession", return_value=session), patch.object(flow_module, "NectoClient", RejectingClient):
            with self.assertRaises(client.NectoAuthError):
                run_immediate(flow_module._validate(object(), "example", "synthetic"))
        self.assertTrue(session.closed)

    def test_rejected_login_produces_generic_error(self):
        async def reject(*args):
            raise client.NectoAuthError("synthetic-secret")
        flow = flow_module.NectoConfigFlow()
        flow.hass = object()
        with patch.object(flow_module, "_validate", reject):
            result = run_immediate(flow.async_step_user({"username": "TEST@example.invalid", "password": "synthetic-secret"}))
        self.assertEqual(result["errors"], {"base": "invalid_auth"})
        self.assertNotIn("synthetic-secret", repr(result))

    def test_accepted_login_creates_user_entry(self):
        async def accept(*args):
            pass
        flow = flow_module.NectoConfigFlow()
        flow.hass = object()
        with patch.object(flow_module, "_validate", accept):
            result = run_immediate(flow.async_step_user({"username": " TEST@example.invalid ", "password": "synthetic"}))
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(flow.unique_id, "test@example.invalid")

    def test_reauth_updates_password(self):
        async def accept(*args):
            pass
        flow = flow_module.NectoConfigFlow()
        flow.hass = object()
        with patch.object(flow_module, "_validate", accept):
            result = run_immediate(flow.async_step_reauth_confirm({"password": "new-synthetic"}))
        self.assertEqual(result["data_updates"], {"password": "new-synthetic"})

    def test_reconfigure_validates_and_preserves_account(self):
        calls = []
        async def accept(hass, username, password):
            calls.append((username, password))
        flow = flow_module.NectoConfigFlow()
        flow.hass = object()
        with patch.object(flow_module, "_validate", accept):
            result = run_immediate(flow.async_step_reconfigure({"password": "new-synthetic"}))
        self.assertEqual(calls, [("test@example.invalid", "new-synthetic")])
        self.assertEqual(result["data_updates"], {"password": "new-synthetic"})

    def test_reconfigure_rejects_invalid_credentials_without_leaking(self):
        async def reject(*args):
            raise client.NectoAuthError("synthetic-secret")
        flow = flow_module.NectoConfigFlow()
        flow.hass = object()
        with patch.object(flow_module, "_validate", reject):
            result = run_immediate(flow.async_step_reconfigure({"password": "synthetic-secret"}))
        self.assertEqual(result["errors"], {"base": "invalid_auth"})
        self.assertNotIn("synthetic-secret", repr(result))
