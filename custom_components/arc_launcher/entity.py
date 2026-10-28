"""Base entity for the Arc Launcher integration."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, TypeVar

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import ArcLauncherAuthError, ArcLauncherError
from .const import DOMAIN
from .coordinator import ArcLauncherCoordinator

_T = TypeVar("_T")


class ArcLauncherEntity(CoordinatorEntity[ArcLauncherCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: ArcLauncherCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_translation_key = key
        self._attr_unique_id = f"{coordinator.device_id}_{key}"
        status = coordinator.data
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_id)},
            manufacturer="Arc Launcher",
            model="Arc Launcher",
            name=status.get("name") or coordinator.config_entry.title,
            sw_version=status.get("appVersion"),
        )

    @property
    def status(self) -> dict[str, Any]:
        return self.coordinator.data

    @property
    def sync(self) -> dict[str, Any] | None:
        """None when this launcher build has no remote sync."""
        return self.coordinator.data.get("sync")

    async def _call(self, request: Awaitable[_T]) -> _T:
        """Run an API call and turn its errors into errors the frontend shows."""
        try:
            return await request
        except ArcLauncherAuthError as err:
            self.coordinator.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(str(err)) from err
        except ArcLauncherError as err:
            raise HomeAssistantError(str(err)) from err

    async def _update_settings(self, **settings: Any) -> None:
        status = await self._call(self.coordinator.api.update_settings(**settings))
        self.coordinator.async_set_updated_data(status)
