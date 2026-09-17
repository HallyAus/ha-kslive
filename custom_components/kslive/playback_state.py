"""Pure helpers for KSLive output start-up and cleanup timing."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final, Literal

ACTIVE_OUTPUT_STATES: Final = frozenset({"playing", "paused"})
STARTING_OUTPUT_STATES: Final = frozenset({"buffering"})
INACTIVE_CLEANUP_DELAY: Final = 5.0
PLAYBACK_START_GRACE: Final = 30.0
PlayCommandAction = Literal["start", "resume", "ignore"]


def inactive_cleanup_delay(
    states: Iterable[str], startup_remaining: float
) -> float | None:
    """Return when cleanup should run, or None while playback is established."""
    state_set = set(states)
    if state_set & ACTIVE_OUTPUT_STATES:
        return None
    if startup_remaining > 0:
        return startup_remaining
    return INACTIVE_CLEANUP_DELAY


def play_command_action(
    states: Iterable[str],
    *,
    playback_active: bool,
    playback_starting: bool,
    same_targets: bool,
) -> PlayCommandAction:
    """Choose whether a Play command should start, resume or do nothing."""
    state_set = set(states)
    if not playback_active or not same_targets:
        return "start"
    if "paused" in state_set:
        return "resume"
    if playback_starting or state_set & {"playing", "buffering"}:
        return "ignore"
    return "start"
