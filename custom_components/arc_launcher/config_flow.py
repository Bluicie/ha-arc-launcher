"""Config flow: find the TV (zeroconf or host), then pair with the code shown on the TV."""

from __future__ import annotations

from collections.abc import Mapping
from ipaddress import ip_address
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from homeassistant.util import slugify

from .api import ArcLauncherApi, ArcLauncherAuthError, ArcLauncherConnectionError, ArcLauncherError
from .const import (
    CLIENT_NAME,
    CONF_QUICK_ACTIONS,
    DEFAULT_PORT,
    DOMAIN,
    MAX_LABEL_LENGTH,
    MAX_QUICK_ACTIONS,
    QUICK_ACTION_ICONS,
)

_LOGGER = logging.getLogger(__name__)

CONF_CODE = "code"
CONF_LABEL = "label"
CONF_ICON = "icon"
CONF_TARGET = "target"
CONF_ACTION = "action"
CONF_ACTIONS = "actions"


def _valid_host(host: str) -> bool:
    """The launcher only answers Hosts that are an IP address or a .local name."""
    try:
        ip_address(host)
    except ValueError:
        return host.lower().rstrip(".").endswith(".local")
    return True


class ArcLauncherConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ArcLauncherOptionsFlow:
        return ArcLauncherOptionsFlow()

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


class ArcLauncherOptionsFlow(OptionsFlow):
    """Manage the quick-action buttons on the TV's status bar."""

    def __init__(self) -> None:
        self._actions: list[dict[str, Any]] | None = None
        self._editing: int | None = None

    @property
    def actions(self) -> list[dict[str, Any]]:
        if self._actions is None:
            self._actions = [dict(a) for a in self.config_entry.options.get(CONF_QUICK_ACTIONS, [])]
        return self._actions

    def _choices(self) -> list[SelectOptionDict]:
        return [SelectOptionDict(value=a["id"], label=a["label"]) for a in self.actions]

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        menu = ["add"] if len(self.actions) < MAX_QUICK_ACTIONS else []
        if self.actions:
            menu += ["edit", "remove"]
        menu.append("save")
        return self.async_show_menu(
            step_id="init",
            menu_options=menu,
            description_placeholders={
                "actions": ", ".join(a["label"] for a in self.actions) or "-",
                "max": str(MAX_QUICK_ACTIONS),
            },
        )

    async def async_step_add(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._editing = None
        return await self.async_step_action()

    async def async_step_edit(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._editing = next(i for i, a in enumerate(self.actions) if a["id"] == user_input[CONF_ACTION])
            return await self.async_step_action()
        return self.async_show_form(
            step_id="edit",
            data_schema=vol.Schema({vol.Required(CONF_ACTION): SelectSelector(SelectSelectorConfig(options=self._choices()))}),
        )

    async def async_step_remove(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._actions = [a for a in self.actions if a["id"] not in user_input[CONF_ACTIONS]]
            return await self.async_step_init()
        return self.async_show_form(
            step_id="remove",
            data_schema=vol.Schema(
                {vol.Required(CONF_ACTIONS): SelectSelector(SelectSelectorConfig(options=self._choices(), multiple=True))}
            ),
        )

    async def async_step_action(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Label, icon and what the button runs (a scene, script or automation, or only the event)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            label = user_input[CONF_LABEL].strip()
            if not 1 <= len(label) <= MAX_LABEL_LENGTH:
                errors[CONF_LABEL] = "invalid_label"
            else:
                action = {
                    "label": label,
                    "icon": user_input[CONF_ICON],
                    "target": user_input.get(CONF_TARGET) or None,
                }
                if self._editing is None:
                    self.actions.append({"id": self._new_id(label), **action})
                else:
                    self.actions[self._editing].update(action)
                return await self.async_step_init()

        current = self.actions[self._editing] if self._editing is not None else {}
        schema = vol.Schema(
            {
                vol.Required(CONF_LABEL): TextSelector(),
                vol.Required(CONF_ICON, default="gesture-tap"): SelectSelector(
                    SelectSelectorConfig(
                        options=QUICK_ACTION_ICONS, mode=SelectSelectorMode.DROPDOWN, translation_key="icon"
                    )
                ),
                vol.Optional(CONF_TARGET): EntitySelector(
                    EntitySelectorConfig(domain=["scene", "script", "automation"])
                ),
            }
        )
        suggested = user_input or {k: v for k, v in current.items() if k != "id" and v is not None}
        return self.async_show_form(
            step_id="action",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
        )

    async def async_step_save(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_create_entry(data={**self.config_entry.options, CONF_QUICK_ACTIONS: self.actions})

    def _new_id(self, label: str) -> str:
        """A stable id from the label: 1-40 chars of [a-z0-9_], unique on this TV."""
        base = slugify(label)[:36] or "action"
        taken = {a["id"] for a in self.actions}
        new_id, n = base, 2
        while new_id in taken:
            new_id, n = f"{base}_{n}", n + 1
        return new_id
