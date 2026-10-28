"""Tests for the Arc Launcher config flow."""

from __future__ import annotations

from ipaddress import ip_address

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.arc_launcher.const import DOMAIN
from homeassistant.config_entries import SOURCE_USER, SOURCE_ZEROCONF
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .conftest import BASE, DEVICE_ID, HOST, INFO, STATUS, TOKEN

PAIRED = {"token": TOKEN, "id": DEVICE_ID, "name": "Woonkamer TV"}

DISCOVERY = ZeroconfServiceInfo(
    ip_address=ip_address(HOST),
    ip_addresses=[ip_address(HOST)],
    hostname="woonkamer.local.",
    name="Woonkamer TV._arclauncher._tcp.local.",
    port=47474,
    type="_arclauncher._tcp.local.",
    properties={"id": DEVICE_ID, "api": "1", "share": "1", "control": "1", "web": "0"},
)


def mock_tv(aioclient_mock: AiohttpClientMocker, confirm_status: int = 200) -> None:
    aioclient_mock.get(f"{BASE}/info", json=INFO)
    aioclient_mock.get(f"{BASE}/status", json=STATUS)
    aioclient_mock.post(f"{BASE}/pair", status=202, json={"expiresIn": 120})
    if confirm_status == 200:
        aioclient_mock.post(f"{BASE}/pair/confirm", json=PAIRED)
    else:
        aioclient_mock.post(f"{BASE}/pair/confirm", status=confirm_status, json={"error": "Wrong code"})


async def test_manual_flow(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    mock_tv(aioclient_mock)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: HOST, CONF_PORT: 47474})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pair"
    pair_call = next(call for call in aioclient_mock.mock_calls if str(call[1]).endswith("/pair"))
    assert pair_call[2] == {"client": "Home Assistant"}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "123 456"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Woonkamer TV"
    assert result["data"] == {CONF_HOST: HOST, CONF_PORT: 47474, CONF_TOKEN: TOKEN}
    assert result["result"].unique_id == DEVICE_ID
    confirm_call = next(call for call in aioclient_mock.mock_calls if str(call[1]).endswith("/confirm"))
    assert confirm_call[2] == {"code": "123456"}


async def test_invalid_host(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "tv.example.com", CONF_PORT: 47474}
    )
    assert result["errors"] == {CONF_HOST: "invalid_host"}


async def test_cannot_connect(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{BASE}/info", exc=TimeoutError)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: HOST, CONF_PORT: 47474})
    assert result["errors"] == {"base": "cannot_connect"}


async def test_control_disabled(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{BASE}/info", json={**INFO, "control": False})
    aioclient_mock.post(f"{BASE}/pair", status=403, json={"error": "Control from other apps is turned off"})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: HOST, CONF_PORT: 47474})
    assert result["step_id"] == "pair"
    assert result["errors"] == {"base": "control_disabled"}


async def test_wrong_code_then_right(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    mock_tv(aioclient_mock, confirm_status=401)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: HOST, CONF_PORT: 47474})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "000000"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"code": "invalid_code"}

    aioclient_mock.clear_requests()
    mock_tv(aioclient_mock)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "123456"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    # The same pairing continues: no new code was requested.
    assert not any(str(call[1]).endswith("/pair") for call in aioclient_mock.mock_calls)


async def test_expired_code_restarts_pairing(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    mock_tv(aioclient_mock, confirm_status=410)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: HOST, CONF_PORT: 47474})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "123456"})
    assert result["errors"] == {"base": "pairing_restarted"}
    assert sum(str(call[1]).endswith("/pair") for call in aioclient_mock.mock_calls) == 2


async def test_zeroconf_flow(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    mock_tv(aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=DISCOVERY
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zeroconf_confirm"
    assert result["description_placeholders"] == {"name": "Woonkamer TV", "host": HOST}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "pair"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "123456"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == DEVICE_ID


async def test_zeroconf_updates_host(hass: HomeAssistant, mock_entry: MockConfigEntry) -> None:
    moved = ZeroconfServiceInfo(
        ip_address=ip_address("192.0.2.99"),
        ip_addresses=[ip_address("192.0.2.99")],
        hostname=DISCOVERY.hostname,
        name=DISCOVERY.name,
        port=47474,
        type=DISCOVERY.type,
        properties=DISCOVERY.properties,
    )
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_ZEROCONF}, data=moved)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_entry.data[CONF_HOST] == "192.0.2.99"


async def test_reauth(
    hass: HomeAssistant, mock_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{BASE}/status", json=STATUS)
    aioclient_mock.post(f"{BASE}/pair", status=202, json={"expiresIn": 120})
    aioclient_mock.post(f"{BASE}/pair/confirm", json={**PAIRED, "token": "new-token"})

    result = await mock_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "pair"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "123456"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_entry.data[CONF_TOKEN] == "new-token"


async def test_reauth_wrong_device(
    hass: HomeAssistant, mock_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(f"{BASE}/pair", status=202, json={"expiresIn": 120})
    aioclient_mock.post(f"{BASE}/pair/confirm", json={**PAIRED, "id": "someone-else"})
    result = await mock_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "123456"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"
    assert mock_entry.data[CONF_TOKEN] == TOKEN
