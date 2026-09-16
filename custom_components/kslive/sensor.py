"""Sensors for KSLive."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
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
    """Set up the KSLive status sensor."""
    coordinator: KSLiveCoordinator = hass.data["kslive"][entry.entry_id]
    async_add_entities([KSLiveStatusSensor(coordinator)])


class KSLiveStatusSensor(KSLiveEntity, SensorEntity):
    """Describe the current KSLive audio availability."""

    _attr_name = "Audio status"
    _attr_icon = "mdi:radio"

    def __init__(self, coordinator: KSLiveCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_audio_status"

    @property
    def native_value(self) -> str:
        return self.coordinator.data.state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        current = data.current
        upcoming = data.upcoming
        latest = data.latest_recording
        return {
            "current_title": current.title if current else None,
            "current_content_id": current.content_id if current else None,
            "next_title": upcoming.title if upcoming else None,
            "next_content_id": upcoming.content_id if upcoming else None,
            "next_start": (
                upcoming.launch_date.isoformat()
                if upcoming and upcoming.launch_date
                else None
            ),
            "latest_recording_title": latest.title if latest else None,
            "latest_recording_content_id": latest.content_id if latest else None,
            "catalog_count": len(data.items),
        }
