"""Service arc_launcher.restore_layout."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .api import ArcLauncherError
from .const import BACKUP_FORMAT, DOMAIN
from .coordinator import ArcLauncherCoordinator

SERVICE_RESTORE_LAYOUT = "restore_layout"
ATTR_FILE = "file"
ATTR_FROM_DEVICE = "from_device"

RESTORE_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string]),
            vol.Exclusive(ATTR_FILE, "source"): cv.string,
            vol.Exclusive(ATTR_FROM_DEVICE, "source"): cv.string,
        }
    ),
    cv.has_at_least_one_key(ATTR_FILE, ATTR_FROM_DEVICE),
)


def _coordinator(hass: HomeAssistant, device_id: str) -> ArcLauncherCoordinator:
    device = dr.async_get(hass).async_get(device_id)
    if device is not None:
        for entry_id in device.config_entries:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry and entry.domain == DOMAIN and entry.state is ConfigEntryState.LOADED:
                return entry.runtime_data
    raise ServiceValidationError(f"{device_id} is not a loaded Arc Launcher TV")


def _read_backup(hass: HomeAssistant, file: str) -> dict[str, Any]:
    """Read a settings file from the config folder (or an allowlisted folder)."""
    path = Path(hass.config.path(file)).resolve()
    config_dir = Path(hass.config.config_dir).resolve()
    if not (path.is_relative_to(config_dir) or hass.config.is_allowed_path(str(path))):
        raise ServiceValidationError(f"{file} is not inside the Home Assistant config folder")
    try:
        backup = json.loads(path.read_text(encoding="utf-8"))
    except OSError as err:
        raise ServiceValidationError(f"Cannot read {file}: {err}") from err
    except ValueError as err:
        raise ServiceValidationError(f"{file} is not valid JSON") from err
    if not isinstance(backup, dict) or backup.get("format") != BACKUP_FORMAT:
        raise ServiceValidationError(f"{file} is not an Arc Launcher settings file")
    return backup


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    async def restore_layout(call: ServiceCall) -> ServiceResponse:
        targets = [_coordinator(hass, device_id) for device_id in call.data[ATTR_DEVICE_ID]]
        try:
            if ATTR_FILE in call.data:
                backup = await hass.async_add_executor_job(_read_backup, hass, call.data[ATTR_FILE])
            else:
                backup = await _coordinator(hass, call.data[ATTR_FROM_DEVICE]).api.get_backup()
            results = {}
            for target in targets:
                results[target.config_entry.title] = await target.api.restore(backup)
                await target.async_request_refresh()
        except ArcLauncherError as err:
            raise HomeAssistantError(f"Restore failed: {err}") from err
        return {"results": results}

    hass.services.async_register(
        DOMAIN,
        SERVICE_RESTORE_LAYOUT,
        restore_layout,
        schema=RESTORE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
