"""Test stable KSLive output names before media-player state is available."""

from conftest import load_module

output_names = load_module("output_names")


def test_state_name_wins_after_player_loads() -> None:
    assert (
        output_names.first_output_name(
            ("Garage", None, "Garage device", "Sonos", "Living Room"),
            "media_player.living_room",
        )
        == "Garage"
    )


def test_device_name_is_stable_before_player_state_loads() -> None:
    assert (
        output_names.first_output_name(
            (None, None, "Garage", "Sonos One", "Living Room"),
            "media_player.living_room",
        )
        == "Garage"
    )


def test_entity_id_is_only_the_final_fallback() -> None:
    assert (
        output_names.first_output_name(
            (None, "", None, None, None), "media_player.living_room"
        )
        == "media_player.living_room"
    )
