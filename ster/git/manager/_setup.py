"""Interactive first-time setup: detect/init/clone/link a repo and ask the
branch strategy (direct push vs. feature-branch + PR).
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from . import _console, _subprocess
from ._state import _ManagerState

_LIT_GIT_DIR: Final = "--git-dir"
_LIT_SHOW_CURRENT: Final = "--show-current"
_LIT_VERIFY: Final = "--verify"
_LIT_CHOOSE: Final = "Choose"
_LIT_BOLD: Final = "[/bold]"
_LIT_BRANCH: Final = "branch"
_LIT_CHECKOUT: Final = "checkout"
_LIT_MAIN_BRANCH: Final = "main_branch"
_LIT_ORIGIN: Final = "origin"
_LIT_ORIGIN_PREFIX: Final = "origin/"
_LIT_REMOTE: Final = "remote"
_LIT_REMOTE_URL: Final = "remote_url"
_LIT_REV_PARSE: Final = "rev-parse"


class _SetupMixin(_ManagerState):
    """``setup()`` and everything it delegates to."""

    def setup(self) -> bool:
        """Interactive first-time setup.  Returns True if git is now active."""
        if not _subprocess._git_available():
            _console.console.print("[dim]git not found — skipping version control.[/dim]")
            return False

        # Already opted out?
        if not self.is_enabled():
            return False

        # Auto-detect an existing repo silently
        repo_root = self._find_repo_root()
        if repo_root:
            self._link_existing_repo(repo_root)
            _console.console.print(
                f"[green]✓[/green] Linked to git repo at [bold]{repo_root}{_LIT_BOLD}"
            )
            if not self._cfg.get("branch_strategy"):
                self._ask_branch_strategy()
            return True

        # Ask the user if they want git at all
        from ster import ask

        _console.console.print()
        want = ask.confirm(
            "[bold]Set up Git version control for this taxonomy?[/bold]",
            default=True,
        )
        if not want:
            self._cfg["git_enabled"] = False
            self._persist()
            return False

        # Present options
        from ster import ask

        _console.console.print(
            "\n[bold]Git setup:[/bold]\n"
            "  [cyan]1[/cyan]  Initialise a new local repository here\n"
            "  [cyan]2[/cyan]  Clone from a remote URL (GitHub / GitLab / …)\n"
            "  [cyan]3[/cyan]  Link to an existing local repository"
        )
        choice = ask.text(_LIT_CHOOSE, choices=["1", "2", "3"], default="1")

        ok = False
        if choice == "1":
            ok = self._init_new_repo()
        elif choice == "2":
            ok = self._clone_repo()
        elif choice == "3":
            ok = self._link_repo_interactive()

        if ok:
            self._ask_branch_strategy()
        return ok

    # ── private: setup helpers ────────────────────────────────────────────────

    def _init_new_repo(self) -> bool:
        """Initialise a brand-new local repository, optionally wiring a remote."""
        from ster import ask

        repo_dir = self.taxonomy_path.parent
        r = _subprocess._git("init", cwd=repo_dir)
        if r.returncode != 0:
            _console.err.print(f"[red]git init failed:[/red] {r.stderr.strip()}")
            return False

        gi = repo_dir / ".gitignore"
        if not gi.exists():
            gi.write_text("# ster temp files\n.ster_session\n")

        _subprocess._git("add", str(gi), cwd=repo_dir)
        _subprocess._git("commit", "-m", "chore: initialise repository", cwd=repo_dir)

        if ask.confirm("Add a remote (GitHub / GitLab / …)?", default=True):
            while True:
                url = ask.text("Remote URL (https or ssh)")
                if not url:
                    break
                # Verify connectivity before storing
                _console.console.print(f"[dim]Connecting to {url}…[/dim]")
                ls_r = _subprocess._git("ls-remote", "--exit-code", url, cwd=repo_dir)
                if ls_r.returncode not in (0, 2):
                    _console.err.print(
                        f"[red]Cannot reach {url}[/red]\n[dim]{ls_r.stderr.strip()}[/dim]"
                    )
                    if not ask.confirm("Try a different URL?", default=True):
                        break
                    continue
                _subprocess._git(_LIT_REMOTE, "add", _LIT_ORIGIN, url, cwd=repo_dir)
                _subprocess._git(
                    "push", "-u", _LIT_ORIGIN, self._local_branch(repo_dir), cwd=repo_dir
                )
                self._cfg[_LIT_REMOTE_URL] = url
                _console.console.print(f"[green]✓ Remote set to {url}[/green]")
                break

        self._link_existing_repo(repo_dir)
        _console.console.print(
            f"[green]✓[/green] Repository initialised at [bold]{repo_dir}{_LIT_BOLD}"
        )
        return True

    def _clone_repo(self) -> bool:
        """Link the taxonomy directory to a remote repository.

        Works whether the directory is empty (true clone) or already contains
        files (init-in-place + fetch).  Loops until connectivity and sync are
        verified, or the user cancels.
        """
        from ster import ask

        repo_dir = self.taxonomy_path.parent

        while True:
            url = ask.text("Repository URL (GitHub https or SSH)")
            if not url:
                return False

            if self._clone_repo_attempt(repo_dir, url):
                return True

            if not ask.confirm("Retry?", default=True):
                return False

    def _clone_repo_attempt(self, repo_dir: Path, url: str) -> bool:
        """Perform one connection, clone/init, and verification attempt."""
        _console.console.print(f"[dim]Connecting to {url}…[/dim]")
        ls_result = _subprocess._git("ls-remote", "--exit-code", "--heads", url, cwd=repo_dir)
        if ls_result.returncode not in (0, 2):
            _console.err.print(
                f"[red]Cannot reach {url}[/red]\n"
                f"[dim]{ls_result.stderr.strip()}[/dim]\n"
                "[dim]Check the URL, your network, and credentials "
                "(SSH key authorised? HTTPS token valid?)[/dim]"
            )
            return False

        _console.console.print("[green]✓ Remote reachable.[/green]")
        existing = [file for file in repo_dir.iterdir() if not file.name.startswith(".")]
        already_git = _subprocess._git(_LIT_REV_PARSE, _LIT_GIT_DIR, cwd=repo_dir).returncode == 0
        if not existing and not already_git:
            result = _subprocess._git("clone", url, ".", cwd=repo_dir)
            if result.returncode != 0:
                _console.err.print(f"[red]Clone failed:[/red] {result.stderr.strip()}")
                return False
            _console.console.print(f"[green]✓ Cloned to {repo_dir}[/green]")
        elif not self._init_inplace_with_remote(repo_dir, url):
            return False

        verify = _subprocess._git(_LIT_REMOTE, "get-url", _LIT_ORIGIN, cwd=repo_dir)
        if verify.returncode != 0:
            _console.err.print("[red]Verification failed — remote not set correctly.[/red]")
            return False
        self._link_existing_repo(repo_dir)
        self._cfg[_LIT_REMOTE_URL] = url
        self._persist()
        _console.console.print(
            f"[bold green]✓ Git configured.[/bold green]  Remote: {verify.stdout.strip()}"
        )
        return True

    def _init_inplace_with_remote(self, repo_dir: Path, url: str) -> bool:
        """Set up git in a non-empty directory and link it to *url*."""
        from ster import ask

        # Init if needed
        already_git = _subprocess._git(_LIT_REV_PARSE, _LIT_GIT_DIR, cwd=repo_dir).returncode == 0
        if not already_git:
            _subprocess._git("init", cwd=repo_dir)
            gi = repo_dir / ".gitignore"
            if not gi.exists():
                gi.write_text("# ster temp files\n.ster_session\n")

        # Add / update remote
        existing = self._get_remote_url(repo_dir)
        if existing and existing != url:
            _console.console.print(f"[yellow]Replacing existing remote ({existing})[/yellow]")
            _subprocess._git(_LIT_REMOTE, "set-url", _LIT_ORIGIN, url, cwd=repo_dir)
        elif not existing:
            _subprocess._git(_LIT_REMOTE, "add", _LIT_ORIGIN, url, cwd=repo_dir)

        # Fetch to get remote refs
        fetch_r = _subprocess._git("fetch", _LIT_ORIGIN, cwd=repo_dir)
        if fetch_r.returncode != 0:
            _console.err.print(f"[red]Fetch failed:[/red] {fetch_r.stderr.strip()}")
            _subprocess._git(_LIT_REMOTE, "remove", _LIT_ORIGIN, cwd=repo_dir)
            return False

        main = self._detect_remote_default_branch(repo_dir)
        self._cfg[_LIT_MAIN_BRANCH] = main

        has_remote_branch = (
            _subprocess._git(_LIT_REV_PARSE, f"{_LIT_ORIGIN_PREFIX}{main}", cwd=repo_dir).returncode
            == 0
        )

        if has_remote_branch:
            # ── remote has content: ask how to sync ───────────────────────
            _console.console.print(
                f"\n[yellow]Remote already has content on branch '{main}'.[/yellow]\n"
                "How do you want to sync?\n"
                "  [cyan]1[/cyan]  Pull from remote into this directory\n"
                f"  [cyan]2[/cyan]  Push local files to remote "
                f"(overwrites '{main}' on the remote)\n"
                "  [cyan]3[/cyan]  Skip for now (track manually later)"
            )
            choice = ask.text(_LIT_CHOOSE, choices=["1", "2", "3"], default="1")

            if choice == "1":
                return self._pull_remote_into_dir(repo_dir, main)
            elif choice == "2":
                return self._push_local_to_remote(repo_dir, main, force=True)
            # choice == 3: no sync, just leave tracking set up
            self._ensure_on_branch(repo_dir, main)
        else:
            # ── remote is empty: push local content ───────────────────────
            return self._push_local_to_remote(repo_dir, main, force=False)

        return True

    def _pull_remote_into_dir(self, repo_dir: Path, main: str) -> bool:
        """Check out the remote branch, merging with any local uncommitted files."""

        local_exists = (
            _subprocess._git(_LIT_REV_PARSE, _LIT_VERIFY, main, cwd=repo_dir).returncode == 0
        )

        if not local_exists:
            r = _subprocess._git(
                _LIT_CHECKOUT, "-b", main, "--track", f"{_LIT_ORIGIN_PREFIX}{main}", cwd=repo_dir
            )
        else:
            _subprocess._git(_LIT_CHECKOUT, main, cwd=repo_dir)
            r = _subprocess._git("pull", "--ff-only", _LIT_ORIGIN, main, cwd=repo_dir)
            if r.returncode != 0:
                r = _subprocess._git(
                    "pull",
                    "--allow-unrelated-histories",
                    "-m",
                    "chore: merge remote history",
                    _LIT_ORIGIN,
                    main,
                    cwd=repo_dir,
                )

        if r.returncode != 0:
            _console.err.print(f"[red]Pull failed:[/red] {r.stderr.strip()}")
            return False

        _console.console.print(f"[green]✓ Pulled '{main}' from remote.[/green]")
        return True

    def _push_local_to_remote(self, repo_dir: Path, main: str, force: bool) -> bool:
        """Stage all local files, commit if needed, and push to remote."""
        from ster import ask

        self._ensure_on_branch(repo_dir, main)
        _subprocess._git("add", ".", cwd=repo_dir)

        # Commit only if there is something staged
        status_r = _subprocess._git("diff", "--cached", "--name-only", cwd=repo_dir)
        if status_r.stdout.strip():
            c = _subprocess._git("commit", "-m", "chore: add existing taxonomy", cwd=repo_dir)
            if c.returncode != 0 and "nothing to commit" not in c.stdout + c.stderr:
                _console.err.print(f"[red]Commit failed:[/red] {c.stderr.strip()}")
                return False

        push_args = ["push", "-u", _LIT_ORIGIN, main]
        if force:
            push_args.insert(1, "--force")
        push_r = _subprocess._git(*push_args, cwd=repo_dir)

        if push_r.returncode != 0:
            _console.err.print(f"[red]Push failed:[/red] {push_r.stderr.strip()}")
            if not force and ask.confirm("Force push? (overwrites remote history)", default=False):
                push_r = _subprocess._git("push", "--force", "-u", _LIT_ORIGIN, main, cwd=repo_dir)
                if push_r.returncode != 0:
                    _console.err.print(f"[red]Force push failed:[/red] {push_r.stderr.strip()}")
                    return False
            else:
                return False

        _console.console.print(f"[green]✓ Pushed to '{main}'.[/green]")
        return True

    @staticmethod
    def _ensure_on_branch(repo_dir: Path, branch: str) -> None:
        """Make sure the repo is on *branch*, creating it if necessary."""
        current = _subprocess._git(_LIT_BRANCH, _LIT_SHOW_CURRENT, cwd=repo_dir).stdout.strip()
        if current == branch:
            return
        if _subprocess._git(_LIT_REV_PARSE, _LIT_VERIFY, branch, cwd=repo_dir).returncode == 0:
            _subprocess._git(_LIT_CHECKOUT, branch, cwd=repo_dir)
        else:
            _subprocess._git(_LIT_CHECKOUT, "-b", branch, cwd=repo_dir)

    def _detect_remote_default_branch(self, repo_dir: Path) -> str:
        """Return the remote's HEAD branch name, falling back to 'main'."""
        show_r = _subprocess._git(_LIT_REMOTE, "show", _LIT_ORIGIN, cwd=repo_dir)
        for line in show_r.stdout.splitlines():
            if "HEAD branch:" in line:
                return line.split(":")[-1].strip()
        for branch in ("main", "master"):
            if (
                _subprocess._git(
                    _LIT_REV_PARSE, f"{_LIT_ORIGIN_PREFIX}{branch}", cwd=repo_dir
                ).returncode
                == 0
            ):
                return branch
        return "main"

    @staticmethod
    def _local_branch(repo_dir: Path) -> str:
        r = _subprocess._git(_LIT_BRANCH, _LIT_SHOW_CURRENT, cwd=repo_dir)
        return r.stdout.strip() or "main"

    def _link_repo_interactive(self) -> bool:
        """Link to an existing local repository with retry."""
        from ster import ask

        while True:
            default = str(self.taxonomy_path.parent)
            path_str = ask.text("Path to git repository", default=default)
            p = Path(path_str).expanduser().resolve()
            if _subprocess._git(_LIT_REV_PARSE, _LIT_GIT_DIR, cwd=p).returncode == 0:
                self._link_existing_repo(p)
                _console.console.print(f"[green]✓[/green] Linked to [bold]{p}{_LIT_BOLD}")
                return True
            _console.err.print(f"[red]Not a git repository: {p}[/red]")
            if not ask.confirm("Try a different path?", default=True):
                return False

    def _link_existing_repo(self, repo_root: Path) -> None:
        self._cfg["repo_path"] = str(repo_root)
        url = self._get_remote_url(repo_root)
        if url:
            self._cfg[_LIT_REMOTE_URL] = url
        self._detect_main_branch(repo_root)
        self._persist()

    def _ask_branch_strategy(self) -> None:
        from ster import ask

        _console.console.print(
            "\n[bold]Default push strategy:[/bold]\n"
            "  [cyan]1[/cyan]  Direct push to main  (single user, no review)\n"
            "  [cyan]2[/cyan]  Feature branch + Pull Request  (team workflow)"
        )
        choice = ask.text(_LIT_CHOOSE, choices=["1", "2"], default="1")
        self._cfg["branch_strategy"] = "direct" if choice == "1" else "pr"
        self._persist()

    # ── private: git utility ──────────────────────────────────────────────────

    def _find_repo_root(self) -> Path | None:
        r = _subprocess._git(_LIT_REV_PARSE, "--show-toplevel", cwd=self.taxonomy_path.parent)
        return Path(r.stdout.strip()) if r.returncode == 0 else None

    def _get_remote_url(self, repo: Path) -> str | None:
        r = _subprocess._git(_LIT_REMOTE, "get-url", _LIT_ORIGIN, cwd=repo)
        return r.stdout.strip() if r.returncode == 0 else None

    def _detect_main_branch(self, repo: Path) -> None:
        for branch in ("main", "master"):
            if _subprocess._git(_LIT_REV_PARSE, _LIT_VERIFY, branch, cwd=repo).returncode == 0:
                self._cfg[_LIT_MAIN_BRANCH] = branch
                return
        r = _subprocess._git(_LIT_BRANCH, _LIT_SHOW_CURRENT, cwd=repo)
        self._cfg[_LIT_MAIN_BRANCH] = r.stdout.strip() or "main"
