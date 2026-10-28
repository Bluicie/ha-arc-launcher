"""Quick actions: buttons on the TV's status bar that call a Home Assistant webhook."""

from __future__ import annotations

from http import HTTPStatus
import json
import logging
from typing import Any

from aiohttp.web import Request, Response
import yarl

from homeassistant.components import webhook
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.util.network import is_ip_address

from .const import CONF_QUICK_ACTIONS, CONF_WEBHOOK_ID, DOMAIN, EVENT_QUICK_ACTION
from .coordinator import ArcLauncherConfigEntry

_LOGGER = logging.getLogger(__name__)


def configured_actions(entry: ArcLauncherConfigEntry) -> list[dict[str, Any]]:
    """The buttons from the options: [{id, label, icon, target}], target an entity id or None."""
    return list(entry.options.get(CONF_QUICK_ACTIONS, []))


def signal_quick_action(entry_id: str) -> str:
    return f"{DOMAIN}_{entry_id}_quick_action"


def webhook_url(hass: HomeAssistant, webhook_id: str) -> str | None:
    """Local URL the TV calls. The TV reaches Home Assistant by IP, so a plain-http host name is swapped for the IP."""
    try:
        base = yarl.URL(get_url(hass, allow_external=False, allow_cloud=False, prefer_external=False))
    except NoURLAvailableError:
        return None
    local_ip = hass.config.api.local_ip if hass.config.api else None
    if base.scheme == "http" and base.host and not is_ip_address(base.host) and local_ip:
        base = base.with_host(local_ip)
    return str(base.with_path(f"/api/webhook/{webhook_id}"))


def tv_payload(entry: ArcLauncherConfigEntry, url: str) -> list[dict[str, Any]]:
    """What PUT /quick-actions gets."""
    return [
        {"id": action["id"], "label": action["label"], "icon": action["icon"], "url": url}
        for action in configured_actions(entry)
    ]


def register_webhook(hass: HomeAssistant, entry: ArcLauncherConfigEntry) -> None:
    async def handle(hass: HomeAssistant, webhook_id: str, request: Request) -> Response:
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return _response(HTTPStatus.BAD_REQUEST, "Expected a JSON object")
        action = next((a for a in configured_actions(entry) if a["id"] == body.get("action")), None)
        if action is None:
            return _response(HTTPStatus.NOT_FOUND, "Unknown action")

        if target := action.get("target"):
            domain = target.split(".", 1)[0]
            service = "trigger" if domain == "automation" else "turn_on"
            try:
                await hass.services.async_call(domain, service, {ATTR_ENTITY_ID: target}, blocking=False)
            except HomeAssistantError as err:
                _LOGGER.warning("Quick action %s on %s failed: %s", action["id"], entry.title, err)
                return _response(HTTPStatus.INTERNAL_SERVER_ERROR, str(err))

        device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.unique_id)})
        hass.bus.async_fire(
            EVENT_QUICK_ACTION,
            {"device_id": device.id if device else None, "action": action["id"], "label": action["label"]},
        )
        async_dispatcher_send(hass, signal_quick_action(entry.entry_id), action["id"])
        return _response(HTTPStatus.OK, "OK")

    webhook.async_register(
        hass,
        DOMAIN,
        f"Arc Launcher {entry.title}",
        entry.data[CONF_WEBHOOK_ID],
        handle,
        local_only=True,
        allowed_methods=["POST"],
    )


def _response(status: HTTPStatus, message: str) -> Response:
    return Response(status=status, text=json.dumps({"message": message}), content_type="application/json")
