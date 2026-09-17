"""Pure data model and validation for KSLive equalizer settings."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Final

DEFAULT_BASS: Final = 4.0
DEFAULT_TREBLE: Final = -2.0
DEFAULT_LOUDNESS: Final = True
DEFAULT_ENABLED: Final = True


@dataclass(slots=True)
class EqualizerSettings:
    """Saved KSLive preset values."""

    bass: float = DEFAULT_BASS
    treble: float = DEFAULT_TREBLE
    loudness: bool = DEFAULT_LOUDNESS
    enabled: bool = DEFAULT_ENABLED


def settings_from_mapping(stored: dict[str, Any]) -> EqualizerSettings:
    """Validate saved data and fall back safely for malformed values."""
    return EqualizerSettings(
        bass=bounded_number(stored.get("bass"), DEFAULT_BASS),
        treble=bounded_number(stored.get("treble"), DEFAULT_TREBLE),
        loudness=boolean(stored.get("loudness"), DEFAULT_LOUDNESS),
        enabled=boolean(stored.get("enabled"), DEFAULT_ENABLED),
    )


def bounded_number(value: Any, default: float) -> float:
    """Coerce an EQ value and constrain it to the Sonos-supported range."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(-10.0, min(10.0, number))


def boolean(value: Any, default: bool) -> bool:
    """Accept only real booleans so corrupted storage fails to a safe default."""
    return value if isinstance(value, bool) else default
