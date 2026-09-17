"""Output selector for KSLive playback."""

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

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


class KSLiveOutputSelect(KSLiveEntity, SelectEntity, RestoreEntity):
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

    async def async_added_to_hass(self) -> None:
        """Restore the user's last valid speaker selection after a restart."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in self.options:
            self.coordinator.select_source(last_state.state)
            self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Select an output without starting playback."""
        self.coordinator.select_source(option)
