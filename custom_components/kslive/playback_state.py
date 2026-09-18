"""Pure helpers for KSLive output start-up and cleanup timing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from urllib.parse import unquote

ACTIVE_OUTPUT_STATES: Final = frozenset({"playing", "paused"})
INACTIVE_CLEANUP_DELAY: Final = 5.0
PLAYBACK_START_GRACE: Final = 30.0


def owns_media_url(expected: str, actual: object) -> bool:
    """Match the exact URL, including Sonos's radio URI wrapper."""
    if not isinstance(actual, str) or not actual:
        return False
    return unquote(actual.removeprefix("x-rincon-mp3radio://")) == unquote(expected)


@dataclass
class OutputSession:
    """Ownership and bounded startup/rebuffer timing for one output."""

    media_url: str
    deadline: float
    seen_media: bool = False
    established: bool = False
    released: bool = False

    def observe(self, state: str, media_id: object, now: float) -> float | None:
        """Return a cleanup delay; zero means another source owns this output."""
        if self.released:
            return 0.0
        matches = owns_media_url(self.media_url, media_id)
        if matches:
            self.seen_media = True
        elif media_id and self.seen_media:
            self.released = True
            return 0.0
        if matches and state in ACTIVE_OUTPUT_STATES:
            self.established = True
            self.deadline = 0.0
            return None
        if not self.established:
            return max(0.0, self.deadline - now)
        if state == "buffering":
            if not self.deadline:
                self.deadline = now + PLAYBACK_START_GRACE
            return max(0.0, self.deadline - now)
        return INACTIVE_CLEANUP_DELAY
