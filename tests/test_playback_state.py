"""Test KSLive playback start-up and cleanup decisions."""

from conftest import load_module

playback_state = load_module("playback_state")


def test_playing_and_paused_outputs_do_not_schedule_cleanup() -> None:
    assert playback_state.inactive_cleanup_delay({"playing"}, 0) is None
    assert playback_state.inactive_cleanup_delay({"paused"}, 0) is None


def test_idle_and_buffering_outputs_keep_the_startup_grace() -> None:
    assert playback_state.inactive_cleanup_delay({"idle"}, 24.5) == 24.5
    assert playback_state.inactive_cleanup_delay({"buffering"}, 12) == 12


def test_inactive_output_cleans_up_after_grace_expires() -> None:
    assert playback_state.inactive_cleanup_delay({"idle"}, 0) == 5
    assert playback_state.inactive_cleanup_delay({"buffering"}, 0) == 5
