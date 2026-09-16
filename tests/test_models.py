"""Tests for KSLive catalog parsing."""

from datetime import UTC, datetime

from conftest import load_module

models = load_module("models")
find_stream_url = models.find_stream_url
parse_catalog = models.parse_catalog


def test_parse_catalog_prioritizes_live_and_latest_recording() -> None:
    now = datetime(2026, 9, 16, 0, 0, tzinfo=UTC)
    catalog = parse_catalog(
        {
            "contents": [
                {
                    "id": 1,
                    "title": "Live audio",
                    "content_type": "live_event",
                    "live_active": True,
                    "live_status": "live",
                    "launch_date": "2026-09-16T06:00:00+10:00",
                },
                {
                    "id": 2,
                    "title": "Tomorrow",
                    "content_type": "live_event",
                    "live_status": "scheduled",
                    "launch_date": "2026-09-17T06:00:00+10:00",
                },
                {
                    "id": 3,
                    "title": "Recording",
                    "content_type": "video",
                    "launch_date": "2026-09-15T06:00:00+10:00",
                },
            ]
        },
        now=now,
    )
    assert catalog.state == "live"
    assert catalog.current and catalog.current.content_id == 1
    assert catalog.upcoming and catalog.upcoming.content_id == 2
    assert catalog.latest_recording and catalog.latest_recording.content_id == 3
    assert catalog.playable == catalog.current


def test_find_stream_url_recurses_without_accepting_web_pages() -> None:
    payload = {
        "unrelated": "https://kslive.com.au/programs/test",
        "playback": {"sources": [{"src": "https://stream.mux.com/example.m3u8?token=x"}]},
    }
    assert find_stream_url(payload) == "https://stream.mux.com/example.m3u8?token=x"


def test_find_stream_url_accepts_playlist_list() -> None:
    playlist = [{"content_id": 42, "hls": "https://stream.mux.com/audio.m3u8?token=x"}]
    assert find_stream_url(playlist) == "https://stream.mux.com/audio.m3u8?token=x"
