"""The Arc Launcher integration."""

from __future__ import annotations

import logging

from homeassistant.components import webhook
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import ArcLauncherApi, ArcLauncherError
from .const import CONF_WEBHOOK_ID, DEFAULT_PORT, DOMAIN
from .coordinator import ArcLauncherConfigEntry, ArcLauncherCoordinator
from .quick_actions import configured_actions, register_webhook, tv_payload, webhook_url
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BUTTON, Platform.EVENT, Platform.SELECT, Platform.SENSOR, Platform.SWITCH]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ArcLauncherConfigEntry) -> bool:
    if CONF_WEBHOOK_ID not in entry.data:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_WEBHOOK_ID: webhook.async_generate_id()}
        )

    api = ArcLauncherApi(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data.get(CONF_PORT, DEFAULT_PORT),
        entry.data[CONF_TOKEN],
    )
    coordinator = ArcLauncherCoordinator(hass, entry, api)
    coordinator.options = dict(entry.options)
    url = webhook_url(hass, entry.data[CONF_WEBHOOK_ID])
    if url is None:
        if configured_actions(entry):
            _LOGGER.warning(
                "No local URL for Home Assistant (Settings > System > Network), so %s gets no quick actions",
                entry.title,
            )
    else:
        coordinator.quick_actions = tv_payload(entry, url)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    register_webhook(hass, entry)
    entry.async_on_unload(lambda: webhook.async_unregister(hass, entry.data[CONF_WEBHOOK_ID]))
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ArcLauncherConfigEntry) -> None:
    # Data updates (new host, new token) reload by themselves; only changed options need it here.
    if entry.options != entry.runtime_data.options:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ArcLauncherConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    coordinator = entry.runtime_data
    if coordinator.data and coordinator.data.get("quickActions"):
        # The webhook is gone, so remove the buttons; a reload pushes them again.
        try:
            await coordinator.api.set_quick_actions([])
        except ArcLauncherError as err:
            _LOGGER.debug("Could not remove the quick actions from %s: %s", entry.title, err)
    return True
