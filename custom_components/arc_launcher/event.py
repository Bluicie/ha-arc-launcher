"""Event entity: fires when a quick-action button on the TV is pressed."""

from __future__ import annotations

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ArcLauncherConfigEntry, ArcLauncherCoordinator
from .entity import ArcLauncherEntity
from .quick_actions import configured_actions, signal_quick_action

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ArcLauncherConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    actions = configured_actions(entry)
    if actions:
        async_add_entities([QuickActionEvent(entry.runtime_data, [action["id"] for action in actions])])


class QuickActionEvent(ArcLauncherEntity, EventEntity):
    """The event type is the id of the pressed button; options changes reload the entry."""

    _attr_device_class = EventDeviceClass.BUTTON

    def __init__(self, coordinator: ArcLauncherCoordinator, event_types: list[str]) -> None:
        super().__init__(coordinator, "quick_action")
        self._attr_event_types = event_types

    @property
    def available(self) -> bool:
        # Presses come from the TV, not from polling.
        return True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_quick_action(self.coordinator.config_entry.entry_id), self._pressed
            )
        )

    @callback
    def _pressed(self, action: str) -> None:
        labels = {a["id"]: a["label"] for a in configured_actions(self.coordinator.config_entry)}
        self._trigger_event(action, {"label": labels.get(action)})
        self.async_write_ha_state()
