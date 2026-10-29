"""Necto Home Assistant integration, pending live verification."""

import asyncio

from aiohttp import ClientError, ClientTimeout, CookieJar
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .client import NectoAuthError, NectoClient, NectoError
from .coordinator import NectoCoordinator

PLATFORMS = (Platform.SENSOR, Platform.BINARY_SENSOR)


async def async_setup_entry(hass, entry):
    """Authenticate with an isolated cookie jar and start polling."""
    session = async_create_clientsession(hass, auto_cleanup=False, cookie_jar=CookieJar(), timeout=ClientTimeout(total=30))
    client = NectoClient(session, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    coordinator = NectoCoordinator(hass, client)
    try:
        await client.login(entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except NectoAuthError:
        await client.close()
        raise ConfigEntryAuthFailed("Necto rejected the login") from None
    except (NectoError, ClientError, asyncio.TimeoutError):
        await client.close()
        raise ConfigEntryNotReady("Cannot connect to Necto") from None
    except BaseException:
        await client.close()
        raise
    return True


async def async_unload_entry(hass, entry):
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.client.close()
    return True
