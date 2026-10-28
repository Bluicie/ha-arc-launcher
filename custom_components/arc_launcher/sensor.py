"""Sensors: last sync, sync status, followed TV and layout version."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import ArcLauncherConfigEntry
from .entity import ArcLauncherEntity

PARALLEL_UPDATES = 0

SYNC_STATES = ["never", "syncing", "ok", "error"]


def _sync_status(status: dict[str, Any]) -> str | None:
    sync = status.get("sync")
    if sync is None:
        return None
    if sync.get("syncing"):
        return "syncing"
    if sync.get("lastError"):
        return "error"
    if not sync.get("lastCheck"):
        return "never"
    return "ok"


def _last_sync(status: dict[str, Any]) -> datetime | None:
    last_check = (status.get("sync") or {}).get("lastCheck")
    return dt_util.parse_datetime(last_check) if last_check else None


def _following(status: dict[str, Any]) -> str | None:
    sync = status.get("sync") or {}
    if not sync.get("url"):
        return None
    return sync.get("following") or sync["url"]


@dataclass(frozen=True, kw_only=True)
class ArcLauncherSensorDescription(SensorEntityDescription):
    value: Callable[[dict[str, Any]], Any]
    attributes: Callable[[dict[str, Any]], dict[str, Any]] | None = None


SENSORS = (
    ArcLauncherSensorDescription(
        key="last_sync",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=_last_sync,
    ),
    ArcLauncherSensorDescription(
        key="sync_status",
        device_class=SensorDeviceClass.ENUM,
        options=SYNC_STATES,
        value=_sync_status,
        attributes=lambda status: {"last_error": (status.get("sync") or {}).get("lastError")},
    ),
    ArcLauncherSensorDescription(
        key="following",
        value=_following,
        attributes=lambda status: {"url": (status.get("sync") or {}).get("url") or None},
    ),
    ArcLauncherSensorDescription(
        key="layout_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda status: (status.get("layout") or {}).get("hash"),
        attributes=lambda status: {
            "sections": (status.get("layout") or {}).get("sections"),
            "apps": (status.get("layout") or {}).get("apps"),
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ArcLauncherConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(ArcLauncherSensor(coordinator, description) for description in SENSORS)


class ArcLauncherSensor(ArcLauncherEntity, SensorEntity):
    entity_description: ArcLauncherSensorDescription

    def __init__(self, coordinator, description: ArcLauncherSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self.status)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attributes is None:
            return None
        return self.entity_description.attributes(self.status)
