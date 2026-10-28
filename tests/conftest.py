"""Fixtures for the Arc Launcher tests."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.arc_launcher.const import DOMAIN
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
from homeassistant.core import HomeAssistant

HOST = "192.0.2.10"
OTHER_HOST = "192.0.2.11"
BASE = f"http://{HOST}:47474/arc-launcher/v1"
OTHER_BASE = f"http://{OTHER_HOST}:47474/arc-launcher/v1"
DEVICE_ID = "device-woonkamer"
OTHER_ID = "device-slaapkamer"
TOKEN = "secret-token"

INFO = {
    "app": "arc-launcher",
    "name": "Woonkamer TV",
    "id": DEVICE_ID,
    "api": 1,
    "sharing": True,
    "control": True,
    "web": False,
}

STATUS = {
    **INFO,
    "appVersion": "1.2.0",
    "autoBackup": True,
    "sync": {
        "url": "",
        "following": None,
        "enabled": False,
        "syncing": False,
        "lastCheck": None,
        "lastError": None,
    },
    "layout": {"hash": "abc123", "sections": 4, "apps": 17},
}


def status(**changes: Any) -> dict[str, Any]:
    data = copy.deepcopy(STATUS)
    sync = changes.pop("sync", None)
    data.update(changes)
    if sync is not None:
        data["sync"].update(sync)
    return data


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def mock_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Woonkamer TV",
        unique_id=DEVICE_ID,
        data={CONF_HOST: HOST, CONF_PORT: 47474, CONF_TOKEN: TOKEN},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def setup_entry(
    hass: HomeAssistant, mock_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> MockConfigEntry:
    aioclient_mock.get(f"{BASE}/status", json=STATUS)
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    return mock_entry
