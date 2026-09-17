"""Pure helpers for KSLive stream routing and transcoding."""

from __future__ import annotations

SONOS_PLATFORM = "sonos"


def needs_audio_relay(platform: str | None) -> bool:
    """Return whether a player needs the video-free KSLive relay."""
    return platform == SONOS_PLATFORM


def ffmpeg_audio_arguments(source_url: str) -> tuple[str, ...]:
    """Build FFmpeg arguments for a reconnectable MP3 radio stream."""
    return (
        "-hide_banner",
        "-nostdin",
        "-nostats",
        "-loglevel",
        "error",
        "-reconnect",
        "1",
        "-reconnect_streamed",
        "1",
        "-reconnect_delay_max",
        "5",
        "-i",
        source_url,
        "-map",
        "0:a:0",
        "-vn",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "192k",
        "-f",
        "mp3",
        "pipe:1",
    )
