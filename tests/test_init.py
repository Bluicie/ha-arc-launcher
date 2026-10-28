"""Tests for setup, entities, the restore service and diagnostics."""

from __future__ import annotations

import json

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.arc_launcher.const import DOMAIN, SCAN_INTERVAL
from custom_components.arc_launcher.diagnostics import async_get_config_entry_diagnostics
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .conftest import BASE, DEVICE_ID, OTHER_BASE, OTHER_HOST, OTHER_ID, STATUS, TOKEN, status

BACKUP = {"format": "arc-launcher-backup", "version": 1, "sections": [], "hiddenApps": [], "settings": {}}
RESTORED = {"categories": 2, "spacers": 0, "settings": 0, "placedApps": 5, "missingApps": []}


def calls(aioclient_mock: AiohttpClientMocker, method: str, url: str) -> list:
    return [call for call in aioclient_mock.mock_calls if call[0] == method and str(call[1]) == url]


async def add_other_tv(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, **changes) -> MockConfigEntry:
    aioclient_mock.get(
        f"{OTHER_BASE}/status", json=status(name="Slaapkamer TV", id=OTHER_ID, **changes)
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Slaapkamer TV",
        unique_id=OTHER_ID,
        data={CONF_HOST: OTHER_HOST, CONF_PORT: 47474, CONF_TOKEN: "other-token"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_and_sensors(
    hass: HomeAssistant, setup_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    assert setup_entry.state is ConfigEntryState.LOADED
    assert aioclient_mock.mock_calls[0][3]["Authorization"] == f"Bearer {TOKEN}"

    assert hass.states.get("sensor.woonkamer_tv_sync_status").state == "never"
    assert hass.states.get("sensor.woonkamer_tv_last_sync").state == "unknown"
    assert hass.states.get("sensor.woonkamer_tv_following").state == "unknown"
    layout = hass.states.get("sensor.woonkamer_tv_layout_version")
    assert layout.state == "abc123"
    assert layout.attributes["apps"] == 17
    assert hass.states.get("switch.woonkamer_tv_share_layout").state == "on"
    assert hass.states.get("switch.woonkamer_tv_automatic_sync").state == "off"
    assert hass.states.get("switch.woonkamer_tv_automatic_backup").state == "on"
    assert hass.states.get("select.woonkamer_tv_follow").state == "none"
    # Nothing to sync from yet.
    assert hass.states.get("button.woonkamer_tv_sync_now").state == "unavailable"

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, DEVICE_ID)})
    assert device.name == "Woonkamer TV"
    assert device.sw_version == "1.2.0"


async def test_sync_states(
    hass: HomeAssistant, setup_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"{BASE}/status",
        json=status(
            sync={
                "url": f"{OTHER_BASE}/backup",
                "following": "Slaapkamer TV",
                "enabled": True,
                "lastCheck": "2026-10-27T03:00:00.000Z",
                "lastError": "Connection refused",
            }
        ),
    )
    async_fire_time_changed(hass, dt_util.utcnow() + SCAN_INTERVAL)
    await hass.async_block_till_done()

    sync_status = hass.states.get("sensor.woonkamer_tv_sync_status")
    assert sync_status.state == "error"
    assert sync_status.attributes["last_error"] == "Connection refused"
    assert hass.states.get("sensor.woonkamer_tv_last_sync").state == "2026-10-27T03:00:00+00:00"
    assert hass.states.get("sensor.woonkamer_tv_following").state == "Slaapkamer TV"
    # The followed TV is not in Home Assistant, so it is shown as an extra option.
    follow = hass.states.get("select.woonkamer_tv_follow")
    assert follow.state == "Slaapkamer TV"
    assert follow.attributes["options"] == ["none", "Slaapkamer TV"]


async def test_switch(
    hass: HomeAssistant, setup_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.put(f"{BASE}/settings", json=status(sync={"enabled": True}))
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.woonkamer_tv_automatic_sync"}, blocking=True
    )
    assert calls(aioclient_mock, "PUT", f"{BASE}/settings")[0][2] == {"autoSync": True}
    assert hass.states.get("switch.woonkamer_tv_automatic_sync").state == "on"


async def test_follow_select(
    hass: HomeAssistant, setup_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    await add_other_tv(hass, aioclient_mock)
    async_fire_time_changed(hass, dt_util.utcnow() + SCAN_INTERVAL)
    await hass.async_block_till_done()
    follow = hass.states.get("select.woonkamer_tv_follow")
    assert follow.attributes["options"] == ["none", "Slaapkamer TV"]

    url = f"{OTHER_BASE}/backup"
    aioclient_mock.put(
        f"{BASE}/settings", json=status(sync={"url": url, "following": "Slaapkamer TV"})
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.woonkamer_tv_follow", "option": "Slaapkamer TV"},
        blocking=True,
    )
    body = calls(aioclient_mock, "PUT", f"{BASE}/settings")[0][2]
    assert body == {"follow": {"name": "Slaapkamer TV", "url": url, "id": OTHER_ID}}
    assert hass.states.get("select.woonkamer_tv_follow").state == "Slaapkamer TV"
    # A TV does not offer itself.
    assert hass.states.get("select.slaapkamer_tv_follow").attributes["options"] == ["none", "Woonkamer TV"]


async def test_follow_none(
    hass: HomeAssistant, setup_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.put(f"{BASE}/settings", json=STATUS)
    await hass.services.async_call(
        "select", "select_option", {"entity_id": "select.woonkamer_tv_follow", "option": "none"}, blocking=True
    )
    assert calls(aioclient_mock, "PUT", f"{BASE}/settings")[0][2] == {"follow": None}


async def test_not_sharing_tv_is_not_offered(
    hass: HomeAssistant, setup_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    await add_other_tv(hass, aioclient_mock, sharing=False)
    async_fire_time_changed(hass, dt_util.utcnow() + SCAN_INTERVAL)
    await hass.async_block_till_done()
    assert hass.states.get("select.woonkamer_tv_follow").attributes["options"] == ["none"]


async def test_buttons(
    hass: HomeAssistant, mock_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{BASE}/status", json=status(sync={"url": f"{OTHER_BASE}/backup"}))
    aioclient_mock.post(f"{BASE}/sync", json={"restored": True, "error": None})
    aioclient_mock.post(f"{BASE}/backup", json={"file": "arc-launcher-backup-20261028.json"})
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call("button", "press", {"entity_id": "button.woonkamer_tv_sync_now"}, blocking=True)
    assert calls(aioclient_mock, "POST", f"{BASE}/sync")[0][2] == {"force": True}
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.woonkamer_tv_back_up_now"}, blocking=True
    )
    assert len(calls(aioclient_mock, "POST", f"{BASE}/backup")) == 1


async def test_unauthorized_starts_reauth(
    hass: HomeAssistant, setup_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/status", status=401, json={"error": "Not paired"})
    async_fire_time_changed(hass, dt_util.utcnow() + SCAN_INTERVAL)
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_offline_tv_is_unavailable(
    hass: HomeAssistant, setup_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/status", exc=TimeoutError)
    async_fire_time_changed(hass, dt_util.utcnow() + SCAN_INTERVAL)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.woonkamer_tv_sync_status").state == "unavailable"


async def test_restore_from_file(
    hass: HomeAssistant, setup_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker, tmp_path
) -> None:
    hass.config.config_dir = str(tmp_path)
    (tmp_path / "kids.json").write_text(json.dumps(BACKUP), encoding="utf-8")
    aioclient_mock.post(f"{BASE}/restore", json=RESTORED)
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, DEVICE_ID)})

    response = await hass.services.async_call(
        DOMAIN,
        "restore_layout",
        {"device_id": device.id, "file": "kids.json"},
        blocking=True,
        return_response=True,
    )
    assert calls(aioclient_mock, "POST", f"{BASE}/restore")[0][2] == BACKUP
    assert response == {"results": {"Woonkamer TV": RESTORED}}


async def test_restore_refuses_other_files(
    hass: HomeAssistant, setup_entry: MockConfigEntry, tmp_path
) -> None:
    hass.config.config_dir = str(tmp_path / "config")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "secrets.yaml").write_text("password: x", encoding="utf-8")
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, DEVICE_ID)})
    for file in ("../outside.json", "secrets.yaml"):
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN, "restore_layout", {"device_id": device.id, "file": file}, blocking=True
            )


async def test_restore_from_other_tv(
    hass: HomeAssistant, setup_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    await add_other_tv(hass, aioclient_mock)
    aioclient_mock.get(f"{OTHER_BASE}/backup", json=BACKUP)
    aioclient_mock.post(f"{BASE}/restore", json=RESTORED)
    registry = dr.async_get(hass)
    target = registry.async_get_device(identifiers={(DOMAIN, DEVICE_ID)})
    source = registry.async_get_device(identifiers={(DOMAIN, OTHER_ID)})

    await hass.services.async_call(
        DOMAIN, "restore_layout", {"device_id": [target.id], "from_device": source.id}, blocking=True
    )
    backup_call = calls(aioclient_mock, "GET", f"{OTHER_BASE}/backup")[0]
    assert backup_call[3]["Authorization"] == "Bearer other-token"
    assert calls(aioclient_mock, "POST", f"{BASE}/restore")[0][2] == BACKUP


async def test_diagnostics(hass: HomeAssistant, setup_entry: MockConfigEntry) -> None:
    diagnostics = await async_get_config_entry_diagnostics(hass, setup_entry)
    assert diagnostics["entry"][CONF_TOKEN] == "**REDACTED**"
    assert diagnostics["status"]["layout"]["hash"] == "abc123"
    assert TOKEN not in json.dumps(diagnostics)


async def test_unload(hass: HomeAssistant, setup_entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(setup_entry.entry_id)
    assert setup_entry.state is ConfigEntryState.NOT_LOADED
