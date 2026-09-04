"""Staging: ``git add`` the taxonomy file (or an arbitrary path) after a save."""

from __future__ import annotations

from pathlib import Path

from . import _subprocess
from ._state import _ManagerState


class _StagingMixin(_ManagerState):
    """Stage files for the next commit."""

    def stage_file(self) -> None:
        """git add the taxonomy file (called after every save, non-blocking)."""
        repo = self._repo()
        if not repo:
            return
        _subprocess._git("add", str(self.taxonomy_path), cwd=repo)

    def stage_path(self, path: Path) -> None:
        """git add an arbitrary file in the same repository."""
        repo = self._repo()
        if not repo:
            return
        _subprocess._git("add", str(path), cwd=repo)

    def has_staged_changes(self) -> bool:
        repo = self._repo()
        if not repo:
            return False
        r = _subprocess._git("diff", "--cached", "--name-only", cwd=repo)
        return bool(r.returncode == 0 and r.stdout.strip())
