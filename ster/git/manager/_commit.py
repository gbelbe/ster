"""Commit flow: staged-changes gate, semanticlint quality gate, commit message
prompt, and the post-commit push-strategy choice (direct vs. feature+PR).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from . import _console, _subprocess
from ._state import _ManagerState

_LIT_BRANCH_STRATEGY: Final = "branch_strategy"
_LIT_DIRECT: Final = "direct"


if TYPE_CHECKING:  # types only — semanticlint is an optional plugin dependency
    from semanticlint.checks.base import Severity, Violation

    _LintState = tuple[list[Violation], Severity]


class _CommitMixin(_ManagerState):
    """Interactive commit/push flow, plus the non-interactive initial commit."""

    def commit_new_taxonomy(self, commit_msg: str) -> None:
        """Stage the taxonomy file, commit with *commit_msg*, and push if remote is set.

        Intended for the initial commit when a new taxonomy is created or first
        added to version control.  Prints a one-line summary on success.
        """
        repo = self._repo()
        if not repo:
            return

        _subprocess._git("add", str(self.taxonomy_path), cwd=repo)

        r = _subprocess._git("commit", "-m", commit_msg, cwd=repo)
        if r.returncode != 0:
            if "nothing to commit" in (r.stdout + r.stderr).lower():
                _console.console.print("[dim]File already committed — nothing to add.[/dim]")
            else:
                _console.err.print(f"[red]Commit failed:[/red] {r.stderr.strip()}")
            return

        first_line = commit_msg.splitlines()[0]
        _console.console.print(f"[green]✓ Committed:[/green] {first_line}")

        if not self._cfg.get("remote_url"):
            _console.console.print("[dim]No remote configured — changes committed locally.[/dim]")
            return

        main = self._cfg.get("main_branch", "main")
        self._push_direct(repo, main)

    def _run_commit_lint(self) -> _LintState | None:
        """Run semanticlint over the file when the plugin is active, returning
        ``(violations, fail_on)``. Uses the plugin's global ``quality.json`` — the same
        config the TUI live view uses — so the commit gate matches what you saw editing.
        ``None`` when the plugin is disabled / not installed (gate skipped)."""
        from ster.plugins import semanticlint

        if not semanticlint.is_active():
            return None
        from ...plugins.semanticlint import config
        from ...plugins.semanticlint.runner import lint_files

        return lint_files(
            [self.taxonomy_path], config.build_check_config()
        ), config.fail_on_severity()

    def _lint_blocks_commit(self, lint: _LintState | None) -> bool:
        """Prompt when the lint introduces blocking issues; True to *cancel* the commit.
        A no-op returning False when *lint* is None (plugin disabled)."""
        from rich.prompt import Confirm

        from ...plugins.semanticlint.runner import display_violations, has_blocking_violations

        if lint is None or not has_blocking_violations(*lint):
            return False
        display_violations(*lint)
        if Confirm.ask("Issues found. Commit anyway?", default=False, console=_console.console):
            return False
        _console.console.print("[dim]Commit cancelled.[/dim]")
        return True

    def _display_lint(self, lint: _LintState | None, *, only_when_clean: bool = False) -> None:
        """Print the lint results (after commit/push); no-op when *lint* is None. With
        *only_when_clean*, print only when there are no blocking issues (already shown)."""
        from ...plugins.semanticlint.runner import display_violations, has_blocking_violations

        if lint is None or (only_when_clean and has_blocking_violations(*lint)):
            return
        display_violations(*lint)

    def commit_and_push(self) -> None:
        """Interactive post-edit flow: commit message → commit → push/PR."""
        if not self.is_configured():
            return
        if not self.has_staged_changes():
            _console.console.print("[dim]No staged changes — nothing to commit.[/dim]")
            return

        from rich.prompt import Prompt

        repo = self._repo()
        if repo is None:
            return
        main = self._cfg.get("main_branch", "main")
        strat = self._cfg.get(_LIT_BRANCH_STRATEGY, _LIT_DIRECT)

        # Semanticlint quality gate (only when the plugin is active). ``lint`` is None
        # when disabled, so every use below is skipped and ster behaves as standard.
        lint = self._run_commit_lint()
        if self._lint_blocks_commit(lint):
            return

        # ── commit message ────────────────────────────────────────────────────
        default_msg = f"Update {self.taxonomy_path.name}"
        _console.console.print()
        try:
            msg = Prompt.ask(
                "[bold]Commit message[/bold]",
                default=default_msg,
                console=_console.console,
            )
        except (KeyboardInterrupt, EOFError):
            _console.console.print("\n[dim]Commit cancelled.[/dim]")
            return

        commit_r = _subprocess._git("commit", "-m", msg, cwd=repo)
        if commit_r.returncode != 0:
            _console.err.print(f"[red]Commit failed:[/red] {commit_r.stderr.strip()}")
            return
        _console.console.print(f"[green]✓ Committed:[/green] {msg}")
        self._refresh_dev_artifacts()

        if not self._cfg.get("remote_url"):
            self._display_lint(lint)
            _console.console.print("[dim]No remote configured — changes committed locally.[/dim]")
            return

        # ── push strategy ─────────────────────────────────────────────────────
        _console.console.print(
            "\n[bold]Push options:[/bold]\n"
            f"  [cyan]1[/cyan]  Push directly to [bold]{main}[/bold]\n"
            "  [cyan]2[/cyan]  Push to a feature branch and open a Pull Request"
        )
        default_choice = "1" if strat == _LIT_DIRECT else "2"
        try:
            choice = Prompt.ask(
                "Choose", choices=["1", "2"], default=default_choice, console=_console.console
            )
        except (KeyboardInterrupt, EOFError):
            _console.console.print("\n[dim]Push cancelled.[/dim]")
            return

        if choice == "1":
            self._push_direct(repo, main)
            self._cfg[_LIT_BRANCH_STRATEGY] = _LIT_DIRECT
            self._persist()
        else:
            self._push_pr(repo, main, msg)
            self._cfg[_LIT_BRANCH_STRATEGY] = "pr"
            self._persist()

        # Show lint results after push so they are the last thing visible.
        self._display_lint(lint, only_when_clean=True)

    def _refresh_dev_artifacts(self) -> None:
        """Best-effort: rebuild ontology/dev/ so it mirrors the just-committed file.

        Never raises — a failed rebuild must not break the commit/push flow.
        """
        from ...publish import regenerate_dev_artifacts

        try:
            paths = regenerate_dev_artifacts(self.taxonomy_path)
        except Exception as e:  # best-effort: dev refresh is non-critical
            _console.console.print(f"[dim]Could not refresh dev pages: {e}[/dim]")
            return
        if paths:
            _console.console.print(
                f"[green]✓[/green] [dim]Refreshed dev pages → {paths[0].parent}[/dim]"
            )
