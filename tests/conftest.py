"""Load pure KSLive modules without requiring Home Assistant locally."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "custom_components" / "kslive"


def load_module(name: str):
    """Load an integration module while bypassing the Home Assistant package entry point."""
    if "kslive" not in sys.modules:
        package = types.ModuleType("kslive")
        package.__path__ = [str(PACKAGE)]
        sys.modules["kslive"] = package
    full_name = f"kslive.{name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    path = PACKAGE / f"{name}.py"
    spec = importlib.util.spec_from_file_location(full_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module

