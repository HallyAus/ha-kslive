"""Buttons for KSLive."""

from homeassistant.components.button import ButtonEntity
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
    """Set up KSLive buttons."""
    coordinator: KSLiveCoordinator = hass.data["kslive"][entry.entry_id]
    async_add_entities([KSLivePlayButton(coordinator), KSLiveRefreshButton(coordinator)])


class KSLivePlayButton(KSLiveEntity, ButtonEntity):
    """Play the current show or newest recording."""

    _attr_name = "Play audio"
    _attr_icon = "mdi:play-circle"

    def __init__(self, coordinator: KSLiveCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_play_audio"

    async def async_press(self) -> None:
        await self.coordinator.async_play()


class KSLiveRefreshButton(KSLiveEntity, ButtonEntity):
    """Refresh the audio catalog immediately."""

    _attr_name = "Refresh"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: KSLiveCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_refresh"

    async def async_press(self) -> None:
        await self.coordinator.async_refresh_catalog()
