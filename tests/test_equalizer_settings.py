"""Test KSLive equalizer defaults and storage validation."""

from conftest import load_module

settings_module = load_module("equalizer_settings")


def test_warm_default_preset() -> None:
    settings = settings_module.EqualizerSettings()

    assert settings.bass == 4
    assert settings.treble == -2
    assert settings.loudness is True
    assert settings.enabled is True


def test_saved_values_are_validated_and_bounded() -> None:
    settings = settings_module.settings_from_mapping(
        {"bass": 99, "treble": -99, "loudness": "yes", "enabled": False}
    )

    assert settings.bass == 10
    assert settings.treble == -10
    assert settings.loudness is True
    assert settings.enabled is False


def test_malformed_values_fall_back_to_defaults() -> None:
    settings = settings_module.settings_from_mapping(
        {"bass": "not-a-number", "treble": "nan"}
    )

    assert settings.bass == 4
    assert settings.treble == -2
