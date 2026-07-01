"""Global configuration for the semanticlint plugin (``~/.config/ster/quality.json``).

The user chose a single global config (rather than per-repo ``onto-ci.yml``): quality
thresholds + which severity fails, plus the plugin's UI feature toggles. ster's live
lint uses this; the git commit hook / CI keep reading the repo's ``onto-ci.yml``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # semanticlint is optional — imported lazily in build_check_config
    from semanticlint.checks.base import CheckConfig

# Threshold keys the QUA checks read, with semanticlint's own defaults.
DEFAULT_THRESHOLDS: dict = {
    "min_label_coverage": 1.0,
    "min_definition_coverage": 0.5,
    "min_class_label_coverage": 1.0,
    "min_property_label_coverage": 1.0,
    "languages": ["en"],
}

# The plugin's UI features, each independently toggleable (all on by default).
DEFAULT_FEATURES: dict = {"icons": True, "detail": True, "quality_block": True}

DEFAULT_FAIL_ON = "error"


def _config_path() -> Path:
    return Path.home() / ".config" / "ster" / "quality.json"


def load_config() -> dict:
    """The plugin config, filled with defaults for any missing key."""
    data: dict = {}
    path = _config_path()
    if path.exists():
        try:
            loaded = json.loads(path.read_text())
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            pass
    return {
        "fail_on": data.get("fail_on", DEFAULT_FAIL_ON),
        "quality": {**DEFAULT_THRESHOLDS, **(data.get("quality") or {})},
        "features": {**DEFAULT_FEATURES, **(data.get("features") or {})},
    }


def save_config(config: dict) -> None:
    """Persist the plugin config (best-effort), merged onto current values."""
    merged = {**load_config(), **config}
    path = _config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(merged, indent=2))
    except Exception:
        pass


def feature_enabled(name: str) -> bool:
    """Whether UI feature *name* (icons / detail / quality_block) is on."""
    return bool(load_config()["features"].get(name, DEFAULT_FEATURES.get(name, False)))


def set_feature(name: str, value: bool) -> None:
    features = {**load_config()["features"], name: bool(value)}
    save_config({"features": features})


def build_check_config() -> CheckConfig:
    """A semanticlint ``CheckConfig`` built from the global quality thresholds. Only
    call when semanticlint is installed (imports the library)."""
    from semanticlint.checks.base import CheckConfig

    return CheckConfig(quality=load_config()["quality"])
