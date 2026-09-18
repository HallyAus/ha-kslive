"""Pure output-name selection for stable KSLive source options."""

from __future__ import annotations

from collections.abc import Iterable


def first_output_name(candidates: Iterable[object], entity_id: str) -> str:
    """Return the first non-empty display name, falling back to the entity ID."""
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return entity_id
