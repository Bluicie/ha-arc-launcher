"""Config flow: find the TV (zeroconf or host), then pair with the code shown on the TV."""

from __future__ import annotations

from collections.abc import Mapping
from ipaddress import ip_address
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .api import ArcLauncherApi, ArcLauncherAuthError, ArcLauncherConnectionError, ArcLauncherError
from .const import CLIENT_NAME, DEFAULT_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)

CONF_CODE = "code"


def _valid_host(host: str) -> bool:
    """The launcher only answers Hosts that are an IP address or a .local name."""
    try:
        ip_address(host)
    except ValueError:
        return host.lower().rstrip(".").endswith(".local")
    return True


class ArcLauncherConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._host = ""
        self._port = DEFAULT_PORT
        self._name = ""
        self._pairing = False

    def _api(self, token: str | None = None) -> ArcLauncherApi:
        return ArcLauncherApi(async_get_clientsession(self.hass), self._host, self._port, token)

    async def _async_fetch_info(self) -> dict[str, Any]:
        info = await self._api().info()
        if info.get("app") != "arc-launcher" or not info.get("id"):
            raise ArcLauncherError("Not an Arc Launcher")
        self._name = info.get("name") or self._host
        return info

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._host = user_input[CONF_HOST].strip()
            self._port = user_input[CONF_PORT]
            if not _valid_host(self._host):
                errors[CONF_HOST] = "invalid_host"
            else:
                try:
                    info = await self._async_fetch_info()
                except ArcLauncherConnectionError:
                    errors["base"] = "cannot_connect"
                except ArcLauncherError:
                    errors["base"] = "not_arc_launcher"
                else:
                    await self.async_set_unique_id(info["id"])
                    self._abort_if_unique_id_configured(updates={CONF_HOST: self._host, CONF_PORT: self._port})
                    return await self.async_step_pair()

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_HOST): str,
                        vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(int, vol.Range(1, 65535)),
                    }
                ),
                user_input,
            ),
            errors=errors,
        )

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> ConfigFlowResult:
        device_id = discovery_info.properties.get("id")
        if not device_id:
            return self.async_abort(reason="not_arc_launcher")
        if discovery_info.ip_address.version != 4:
            return self.async_abort(reason="not_ipv4_address")
        self._host = str(discovery_info.ip_address)
        self._port = discovery_info.port or DEFAULT_PORT
        await self.async_set_unique_id(device_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: self._host, CONF_PORT: self._port})
        self._name = discovery_info.name.removesuffix(f".{discovery_info.type}")
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return await self.async_step_pair()
        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders={"name": self._name, "host": self._host},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        self._host = entry_data[CONF_HOST]
        self._port = entry_data.get(CONF_PORT, DEFAULT_PORT)
        self._name = self._get_reauth_entry().title
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return await self.async_step_pair()
        return self.async_show_form(step_id="reauth_confirm", description_placeholders={"name": self._name})

    async def _async_start_pairing(self) -> str | None:
        """Ask the TV to show a code; returns an error key when it won't."""
        try:
            await self._api().pair(CLIENT_NAME)
        except ArcLauncherConnectionError:
            return "cannot_connect"
        except ArcLauncherAuthError:
            return "control_disabled"
        except ArcLauncherError as err:
            if err.status == 409:
                return "pairing_busy"
            if err.status == 429:
                return "pairing_blocked"
            _LOGGER.warning("Pairing with %s failed: %s", self._host, err)
            return "unknown"
        self._pairing = True
        return None

    async def async_step_pair(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show a code on the TV and let the user type it in."""
        errors: dict[str, str] = {}
        if user_input is None or not self._pairing:
            # First visit, or the previous attempt to start pairing failed: (re)start it.
            if error := await self._async_start_pairing():
                errors["base"] = error
        else:
            code = "".join(user_input[CONF_CODE].split())
            try:
                result = await self._api().confirm_pair(code)
            except ArcLauncherConnectionError:
                errors["base"] = "cannot_connect"
            except ArcLauncherAuthError as err:
                if err.status == 401:
                    errors[CONF_CODE] = "invalid_code"
                else:
                    errors["base"] = "control_disabled"
                    self._pairing = False
            except ArcLauncherError as err:
                self._pairing = False
                if err.status == 410:
                    # The code expired (2 minutes) or was used up by wrong guesses: show a new one.
                    errors["base"] = await self._async_start_pairing() or "pairing_restarted"
                else:
                    _LOGGER.warning("Pairing with %s failed: %s", self._host, err)
                    errors["base"] = "unknown"
            else:
                return await self._async_finish(result)

        return self.async_show_form(
            step_id="pair",
            data_schema=vol.Schema({vol.Required(CONF_CODE): str}),
            description_placeholders={"name": self._name},
            errors=errors,
        )

    async def _async_finish(self, result: dict[str, Any]) -> ConfigFlowResult:
        await self.async_set_unique_id(result["id"])
        data = {CONF_HOST: self._host, CONF_PORT: self._port, CONF_TOKEN: result["token"]}
        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch(reason="wrong_device")
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data_updates=data)
        self._abort_if_unique_id_configured(updates=data)
        return self.async_create_entry(title=result.get("name") or self._name, data=data)
