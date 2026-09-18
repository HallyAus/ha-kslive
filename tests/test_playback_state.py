"""Test media ownership and startup/rebuffering timelines."""

from conftest import load_module

playback_state = load_module("playback_state")
URL = "http://ha.test:8123/api/kslive/audio/session.mp3"


def test_sonos_radio_wrapper_preserves_exact_session_ownership() -> None:
    assert playback_state.owns_media_url(URL, URL)
    assert playback_state.owns_media_url(URL, f"x-rincon-mp3radio://{URL}")
    assert not playback_state.owns_media_url(URL, URL + "different")
    assert not playback_state.owns_media_url(URL, "spotify:track")
    assert not playback_state.owns_media_url(URL, None)


def test_previous_source_does_not_establish_new_session() -> None:
    session = playback_state.OutputSession(URL, deadline=130)
    assert session.observe("playing", "spotify:old", 100) == 30
    assert session.observe("paused", "spotify:old", 105) == 25
    assert session.observe("buffering", URL, 110) == 20
    assert not session.established
    assert session.observe("playing", URL, 115) is None
    assert session.established


def test_new_source_releases_even_when_transport_remains_playing() -> None:
    session = playback_state.OutputSession(URL, deadline=130)
    assert session.observe("playing", URL, 101) is None
    assert session.observe("playing", "spotify:new", 102) == 0
    assert session.released
    assert session.observe("playing", URL, 103) == 0


def test_rebuffering_has_a_bounded_grace_that_state_events_do_not_extend() -> None:
    session = playback_state.OutputSession(URL, deadline=130)
    assert session.observe("playing", URL, 101) is None
    assert session.observe("buffering", URL, 200) == 30
    assert session.observe("buffering", URL, 225) == 5
    assert session.observe("buffering", URL, 235) == 0


def test_transient_missing_metadata_and_idle_can_recover_before_cleanup() -> None:
    session = playback_state.OutputSession(URL, deadline=130)
    assert session.observe("playing", URL, 101) is None
    assert session.observe("idle", None, 105) == 5
    assert session.observe("playing", URL, 108) is None
    assert not session.released
