"""Per-instance config accessors: the state every other mixin reads/writes.

Each ``GitManager`` is bound to one taxonomy file path; all config for that
file lives in ``self._cfg`` and is persisted to the global JSON via
``_config_store``.
"""

from __future__ import annotations

from pathlib import Path

from . import _config_store
from ._state import _ManagerState


class _ConfigMixin(_ManagerState):
    """Instance construction, opt-out/configured checks, and the repo-path
    resolver every other mixin calls to find the linked repository."""

    def __init__(self, taxonomy_path: Path) -> None:
        self.taxonomy_path = taxonomy_path.resolve()
        self._global_cfg = _config_store._load_global_config()
        self._cfg: dict = self._global_cfg.get(str(self.taxonomy_path), {})

    # ── public API ────────────────────────────────────────────────────────────

    def is_enabled(self) -> bool:
        """Returns False only when the user explicitly opted out for this file."""
        return self._cfg.get("git_enabled", True)

    def is_configured(self) -> bool:
        return bool(self._cfg.get("repo_path"))

    # ── private: git utility ──────────────────────────────────────────────────

    def _repo(self) -> Path | None:
        rp = self._cfg.get("repo_path")
        if rp:
            p = Path(rp)
            return p if p.exists() else None
        return None

    # ── private: config persistence ──────────────────────────────────────────

    def _persist(self) -> None:
        self._global_cfg[str(self.taxonomy_path)] = self._cfg
        _config_store._save_global_config(self._global_cfg)
