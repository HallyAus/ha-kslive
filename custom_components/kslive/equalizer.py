"""KSLive-only equalizer preset management for supported speakers."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass
from typing import Any, Final

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .equalizer_settings import EqualizerSettings, bounded_number, settings_from_mapping

_LOGGER = logging.getLogger(__name__)

_STORAGE_VERSION: Final = 1


@dataclass(slots=True)
class _EqualizerControls:
    bass: str | None = None
    treble: str | None = None
    loudness: str | None = None


@dataclass(slots=True)
class _EqualizerSnapshot:
    controls: _EqualizerControls
    bass: float | None
    treble: float | None
    loudness: bool | None


class KSLiveEqualizer:
    """Apply a saved preset while KSLive owns a supported output."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self.settings = EqualizerSettings()
        self._store = Store[dict[str, Any]](
            hass, _STORAGE_VERSION, f"kslive.{entry_id}.equalizer"
        )
        self._snapshots: dict[str, _EqualizerSnapshot] = {}
        self._lock = asyncio.Lock()

    async def async_load(self) -> None:
        """Load the durable preset without storing speaker state."""
        stored = await self._store.async_load()
        if not isinstance(stored, dict):
            return
        self.settings = settings_from_mapping(stored)

    async def async_set(self, key: str, value: float | bool) -> None:
        """Update and save one preset value."""
        if key in {"bass", "treble"}:
            setattr(self.settings, key, bounded_number(value, 0.0))
        elif key in {"loudness", "enabled"}:
            setattr(self.settings, key, bool(value))
        else:
            raise ValueError(f"Unknown KSLive equalizer setting: {key}")
        await self._store.async_save(asdict(self.settings))

    async def async_apply(self, targets: tuple[str, ...]) -> None:
        """Capture current speaker settings and apply the KSLive preset."""
        if not self.settings.enabled:
            return
        async with self._lock:
            for target in targets:
                controls = self._controls_for_target(target)
                if controls is None:
                    continue
                if target not in self._snapshots:
                    self._snapshots[target] = self._snapshot(controls)
                try:
                    await self._async_set_controls(self._snapshots[target].controls)
                except HomeAssistantError:
                    _LOGGER.warning(
                        "Unable to apply the KSLive equalizer preset to %s",
                        target,
                    )

    async def async_restore(self, targets: tuple[str, ...]) -> None:
        """Restore settings captured before KSLive used each output."""
        async with self._lock:
            for target in targets:
                snapshot = self._snapshots.get(target)
                if snapshot is None:
                    continue
                try:
                    await self._async_restore_snapshot(snapshot)
                except HomeAssistantError:
                    _LOGGER.warning(
                        "Unable to restore the pre-KSLive equalizer settings for %s",
                        target,
                    )
                else:
                    self._snapshots.pop(target, None)

    async def async_restore_all(self) -> None:
        """Restore every speaker still carrying the KSLive preset."""
        await self.async_restore(tuple(self._snapshots))

    def _controls_for_target(self, target: str) -> _EqualizerControls | None:
        registry = er.async_get(self.hass)
        target_entry = registry.async_get(target)
        if (
            target_entry is None
            or target_entry.platform != "sonos"
            or target_entry.device_id is None
        ):
            return None

        controls = _EqualizerControls()
        for entry in er.async_entries_for_device(
            registry, target_entry.device_id, include_disabled_entities=False
        ):
            if entry.platform != "sonos":
                continue
            if entry.translation_key == "bass" and entry.entity_id.startswith("number."):
                controls.bass = entry.entity_id
            elif (
                entry.translation_key == "treble"
                and entry.entity_id.startswith("number.")
            ):
                controls.treble = entry.entity_id
            elif (
                entry.translation_key == "loudness"
                and entry.entity_id.startswith("switch.")
            ):
                controls.loudness = entry.entity_id

        return controls if any(asdict(controls).values()) else None

    def _snapshot(self, controls: _EqualizerControls) -> _EqualizerSnapshot:
        bass = self._number_state(controls.bass)
        treble = self._number_state(controls.treble)
        loudness = self._switch_state(controls.loudness)
        # Never change a control whose original value cannot be restored.
        return _EqualizerSnapshot(
            controls=_EqualizerControls(
                bass=controls.bass if bass is not None else None,
                treble=controls.treble if treble is not None else None,
                loudness=controls.loudness if loudness is not None else None,
            ),
            bass=bass,
            treble=treble,
            loudness=loudness,
        )

    async def _async_set_controls(self, controls: _EqualizerControls) -> None:
        if controls.bass is not None:
            await self._async_number_set(controls.bass, self.settings.bass)
        if controls.treble is not None:
            await self._async_number_set(controls.treble, self.settings.treble)
        if controls.loudness is not None:
            await self._async_switch_set(controls.loudness, self.settings.loudness)

    async def _async_restore_snapshot(self, snapshot: _EqualizerSnapshot) -> None:
        if snapshot.controls.bass is not None and snapshot.bass is not None:
            await self._async_number_set(snapshot.controls.bass, snapshot.bass)
        if snapshot.controls.treble is not None and snapshot.treble is not None:
            await self._async_number_set(snapshot.controls.treble, snapshot.treble)
        if snapshot.controls.loudness is not None and snapshot.loudness is not None:
            await self._async_switch_set(snapshot.controls.loudness, snapshot.loudness)

    async def _async_number_set(self, entity_id: str, value: float) -> None:
        await self.hass.services.async_call(
            "number",
            "set_value",
            {ATTR_ENTITY_ID: entity_id, "value": value},
            blocking=True,
        )

    async def _async_switch_set(self, entity_id: str, enabled: bool) -> None:
        await self.hass.services.async_call(
            "switch",
            "turn_on" if enabled else "turn_off",
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

    def _number_state(self, entity_id: str | None) -> float | None:
        state = self.hass.states.get(entity_id) if entity_id else None
        try:
            return float(state.state) if state is not None else None
        except ValueError:
            return None

    def _switch_state(self, entity_id: str | None) -> bool | None:
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None or state.state not in {"on", "off"}:
            return None
        return state.state == "on"
