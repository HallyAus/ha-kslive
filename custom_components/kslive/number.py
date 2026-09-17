"""Equalizer preset number entities for KSLive."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import KSLiveCoordinator
from .entity import KSLiveEntity


@dataclass(frozen=True, kw_only=True)
class _EqualizerNumberDescription:
    key: str
    name: str
    icon: str


DESCRIPTIONS = (
    _EqualizerNumberDescription(key="bass", name="Bass preset", icon="mdi:music-clef-bass"),
    _EqualizerNumberDescription(
        key="treble", name="Treble preset", icon="mdi:music-clef-treble"
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up KSLive equalizer preset numbers."""
    coordinator: KSLiveCoordinator = hass.data["kslive"][entry.entry_id]
    async_add_entities(
        [KSLiveEqualizerNumber(coordinator, description) for description in DESCRIPTIONS]
    )


class KSLiveEqualizerNumber(KSLiveEntity, NumberEntity):
    """A durable KSLive equalizer preset value."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = -10
    _attr_native_max_value = 10
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self,
        coordinator: KSLiveCoordinator,
        description: _EqualizerNumberDescription,
    ) -> None:
        super().__init__(coordinator)
        self._key = description.key
        self._attr_name = description.name
        self._attr_icon = description.icon
        self._attr_unique_id = f"{coordinator.entry.entry_id}_eq_{description.key}"

    @property
    def native_value(self) -> float:
        """Return the saved KSLive preset value."""
        return float(getattr(self.coordinator.equalizer.settings, self._key))

    async def async_set_native_value(self, value: float) -> None:
        """Save a value and apply it to active KSLive Sonos outputs."""
        await self.coordinator.async_set_equalizer(self._key, value)
