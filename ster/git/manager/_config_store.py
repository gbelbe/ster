"""Per-file git settings, persisted to ``~/.config/ster/git_repos.json``.

Keyed by the absolute path of the taxonomy file, so one user can work on many
different taxonomy files across different repos simultaneously with no
cross-contamination. GitHub tokens are NOT persisted here by default; see
``_push.py`` for the opt-in, plaintext-warned save path.

Reached by other submodules through ``_config_store.<name>`` (module-qualified,
not a bare imported name) for the same reason as ``_subprocess.py``: it keeps
``patch("ster.git.manager._config_store.CONFIG_FILE", ...)`` (and friends)
effective regardless of which mixin's method triggers the read/write.
"""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "ster"
CONFIG_FILE = CONFIG_DIR / "git_repos.json"


def _load_global_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {}


def _save_global_config(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2))
