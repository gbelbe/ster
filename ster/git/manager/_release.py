"""Release tagging: git-tag-driven semver versioning for published taxonomies.

Runs in the linked repo when one is configured, else falls back to the
taxonomy file's own directory — releases work even for a taxonomy that never
went through interactive ``setup()``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from . import _subprocess
from ._state import _ManagerState

_LIT_ORIGIN: Final = "origin"


class _ReleaseMixin(_ManagerState):
    """Tag/commit/push helpers for the stable-release flow."""

    def _release_cwd(self) -> Path:
        """Directory to run release git commands in: the linked repo, else the file's dir."""
        return self._repo() or self.taxonomy_path.parent

    def list_tags(self) -> list[str]:
        """All git tags in the repository (empty list when not in a repo)."""
        r = _subprocess._git("tag", "--list", cwd=self._release_cwd())
        if r.returncode != 0:
            return []
        return [line.strip() for line in r.stdout.splitlines() if line.strip()]

    def commit_paths(self, paths: list[Path], message: str) -> str | None:
        """Stage *paths* and commit them with *message*; return the new sha or None."""
        cwd = self._release_cwd()
        for p in paths:
            _subprocess._git("add", str(p), cwd=cwd)
        if _subprocess._git("commit", "-m", message, cwd=cwd).returncode != 0:
            return None
        head = _subprocess._git("rev-parse", "HEAD", cwd=cwd)
        return head.stdout.strip() if head.returncode == 0 else None

    def create_tag(self, tag: str, message: str) -> bool:
        """Create an annotated git tag at HEAD; return True on success."""
        return (
            _subprocess._git("tag", "-a", tag, "-m", message, cwd=self._release_cwd()).returncode
            == 0
        )

    def push_release(self, tag: str) -> bool:
        """Push the release commit to the main branch and *tag* to origin.

        Pushes the current HEAD to the repo's main branch (``main_branch`` config,
        default ``main``) rather than whatever branch is checked out, so releases
        always land on main.  No-op (returns False) when no remote is configured.
        """
        cwd = self._release_cwd()
        if _subprocess._git("remote", "get-url", _LIT_ORIGIN, cwd=cwd).returncode != 0:
            return False
        main = self._cfg.get("main_branch", "main")
        branch_ok = _subprocess._git("push", _LIT_ORIGIN, f"HEAD:{main}", cwd=cwd).returncode == 0
        tag_ok = _subprocess._git("push", _LIT_ORIGIN, tag, cwd=cwd).returncode == 0
        return branch_ok and tag_ok
