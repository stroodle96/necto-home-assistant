"""Home Assistant integration tests with synthetic responses and no network."""

from unittest.mock import AsyncMock, patch
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import pytest
from types import SimpleNamespace

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry
from custom_components.necto.client import NectoAuthError, NectoError

DOMAIN = "necto"


async def test_config_flow_creates_entry(hass):
    """A validated synthetic login is stored by the normal config flow."""
    with patch("custom_components.necto.config_flow._validate", new_callable=AsyncMock), patch(
        "custom_components.necto.async_setup_entry", new_callable=AsyncMock, return_value=True
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USERNAME: "sample@example.invalid", CONF_PASSWORD: "synthetic"}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_config_flow_rejects_bad_credentials(hass):
    with patch("custom_components.necto.config_flow._validate", new_callable=AsyncMock,
               side_effect=NectoAuthError("rejected")):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USERNAME: "sample@example.invalid", CONF_PASSWORD: "synthetic"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "invalid_auth"


async def test_validation_detaches_private_ha_session_without_close_warning(hass, caplog):
    from homeassistant.helpers.aiohttp_client import async_create_clientsession
    from custom_components.necto.config_flow import _validate
    sessions = []

    def create_session(hass, **kwargs):
        assert kwargs["auto_cleanup"] is False
        session = async_create_clientsession(hass, **kwargs)
        sessions.append(session)
        return session

    with patch("custom_components.necto.config_flow.async_create_clientsession", side_effect=create_session), patch(
        "custom_components.necto.client.NectoClient.login", new_callable=AsyncMock,
        side_effect=NectoAuthError("synthetic")
    ):
        with pytest.raises(NectoAuthError):
            await _validate(hass, "sample@example.invalid", "synthetic")
    assert sessions[0].closed
    assert "closes the Home Assistant aiohttp session" not in caplog.text


async def test_reauth_updates_password(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="sample@example.invalid",
                            data={CONF_USERNAME: "sample@example.invalid", CONF_PASSWORD: "old-synthetic"})
    entry.add_to_hass(hass)
    with patch("custom_components.necto.config_flow._validate", new_callable=AsyncMock), patch(
        "custom_components.necto.async_setup_entry", new_callable=AsyncMock, return_value=True
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "reauth", "entry_id": entry.entry_id}, data=entry.data
        )
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "new-synthetic"}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new-synthetic"


async def test_setup_creates_entities_from_cloud_data(hass):
    """The actual HA runtime loads entities from a synthetic device page."""
    hass.config.units = US_CUSTOMARY_SYSTEM
    report_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    payload = {"props": {"user": {"meta": {"unit": "f"}}, "devices": {
        "data": [{"device_id": "synthetic-device", "name": "Example", "is_offline": False,
                  "is_powered_off": False, "latest_report_at": report_time,
                  "latest_report": {"temp_val": 64.5, "humi_val": 51, "event": "power off"}}],
        "meta": {"current_page": 1, "last_page": 1},
    }}}
    client = SimpleNamespace(login=AsyncMock(), get_device_page=AsyncMock(return_value=payload), close=AsyncMock())
    session = SimpleNamespace(close=AsyncMock())
    entry = MockConfigEntry(domain=DOMAIN, unique_id="sample@example.invalid",
                            data={CONF_USERNAME: "sample@example.invalid", CONF_PASSWORD: "synthetic"})
    entry.add_to_hass(hass)
    with patch("custom_components.necto.NectoClient", return_value=client), patch(
        "custom_components.necto.async_create_clientsession", return_value=session
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        registry = er.async_get(hass)
        temp_id = registry.async_get_entity_id("sensor", DOMAIN, "synthetic-device_temperature")
        humidity_id = registry.async_get_entity_id("sensor", DOMAIN, "synthetic-device_humidity")
        report_id = registry.async_get_entity_id("sensor", DOMAIN, "synthetic-device_last_report")
        event_id = registry.async_get_entity_id("sensor", DOMAIN, "synthetic-device_event")
        offline_id = registry.async_get_entity_id("binary_sensor", DOMAIN, "synthetic-device_offline")
        power_id = registry.async_get_entity_id("binary_sensor", DOMAIN, "synthetic-device_powered_off")
        assert hass.states.get(temp_id).state == "64.5"
        assert hass.states.get(offline_id).state == "off"
        assert hass.states.get(power_id).state == "off"
        stopped = deepcopy(payload)
        stopped["props"]["devices"]["data"][0]["is_powered_off"] = True
        client.get_device_page.return_value = stopped
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(temp_id).state == "64.5"
        assert hass.states.get(humidity_id).state == "51"
        assert hass.states.get(power_id).state == "on"
        assert hass.states.get(offline_id).state == "off"
        assert hass.states.get(report_id).state not in ("unavailable", "unknown")
        assert hass.states.get(event_id).state == "power off"
        client.get_device_page.side_effect = [NectoError("temporary failure"), payload]
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        assert not entry.runtime_data.last_update_success
        assert hass.states.get(temp_id).state == "64.5"
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        assert entry.runtime_data.last_update_success
        assert hass.states.get(temp_id).state == "64.5"
        assert await hass.config_entries.async_unload(entry.entry_id)
        client.close.assert_awaited_once()


async def test_fresh_measurements_expire_without_another_poll(hass):
    """A scheduled transition updates the entity even if no new data arrives."""
    hass.config.units = US_CUSTOMARY_SYSTEM
    from custom_components.necto import sensor as component_sensor
    clock = [datetime.now(timezone.utc)]
    callbacks = []
    def schedule(hass, callback, when):
        callbacks.append((callback, when))
        return lambda: None
    report_time = (clock[0] - timedelta(minutes=59)).isoformat()
    payload = {"props": {"user": {"meta": {"unit": "f"}}, "devices": {
        "data": [{"device_id": "synthetic-device", "name": "Example", "is_offline": True,
                  "is_powered_off": True, "latest_report_at": report_time,
                  "latest_report": {"temp_val": 64.5, "humi_val": 51}}],
        "meta": {"current_page": 1, "last_page": 1},
    }}}
    client = SimpleNamespace(login=AsyncMock(), get_device_page=AsyncMock(return_value=payload), close=AsyncMock())
    session = SimpleNamespace(close=AsyncMock())
    entry = MockConfigEntry(domain=DOMAIN, unique_id="sample@example.invalid",
                            data={CONF_USERNAME: "sample@example.invalid", CONF_PASSWORD: "synthetic"})
    entry.add_to_hass(hass)
    with patch("custom_components.necto.NectoClient", return_value=client), patch(
        "custom_components.necto.async_create_clientsession", return_value=session
    ), patch.object(component_sensor, "dt_util", SimpleNamespace(utcnow=lambda: clock[0])), patch.object(
        component_sensor, "async_track_point_in_utc_time", side_effect=schedule
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        registry = er.async_get(hass)
        temp_id = registry.async_get_entity_id("sensor", DOMAIN, "synthetic-device_temperature")
        assert hass.states.get(temp_id).state == "64.5"
        clock[0] += timedelta(minutes=1)
        for callback, when in list(callbacks):
            callback(when)
        await hass.async_block_till_done()
        assert hass.states.get(temp_id).state == "unavailable"
        assert client.get_device_page.await_count == 1
        assert await hass.config_entries.async_unload(entry.entry_id)
