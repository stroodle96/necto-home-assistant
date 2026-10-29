"""Coordinator for a future authenticated Necto client."""

import logging
import asyncio

from aiohttp import ClientError
from homeassistant.exceptions import ConfigEntryAuthFailed

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, UPDATE_INTERVAL
from .client import NectoAuthError, NectoError
from .model import fetch_devices


class NectoCoordinator(DataUpdateCoordinator):
    """Poll the stored device readings, without requesting a device refresh."""

    def __init__(self, hass, client):
        super().__init__(hass, logger=logging.getLogger(__name__),
                         name=DOMAIN, update_interval=UPDATE_INTERVAL)
        self.client = client

    async def _async_update_data(self):
        try:
            return await fetch_devices(self.client)
        except NectoAuthError:
            raise ConfigEntryAuthFailed("Necto rejected the login") from None
        except (NectoError, ClientError, asyncio.TimeoutError, ValueError):
            raise UpdateFailed("Unable to update Necto devices") from None
