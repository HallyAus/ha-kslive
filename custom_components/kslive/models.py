"""Data models and catalog parsing for KSLive."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


def parse_datetime(value: Any) -> datetime | None:
    """Parse an API timestamp into an aware datetime."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


@dataclass(frozen=True, slots=True)
class KSLiveContent:
    """A KSLive catalog item."""

    content_id: int
    title: str
    content_type: str
    launch_date: datetime | None
    permalink: str | None
    live_active: bool
    live_status: str | None
    description: str | None
    image_url: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KSLiveContent | None:
        """Build content from an API object."""
        try:
            content_id = int(data["id"])
        except (KeyError, TypeError, ValueError):
            return None

        preview = data.get("preview")
        image_url = preview if isinstance(preview, str) else None
        if isinstance(preview, dict):
            for key in ("image_url", "url", "medium", "large"):
                if isinstance(preview.get(key), str):
                    image_url = preview[key]
                    break

        return cls(
            content_id=content_id,
            title=str(data.get("title") or f"KSLive {content_id}"),
            content_type=str(data.get("content_type") or "unknown"),
            launch_date=parse_datetime(data.get("launch_date")),
            permalink=data.get("permalink") if isinstance(data.get("permalink"), str) else None,
            live_active=bool(data.get("live_active")),
            live_status=(
                str(data["live_status"]).lower() if data.get("live_status") is not None else None
            ),
            description=(
                data.get("description") if isinstance(data.get("description"), str) else None
            ),
            image_url=image_url,
        )

    @property
    def is_live(self) -> bool:
        """Return whether this content is currently live."""
        return self.live_active or self.live_status in {"active", "live", "started", "streaming"}


@dataclass(frozen=True, slots=True)
class KSLiveCatalog:
    """A normalized KSLive audio catalog."""

    items: tuple[KSLiveContent, ...]
    current: KSLiveContent | None
    upcoming: KSLiveContent | None
    latest_recording: KSLiveContent | None
    recordings: tuple[KSLiveContent, ...]

    @property
    def state(self) -> str:
        """Return a compact broadcast state."""
        if self.current is not None:
            return "live"
        if self.upcoming is not None:
            return "scheduled"
        if self.latest_recording is not None:
            return "recorded"
        return "off_air"

    @property
    def playable(self) -> KSLiveContent | None:
        """Prefer the live show, otherwise the newest recording."""
        return self.current or self.latest_recording

    @property
    def playable_items(self) -> tuple[KSLiveContent, ...]:
        """Return the live show followed by recordings in queue order."""
        ordered = ((self.current,) if self.current is not None else ()) + self.recordings
        seen: set[int] = set()
        return tuple(
            item
            for item in ordered
            if item.content_id not in seen and not seen.add(item.content_id)
        )


def parse_catalog(payload: dict[str, Any], *, now: datetime | None = None) -> KSLiveCatalog:
    """Normalize the KSLive content search response."""
    now = now or datetime.now(UTC)
    raw_items = payload.get("contents", [])
    items = tuple(
        parsed
        for raw in raw_items
        if isinstance(raw, dict)
        if (parsed := KSLiveContent.from_dict(raw)) is not None
    )

    current = next((item for item in items if item.is_live), None)
    future = sorted(
        (
            item
            for item in items
            if item.launch_date is not None
            and item.launch_date > now
            and item.content_type == "live_event"
        ),
        key=lambda item: item.launch_date or now,
    )
    recordings = sorted(
        (
            item
            for item in items
            if item.content_type in {"video", "audio"}
            and (item.launch_date is None or item.launch_date <= now)
        ),
        key=lambda item: item.launch_date or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    return KSLiveCatalog(
        items=items,
        current=current,
        upcoming=future[0] if future else None,
        latest_recording=recordings[0] if recordings else None,
        recordings=tuple(recordings),
    )


def catalog_cache(catalog: KSLiveCatalog) -> dict[str, Any]:
    """Persist display metadata only, never raw API responses or stream URLs."""
    return {"contents": [
        {
            "id": item.content_id,
            "title": item.title,
            "content_type": item.content_type,
            "launch_date": item.launch_date.isoformat() if item.launch_date else None,
            "permalink": item.permalink,
            "live_active": item.live_active,
            "live_status": item.live_status,
            "description": item.description,
            "preview": item.image_url,
        }
        for item in catalog.items
    ]}


def find_stream_url(value: Any) -> str | None:
    """Find an HLS or audio URL in a nested API response."""
    if isinstance(value, str):
        lowered = value.lower()
        if value.startswith(("https://", "http://")) and (
            ".m3u8" in lowered
            or lowered.endswith((".mp3", ".m4a", ".aac"))
            or "stream.mux.com" in lowered
        ):
            return value
        return None
    if isinstance(value, dict):
        preferred = (
            "stream_url",
            "playback_url",
            "hls_url",
            "hls",
            "url",
            "src",
            "source",
        )
        for key in preferred:
            if key in value and (found := find_stream_url(value[key])):
                return found
        for nested in value.values():
            if found := find_stream_url(nested):
                return found
    if isinstance(value, list):
        for nested in value:
            if found := find_stream_url(nested):
                return found
    return None
