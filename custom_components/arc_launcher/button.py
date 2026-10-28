"""Buttons: sync now and back up now."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ArcLauncherConfigEntry
from .entity import ArcLauncherEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ArcLauncherConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([SyncNowButton(coordinator, "sync_now"), BackupNowButton(coordinator, "backup_now")])


class SyncNowButton(ArcLauncherEntity, ButtonEntity):
    @property
    def available(self) -> bool:
        return super().available and bool((self.sync or {}).get("url"))

    async def async_press(self) -> None:
        result = await self._call(self.coordinator.api.sync(force=True))
        if result.get("error"):
            # Not raised: one TV that cannot reach the shared layout should not stop an automation
            # syncing several TVs. The sync status sensor shows the error.
            _LOGGER.warning("Sync of %s failed: %s", self.coordinator.config_entry.title, result["error"])
        await self.coordinator.async_request_refresh()


class BackupNowButton(ArcLauncherEntity, ButtonEntity):
    async def async_press(self) -> None:
        await self._call(self.coordinator.api.backup())
