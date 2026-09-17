"""Test audio relay routing and FFmpeg command construction."""

from conftest import load_module

streaming = load_module("streaming")


def test_only_sonos_needs_audio_relay() -> None:
    assert streaming.needs_audio_relay("sonos") is True
    assert streaming.needs_audio_relay("cast") is False
    assert streaming.needs_audio_relay(None) is False


def test_ffmpeg_command_outputs_audio_only_mp3() -> None:
    source_url = "https://example.invalid/master.m3u8?secret=not-logged"
    arguments = streaming.ffmpeg_audio_arguments(source_url)

    assert arguments[arguments.index("-i") + 1] == source_url
    assert arguments[arguments.index("-map") + 1] == "0:a:0"
    assert "-vn" in arguments
    assert arguments[arguments.index("-c:a") + 1] == "libmp3lame"
    assert arguments[arguments.index("-f") + 1] == "mp3"
    assert arguments[-1] == "pipe:1"
