"""Tests for the quick actions: options flow, pushing to the TV, and the webhook."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_mock_service,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.arc_launcher.const import CONF_WEBHOOK_ID, DOMAIN, EVENT_QUICK_ACTION
from custom_components.arc_launcher.quick_actions import webhook_url
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component

from .conftest import BASE, DEVICE_ID, HOST, TOKEN, status

HA_URL = "http://192.0.2.1:8123"
WEBHOOK_ID = "test-webhook"
ACTIONS = [
    {"id": "movie_night", "label": "Movie night", "icon": "movie", "target": "scene.movie"},
    {"id": "lights_off", "label": "Lights off", "icon": "lightbulb-off", "target": None},
]
URL = f"{HA_URL}/api/webhook/{WEBHOOK_ID}"
TV_ACTIONS = [{"id": a["id"], "label": a["label"], "icon": a["icon"], "url": URL} for a in ACTIONS]
SHOWN = [{"id": a["id"], "label": a["label"], "icon": a["icon"]} for a in ACTIONS]


@pytest.fixture
async def ha_with_webhook(hass: HomeAssistant) -> HomeAssistant:
    hass.config.internal_url = HA_URL
    assert await async_setup_component(hass, "webhook", {})
    return hass


def make_entry(hass: HomeAssistant, actions: list | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Woonkamer TV",
        unique_id=DEVICE_ID,
        data={CONF_HOST: HOST, CONF_PORT: 47474, CONF_TOKEN: TOKEN, CONF_WEBHOOK_ID: WEBHOOK_ID},
        options={"quick_actions": ACTIONS if actions is None else actions},
    )
    entry.add_to_hass(hass)
    return entry


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def puts(aioclient_mock: AiohttpClientMocker) -> list:
    return [call[2] for call in aioclient_mock.mock_calls if call[0] == "PUT" and str(call[1]).endswith("/quick-actions")]


async def test_pushed_on_setup(
    ha_with_webhook: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    hass = ha_with_webhook
    aioclient_mock.get(f"{BASE}/status", json=status(quickActions=[]))
    aioclient_mock.put(f"{BASE}/quick-actions", json={"quickActions": 2})
    await setup(hass, make_entry(hass))
    assert puts(aioclient_mock) == [{"actions": TV_ACTIONS}]


async def test_not_pushed_when_tv_has_them(
    ha_with_webhook: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    hass = ha_with_webhook
    aioclient_mock.get(f"{BASE}/status", json=status(quickActions=SHOWN))
    await setup(hass, make_entry(hass))
    assert puts(aioclient_mock) == []


async def test_older_launcher_is_left_alone(
    ha_with_webhook: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    hass = ha_with_webhook
    aioclient_mock.get(f"{BASE}/status", json=status())
    entry = make_entry(hass)
    await setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert puts(aioclient_mock) == []


async def test_refused_list_does_not_fail_setup(
    ha_with_webhook: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    hass = ha_with_webhook
    aioclient_mock.get(f"{BASE}/status", json=status(quickActions=[]))
    aioclient_mock.put(f"{BASE}/quick-actions", status=400, json={"error": "label too long"})
    entry = make_entry(hass)
    await setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED


async def test_webhook_runs_target_and_fires_event(
    ha_with_webhook: HomeAssistant, aioclient_mock: AiohttpClientMocker, hass_client_no_auth
) -> None:
    hass = ha_with_webhook
    aioclient_mock.get(f"{BASE}/status", json=status(quickActions=SHOWN))
    await setup(hass, make_entry(hass))
    scene_calls = async_mock_service(hass, "scene", "turn_on")
    events = async_capture_events(hass, EVENT_QUICK_ACTION)
    client = await hass_client_no_auth()

    body = {"action": "movie_night", "device": DEVICE_ID, "name": "Woonkamer TV"}
    response = await client.post(f"/api/webhook/{WEBHOOK_ID}", json=body)
    await hass.async_block_till_done()
    assert response.status == 200
    assert scene_calls[0].data == {"entity_id": "scene.movie"}
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, DEVICE_ID)})
    assert events[0].data == {"device_id": device.id, "action": "movie_night", "label": "Movie night"}
    event_state = hass.states.get("event.woonkamer_tv_quick_action")
    assert event_state.attributes["event_type"] == "movie_night"
    assert event_state.attributes["event_types"] == ["movie_night", "lights_off"]
    assert event_state.attributes["label"] == "Movie night"

    # Event only: no service call.
    response = await client.post(f"/api/webhook/{WEBHOOK_ID}", json={**body, "action": "lights_off"})
    await hass.async_block_till_done()
    assert response.status == 200
    assert len(scene_calls) == 1
    assert events[1].data["action"] == "lights_off"

    response = await client.post(f"/api/webhook/{WEBHOOK_ID}", json={**body, "action": "nope"})
    assert response.status == 404
    response = await client.post(f"/api/webhook/{WEBHOOK_ID}", data="not json")
    assert response.status == 400


async def test_unload_clears_the_tv(
    ha_with_webhook: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    hass = ha_with_webhook
    aioclient_mock.get(f"{BASE}/status", json=status(quickActions=SHOWN))
    aioclient_mock.put(f"{BASE}/quick-actions", json={"quickActions": 0})
    entry = make_entry(hass)
    await setup(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert puts(aioclient_mock) == [{"actions": []}]


async def test_webhook_id_is_created(
    ha_with_webhook: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    hass = ha_with_webhook
    aioclient_mock.get(f"{BASE}/status", json=status())
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Woonkamer TV",
        unique_id=DEVICE_ID,
        data={CONF_HOST: HOST, CONF_PORT: 47474, CONF_TOKEN: TOKEN},
    )
    entry.add_to_hass(hass)
    await setup(hass, entry)
    assert len(entry.data[CONF_WEBHOOK_ID]) >= 32
    # No buttons configured, so no event entity.
    assert hass.states.get("event.woonkamer_tv_quick_action") is None


async def test_webhook_url_uses_ip(hass: HomeAssistant) -> None:
    hass.config.internal_url = "http://homeassistant.local:8123"
    hass.config.api = SimpleNamespace(local_ip="192.0.2.5", port=8123, use_ssl=False)
    assert webhook_url(hass, "abc") == "http://192.0.2.5:8123/api/webhook/abc"
    hass.config.internal_url = "https://ha.example.com"
    assert webhook_url(hass, "abc") == "https://ha.example.com/api/webhook/abc"


async def test_options_flow(
    ha_with_webhook: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    hass = ha_with_webhook
    aioclient_mock.get(f"{BASE}/status", json=status(quickActions=[]))
    aioclient_mock.put(f"{BASE}/quick-actions", json={"quickActions": 1})
    entry = make_entry(hass, actions=[])
    await setup(hass, entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["add", "save"]

    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "add"})
    assert result["step_id"] == "action"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"label": "x" * 25, "icon": "movie"}
    )
    assert result["errors"] == {"label": "invalid_label"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"label": "Movie night", "icon": "movie", "target": "scene.movie"}
    )
    assert result["menu_options"] == ["add", "edit", "remove", "save"]

    # Same label again gets its own id.
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "add"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"label": "Movie night", "icon": "sofa"}
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "edit"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"action": "movie_night_2"})
    assert result["step_id"] == "action"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"label": "Couch", "icon": "sofa"}
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "remove"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"actions": ["movie_night"]})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "save"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert entry.options["quick_actions"] == [
        {"id": "movie_night_2", "label": "Couch", "icon": "sofa", "target": None}
    ]
    # Saving reloads the entry, which sends the new list to the TV.
    assert puts(aioclient_mock)[-1] == {
        "actions": [{"id": "movie_night_2", "label": "Couch", "icon": "sofa", "url": URL}]
    }
    assert hass.states.get("event.woonkamer_tv_quick_action").attributes["event_types"] == ["movie_night_2"]
