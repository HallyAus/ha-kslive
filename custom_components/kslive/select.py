"""Output selector for KSLive playback."""

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import KSLiveCoordinator
from .entity import KSLiveEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the KSLive output selector."""
    coordinator: KSLiveCoordinator = hass.data["kslive"][entry.entry_id]
    async_add_entities([KSLiveOutputSelect(coordinator)])


class KSLiveOutputSelect(KSLiveEntity, SelectEntity):
    """Choose the speaker or configured multi-speaker output."""

    _attr_name = "Output"
    _attr_icon = "mdi:speaker-multiple"

    def __init__(self, coordinator: KSLiveCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_output"

    @property
    def options(self) -> list[str]:
        return list(self.coordinator.output_sources)

    @property
    def current_option(self) -> str | None:
        return self.coordinator.selected_source

    async def async_select_option(self, option: str) -> None:
        """Select an output without starting playback."""
        await self.coordinator.async_select_source(option)
