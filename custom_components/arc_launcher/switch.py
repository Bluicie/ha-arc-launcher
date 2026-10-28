"""Switches: share layout, automatic sync and automatic backup."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ArcLauncherConfigEntry
from .entity import ArcLauncherEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class ArcLauncherSwitchDescription(SwitchEntityDescription):
    setting: str
    value: Callable[[dict[str, Any]], bool | None]


SWITCHES = (
    ArcLauncherSwitchDescription(
        key="share_layout",
        setting="share",
        value=lambda status: status.get("sharing"),
    ),
    ArcLauncherSwitchDescription(
        key="auto_sync",
        setting="autoSync",
        value=lambda status: (status.get("sync") or {}).get("enabled"),
    ),
    ArcLauncherSwitchDescription(
        key="auto_backup",
        setting="autoBackup",
        value=lambda status: status.get("autoBackup"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ArcLauncherConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(ArcLauncherSwitch(coordinator, description) for description in SWITCHES)


class ArcLauncherSwitch(ArcLauncherEntity, SwitchEntity):
    _attr_entity_category = EntityCategory.CONFIG
    entity_description: ArcLauncherSwitchDescription

    def __init__(self, coordinator, description: ArcLauncherSwitchDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return super().available and self.entity_description.value(self.status) is not None

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value(self.status)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._update_settings(**{self.entity_description.setting: True})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._update_settings(**{self.entity_description.setting: False})
