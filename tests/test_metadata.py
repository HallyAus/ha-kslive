"""Validate HACS and Home Assistant metadata."""

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_manifest() -> None:
    manifest = json.loads(
        (ROOT / "custom_components" / "kslive" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["domain"] == "kslive"
    assert manifest["config_flow"] is True
    assert manifest["version"] == "0.1.1"


def test_hacs_metadata() -> None:
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert hacs["name"] == "KSLive"
