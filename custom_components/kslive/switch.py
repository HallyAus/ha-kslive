"""Equalizer preset switches for KSLive."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import KSLiveCoordinator
from .entity import KSLiveEntity


@dataclass(frozen=True, kw_only=True)
class _EqualizerSwitchDescription:
    key: str
    name: str
    icon: str


DESCRIPTIONS = (
    _EqualizerSwitchDescription(
        key="enabled", name="EQ preset", icon="mdi:tune-vertical"
    ),
    _EqualizerSwitchDescription(
        key="loudness", name="Loudness preset", icon="mdi:volume-high"
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up KSLive equalizer preset switches."""
    coordinator: KSLiveCoordinator = hass.data["kslive"][entry.entry_id]
    async_add_entities(
        [KSLiveEqualizerSwitch(coordinator, description) for description in DESCRIPTIONS]
    )


class KSLiveEqualizerSwitch(KSLiveEntity, SwitchEntity):
    """A durable KSLive equalizer preset toggle."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: KSLiveCoordinator,
        description: _EqualizerSwitchDescription,
    ) -> None:
        super().__init__(coordinator)
        self._key = description.key
        self._attr_name = description.name
        self._attr_icon = description.icon
        self._attr_unique_id = f"{coordinator.entry.entry_id}_eq_{description.key}"

    @property
    def is_on(self) -> bool:
        """Return the saved KSLive preset toggle."""
        return bool(getattr(self.coordinator.equalizer.settings, self._key))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable this preset option."""
        del kwargs
        await self.coordinator.async_set_equalizer(self._key, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable this preset option."""
        del kwargs
        await self.coordinator.async_set_equalizer(self._key, False)
