"""Select: which other Arc Launcher TV this TV follows."""

from __future__ import annotations

from urllib.parse import urlparse

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import ArcLauncherConfigEntry, ArcLauncherCoordinator
from .entity import ArcLauncherEntity

PARALLEL_UPDATES = 1

NOT_FOLLOWING = "none"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ArcLauncherConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([FollowSelect(entry.runtime_data, "follow")])


class FollowSelect(ArcLauncherEntity, SelectEntity):
    """Options are the other configured TVs that share their layout."""

    _attr_entity_category = EntityCategory.CONFIG

    @property
    def available(self) -> bool:
        return super().available and self.sync is not None

    def _sources(self) -> dict[str, ArcLauncherCoordinator]:
        sources: dict[str, ArcLauncherCoordinator] = {}
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.state is not ConfigEntryState.LOADED or entry.unique_id == self.coordinator.device_id:
                continue
            other: ArcLauncherCoordinator = entry.runtime_data
            if not other.data or not other.data.get("sharing"):
                continue
            name = other.data.get("name") or entry.title
            if name in sources or name == NOT_FOLLOWING:
                name = f"{name} ({other.api.host})"
            sources[name] = other
        return sources

    def _followed(self, sources: dict[str, ArcLauncherCoordinator]) -> str | None:
        sync = self.sync or {}
        url = sync.get("url")
        if not url:
            return NOT_FOLLOWING
        host = urlparse(url).hostname
        for name, other in sources.items():
            if host == other.api.host:
                return name
        # Following a TV that is not in Home Assistant (or not sharing right now).
        return sync.get("following") or url

    @property
    def options(self) -> list[str]:
        sources = self._sources()
        options = [NOT_FOLLOWING, *sources]
        followed = self._followed(sources)
        if followed not in options:
            options.append(followed)
        return options

    @property
    def current_option(self) -> str | None:
        return self._followed(self._sources())

    async def async_select_option(self, option: str) -> None:
        sources = self._sources()
        if option == NOT_FOLLOWING:
            await self._update_settings(follow=None)
            return
        if option == self._followed(sources):
            return
        other = sources.get(option)
        if other is None:
            raise HomeAssistantError(f"{option} is not an Arc Launcher TV that shares its layout")
        await self._update_settings(
            follow={
                "name": other.data.get("name") or other.config_entry.title,
                "url": other.api.backup_url,
                "id": other.device_id,
            }
        )
