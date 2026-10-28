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
        self.options: dict[str, Any] = {}
        # Quick actions as PUT /quick-actions wants them; None leaves the TV's buttons alone.
        self.quick_actions: list[dict[str, Any]] | None = None
        self._rejected_quick_actions: list[dict[str, Any]] | None = None

    @property
    def device_id(self) -> str:
        return self.config_entry.unique_id or self.config_entry.entry_id

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            status = await self.api.status()
            await self._async_sync_quick_actions(status)
        except ArcLauncherAuthError as err:
            # Turning control off on the TV unpairs every app, so pairing again is the way back.
            raise ConfigEntryAuthFailed(str(err)) from err
        except ArcLauncherError as err:
            raise UpdateFailed(str(err)) from err
        return status

    async def _async_sync_quick_actions(self, status: dict[str, Any]) -> None:
        """Push the buttons when the TV shows something else (first setup, changed options, reinstalled TV)."""
        wanted = self.quick_actions
        if wanted is None or "quickActions" not in status or wanted == self._rejected_quick_actions:
            return
        shown = [(a.get("id"), a.get("label"), a.get("icon")) for a in status["quickActions"]]
        if shown == [(a["id"], a["label"], a["icon"]) for a in wanted]:
            return
        try:
            await self.api.set_quick_actions(wanted)
        except ArcLauncherAuthError:
            raise
        except ArcLauncherError as err:
            if err.status is None:
                raise
            # Refused (for example an invalid list): don't send the same list every minute.
            self._rejected_quick_actions = wanted
            _LOGGER.warning("%s refused the quick actions: %s", self.config_entry.title, err)
            return
        status["quickActions"] = [{k: a[k] for k in ("id", "label", "icon")} for a in wanted]
