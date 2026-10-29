"""Experimental user-driven sign-in for Necto."""

import asyncio
import logging

from aiohttp import ClientError, ClientTimeout, CookieJar
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .client import NectoAuthError, NectoClient, NectoError, NectoRedirectError, release_session
from .const import DOMAIN
from .model import fetch_devices

_LOGGER = logging.getLogger(__name__)
_SAFE_ERRORS = {
    "Unable to load the login page": "login_page_request",
    "Login page did not provide expected CSRF or application data": "login_page_data",
    "Necto returned an unexpected login response": "login_response",
    "Necto returned an unexpected login redirect": "login_redirect",
    "Necto login session could not be verified": "login_session_unverified",
    "Unable to retrieve Necto devices": "device_request",
    "Necto returned an unexpected response": "device_response",
}


def _schema(username=True):
    fields = {vol.Required(CONF_PASSWORD): selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))}
    if username:
        fields = {vol.Required(CONF_USERNAME): str, **fields}
    return vol.Schema(fields)


async def _validate(hass, username, password):
    session = async_create_clientsession(hass, auto_cleanup=False, cookie_jar=CookieJar(), timeout=ClientTimeout(total=30))
    stage = "login"
    try:
        client = NectoClient(session)
        await client.login(username, password)
        stage = "devices"
        await fetch_devices(client)
    except (NectoError, ClientError, asyncio.TimeoutError, ValueError) as exc:
        if isinstance(exc, NectoAuthError):
            reason = "authentication"
        elif isinstance(exc, NectoRedirectError):
            reason = "login_redirect_" + exc.category
        elif isinstance(exc, NectoError):
            reason = _SAFE_ERRORS.get(str(exc), "service_error")
        elif isinstance(exc, asyncio.TimeoutError):
            reason = "timeout"
        elif isinstance(exc, ClientError):
            reason = "network_error"
        else:
            reason = "invalid_data"
        _LOGGER.warning("Necto setup check failed: stage=%s reason=%s", stage, reason)
        raise
    finally:
        release_session(session)


class NectoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(username.casefold())
            self._abort_if_unique_id_configured()
            try:
                await _validate(self.hass, username, user_input[CONF_PASSWORD])
            except NectoAuthError:
                errors["base"] = "invalid_auth"
            except (NectoError, ClientError, asyncio.TimeoutError, ValueError):
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title="Necto", data={CONF_USERNAME: username,
                                                                   CONF_PASSWORD: user_input[CONF_PASSWORD]})
        return self.async_show_form(step_id="user", data_schema=_schema(), errors=errors)

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors = {}
        if user_input is not None:
            entry = self._get_reauth_entry()
            try:
                await _validate(self.hass, entry.data[CONF_USERNAME], user_input[CONF_PASSWORD])
            except NectoAuthError:
                errors["base"] = "invalid_auth"
            except (NectoError, ClientError, asyncio.TimeoutError, ValueError):
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]})
        return self.async_show_form(step_id="reauth_confirm", data_schema=_schema(False), errors=errors)

    async def async_step_reconfigure(self, user_input=None):
        """Allow a password update without losing device history."""
        errors = {}
        if user_input is not None:
            entry = self._get_reconfigure_entry()
            try:
                await _validate(self.hass, entry.data[CONF_USERNAME], user_input[CONF_PASSWORD])
            except NectoAuthError:
                errors["base"] = "invalid_auth"
            except (NectoError, ClientError, asyncio.TimeoutError, ValueError):
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]})
        return self.async_show_form(step_id="reconfigure", data_schema=_schema(False), errors=errors)
