"""Fetch/pull-behind checks: session-start sync with the remote.

``fetch_remote`` is safe to call from a background thread (silent, swallows
``KeyboardInterrupt``); ``check_and_pull``/``pre_edit_check`` are the
interactive "you're behind, pull?" prompts, called at different points in the
TUI/CLI session lifecycle (see module docstring in ``__init__.py``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from . import _console, _subprocess
from ._state import _ManagerState

_LIT_ORIGIN: Final = "origin"
_LIT_REMOTE_URL: Final = "remote_url"
_LIT_REV_PARSE: Final = "rev-parse"


class _SyncMixin(_ManagerState):
    """Remote fetch/pull-behind checks."""

    def fetch_remote(self) -> None:
        """Fetch from remote. Safe to call from a background thread."""
        repo = self._repo()
        if not repo or not self._cfg.get(_LIT_REMOTE_URL):
            return
        try:
            _subprocess._git("fetch", "--quiet", _LIT_ORIGIN, cwd=repo)
        except KeyboardInterrupt:
            return

    def check_and_pull(self) -> str | None:
        """Check if behind remote and offer to pull. Does NOT fetch — call fetch_remote() first."""
        if not self.is_configured():
            return None
        repo = self._repo()
        if not repo:
            return None
        if not self._cfg.get(_LIT_REMOTE_URL):
            return None

        try:
            return self._check_and_pull_inner(repo)
        except KeyboardInterrupt:
            return None

    def _check_and_pull_inner(self, repo: Path) -> str | None:
        main = self._cfg.get("main_branch", "main")
        behind_r = _subprocess._git("rev-list", "--count", f"HEAD..origin/{main}", cwd=repo)
        if behind_r.returncode != 0:
            return None
        try:
            behind = int(behind_r.stdout.strip())
        except ValueError:
            return None

        if behind == 0:
            return None

        from rich.prompt import Confirm

        _console.console.print(
            f"\n[yellow]⚠  {self.taxonomy_path.name} is "
            f"{behind} commit{'s' if behind > 1 else ''} behind the remote.[/yellow]"
        )
        if not Confirm.ask("Pull latest changes?", default=True):
            return None

        before_r = _subprocess._git(_LIT_REV_PARSE, "HEAD", cwd=repo)
        before = before_r.stdout.strip() if before_r.returncode == 0 else None

        pull_r = _subprocess._git("pull", "--ff-only", _LIT_ORIGIN, main, cwd=repo)
        if pull_r.returncode != 0:
            _console.err.print(f"[red]Pull failed:[/red] {pull_r.stderr.strip()}")
            return None

        _console.console.print("[green]✓ Updated.[/green]")

        if before:
            diff_r = _subprocess._git(
                "diff", before, "HEAD", "--", str(self.taxonomy_path), cwd=repo
            )
            if diff_r.returncode == 0 and diff_r.stdout:
                return diff_r.stdout

        return None

    def pre_edit_check(self) -> str | None:
        """Fetch; pull if behind; return diff text (or None) for display."""
        if not self.is_configured():
            return None
        repo = self._repo()
        if not repo:
            return None
        if not self._cfg.get(_LIT_REMOTE_URL):
            return None

        try:
            return self._pre_edit_check_inner(repo)
        except KeyboardInterrupt:
            return None

    def _pre_edit_check_inner(self, repo: Path) -> str | None:
        # Silent fetch
        _subprocess._git("fetch", "--quiet", _LIT_ORIGIN, cwd=repo)

        main = self._cfg.get("main_branch", "main")
        behind_r = _subprocess._git("rev-list", "--count", f"HEAD..origin/{main}", cwd=repo)
        if behind_r.returncode != 0:
            return None
        try:
            behind = int(behind_r.stdout.strip())
        except ValueError:
            return None

        if behind == 0:
            return None

        from rich.prompt import Confirm

        _console.console.print(
            f"\n[yellow]⚠  {self.taxonomy_path.name} is "
            f"{behind} commit{'s' if behind > 1 else ''} behind the remote.[/yellow]"
        )
        if not Confirm.ask("Pull latest changes?", default=True):
            return None

        # Record HEAD before pull so we can diff
        before_r = _subprocess._git(_LIT_REV_PARSE, "HEAD", cwd=repo)
        before = before_r.stdout.strip() if before_r.returncode == 0 else None

        pull_r = _subprocess._git("pull", "--ff-only", _LIT_ORIGIN, main, cwd=repo)
        if pull_r.returncode != 0:
            _console.err.print(f"[red]Pull failed:[/red] {pull_r.stderr.strip()}")
            return None

        _console.console.print("[green]✓ Updated.[/green]")

        if before:
            diff_r = _subprocess._git(
                "diff", before, "HEAD", "--", str(self.taxonomy_path), cwd=repo
            )
            if diff_r.returncode == 0 and diff_r.stdout:
                return diff_r.stdout

        return None

    def record_head(self) -> None:
        """Snapshot current HEAD for "what changed since last open" diffing."""
        repo = self._repo()
        if not repo:
            return
        r = _subprocess._git(_LIT_REV_PARSE, "HEAD", cwd=repo)
        if r.returncode == 0:
            self._cfg["last_commit"] = r.stdout.strip()
            self._persist()
