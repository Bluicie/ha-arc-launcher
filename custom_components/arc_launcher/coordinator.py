"""Coordinator for the Arc Launcher integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ArcLauncherApi, ArcLauncherAuthError, ArcLauncherError
from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

type ArcLauncherConfigEntry = ConfigEntry[ArcLauncherCoordinator]


class ArcLauncherCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls GET /status of one TV."""

    config_entry: ArcLauncherConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ArcLauncherConfigEntry, api: ArcLauncherApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {api.host}",
            update_interval=SCAN_INTERVAL,
        )
        self.api = api

    @property
    def device_id(self) -> str:
        return self.config_entry.unique_id or self.config_entry.entry_id

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.api.status()
        except ArcLauncherAuthError as err:
            # Turning control off on the TV unpairs every app, so pairing again is the way back.
            raise ConfigEntryAuthFailed(str(err)) from err
        except ArcLauncherError as err:
            raise UpdateFailed(str(err)) from err
