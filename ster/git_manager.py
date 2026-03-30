"""Git integration for ster — version-control taxonomy files automatically.

Session lifecycle
─────────────────
  setup()          — first-time: detect/init/clone/link repo; ask branch strategy
  pre_edit_check() — fetch remote; pull if behind; show what changed
  stage_file()     — git add <taxonomy_file>  (called after every save)
  commit_and_push() — prompt for message; commit; push direct or via PR

Config
──────
  Per-file settings are stored in ~/.config/ster/git_repos.json, keyed by the
  absolute path of the taxonomy file.  This means one user can work on many
  different taxonomy files across different repos simultaneously with no
  cross-contamination.

  GitHub tokens are NOT persisted here.  We first try ``gh auth token``
  (GitHub CLI) and, for one-time use, prompt the user; saving is opt-in with a
  plaintext warning.
"""
from __future__ import annotations

import datetime
import json
import re
import subprocess
from pathlib import Path
from typing import Optional

from rich.console import Console

console = Console()
err     = Console(stderr=True)

# ── config ────────────────────────────────────────────────────────────────────

CONFIG_DIR  = Path.home() / ".config" / "ster"
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


# ── subprocess helper ─────────────────────────────────────────────────────────

def _git(*args: str, cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _git_available() -> bool:
    try:
        r = subprocess.run(["git", "--version"], capture_output=True)
        return r.returncode == 0
    except FileNotFoundError:
        return False


# ── diff renderer ─────────────────────────────────────────────────────────────

def render_diff(diff: str, max_lines: int = 60) -> None:
    """Print a unified diff using Rich markup colours."""
    lines = diff.splitlines()[:max_lines]
    for line in lines:
        if line.startswith("+") and not line.startswith("+++"):
            console.print(f"[green]{line}[/green]")
        elif line.startswith("-") and not line.startswith("---"):
            console.print(f"[red]{line}[/red]")
        elif line.startswith("@@"):
            console.print(f"[cyan]{line}[/cyan]")
        else:
            console.print(f"[dim]{line}[/dim]")
    if len(diff.splitlines()) > max_lines:
        console.print(f"[dim]… {len(diff.splitlines()) - max_lines} more lines[/dim]")


# ── GitManager ────────────────────────────────────────────────────────────────

class GitManager:
    """Manages git operations for a single taxonomy file.

    Each instance is bound to one taxonomy file path.  All config for this
    file is stored under ``self._cfg`` and persisted to the global JSON.
    """

    def __init__(self, taxonomy_path: Path) -> None:
        self.taxonomy_path = taxonomy_path.resolve()
        self._global_cfg   = _load_global_config()
        self._cfg: dict    = self._global_cfg.get(str(self.taxonomy_path), {})

    # ── public API ────────────────────────────────────────────────────────────

    def is_enabled(self) -> bool:
        """Returns False only when the user explicitly opted out for this file."""
        return self._cfg.get("git_enabled", True)

    def is_configured(self) -> bool:
        return bool(self._cfg.get("repo_path"))

    def setup(self) -> bool:
        """Interactive first-time setup.  Returns True if git is now active."""
        if not _git_available():
            console.print("[dim]git not found — skipping version control.[/dim]")
            return False

        # Already opted out?
        if not self.is_enabled():
            return False

        # Auto-detect an existing repo silently
        repo_root = self._find_repo_root()
        if repo_root:
            self._link_existing_repo(repo_root)
            console.print(
                f"[green]✓[/green] Linked to git repo at "
                f"[bold]{repo_root}[/bold]"
            )
            if not self._cfg.get("branch_strategy"):
                self._ask_branch_strategy()
            return True

        # Ask the user if they want git at all
        from rich.prompt import Confirm
        console.print()
        want = Confirm.ask(
            "[bold]Set up Git version control for this taxonomy?[/bold]",
            default=True,
        )
        if not want:
            self._cfg["git_enabled"] = False
            self._persist()
            return False

        # Present options
        from rich.prompt import Prompt
        console.print(
            "\n[bold]Git setup:[/bold]\n"
            "  [cyan]1[/cyan]  Initialise a new local repository here\n"
            "  [cyan]2[/cyan]  Clone from a remote URL (GitHub / GitLab / …)\n"
            "  [cyan]3[/cyan]  Link to an existing local repository"
        )
        choice = Prompt.ask("Choose", choices=["1", "2", "3"], default="1")

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

    def pre_edit_check(self) -> Optional[str]:
        """Fetch; pull if behind; return diff text (or None) for display."""
        if not self.is_configured():
            return None
        repo = self._repo()
        if not repo:
            return None
        if not self._cfg.get("remote_url"):
            return None

        # Silent fetch
        _git("fetch", "--quiet", "origin", cwd=repo)

        main = self._cfg.get("main_branch", "main")
        behind_r = _git("rev-list", "--count", f"HEAD..origin/{main}", cwd=repo)
        if behind_r.returncode != 0:
            return None
        try:
            behind = int(behind_r.stdout.strip())
        except ValueError:
            return None

        if behind == 0:
            return None

        from rich.prompt import Confirm
        console.print(
            f"\n[yellow]⚠  {self.taxonomy_path.name} is "
            f"{behind} commit{'s' if behind > 1 else ''} behind the remote.[/yellow]"
        )
        if not Confirm.ask("Pull latest changes?", default=True):
            return None

        # Record HEAD before pull so we can diff
        before_r = _git("rev-parse", "HEAD", cwd=repo)
        before   = before_r.stdout.strip() if before_r.returncode == 0 else None

        pull_r = _git("pull", "--ff-only", "origin", main, cwd=repo)
        if pull_r.returncode != 0:
            err.print(f"[red]Pull failed:[/red] {pull_r.stderr.strip()}")
            return None

        console.print("[green]✓ Updated.[/green]")

        if before:
            diff_r = _git(
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
        r = _git("rev-parse", "HEAD", cwd=repo)
        if r.returncode == 0:
            self._cfg["last_commit"] = r.stdout.strip()
            self._persist()

    def stage_file(self) -> None:
        """git add the taxonomy file (called after every save, non-blocking)."""
        repo = self._repo()
        if not repo:
            return
        _git("add", str(self.taxonomy_path), cwd=repo)

    def stage_path(self, path: "Path") -> None:
        """git add an arbitrary file in the same repository."""
        repo = self._repo()
        if not repo:
            return
        _git("add", str(path), cwd=repo)

    def has_staged_changes(self) -> bool:
        repo = self._repo()
        if not repo:
            return False
        r = _git("diff", "--cached", "--name-only", cwd=repo)
        return bool(r.returncode == 0 and r.stdout.strip())

    def commit_new_taxonomy(self, commit_msg: str) -> None:
        """Stage the taxonomy file, commit with *commit_msg*, and push if remote is set.

        Intended for the initial commit when a new taxonomy is created or first
        added to version control.  Prints a one-line summary on success.
        """
        repo = self._repo()
        if not repo:
            return

        _git("add", str(self.taxonomy_path), cwd=repo)

        r = _git("commit", "-m", commit_msg, cwd=repo)
        if r.returncode != 0:
            if "nothing to commit" in (r.stdout + r.stderr).lower():
                console.print("[dim]File already committed — nothing to add.[/dim]")
            else:
                err.print(f"[red]Commit failed:[/red] {r.stderr.strip()}")
            return

        first_line = commit_msg.splitlines()[0]
        console.print(f"[green]✓ Committed:[/green] {first_line}")

        if not self._cfg.get("remote_url"):
            console.print("[dim]No remote configured — changes committed locally.[/dim]")
            return

        main = self._cfg.get("main_branch", "main")
        self._push_direct(repo, main)

    def commit_and_push(self) -> None:
        """Interactive post-edit flow: commit message → commit → push/PR."""
        if not self.is_configured():
            return
        if not self.has_staged_changes():
            console.print("[dim]No staged changes — nothing to commit.[/dim]")
            return

        from rich.prompt import Prompt, Confirm
        repo    = self._repo()
        main    = self._cfg.get("main_branch", "main")
        strat   = self._cfg.get("branch_strategy", "direct")

        # ── commit message ────────────────────────────────────────────────────
        default_msg = f"Update {self.taxonomy_path.name}"
        console.print()
        try:
            msg = Prompt.ask(
                "[bold]Commit message[/bold]",
                default=default_msg,
            )
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Commit cancelled.[/dim]")
            return

        commit_r = _git("commit", "-m", msg, cwd=repo)
        if commit_r.returncode != 0:
            err.print(f"[red]Commit failed:[/red] {commit_r.stderr.strip()}")
            return
        console.print(f"[green]✓ Committed:[/green] {msg}")

        if not self._cfg.get("remote_url"):
            console.print("[dim]No remote configured — changes committed locally.[/dim]")
            return

        # ── push strategy ─────────────────────────────────────────────────────
        console.print(
            "\n[bold]Push options:[/bold]\n"
            f"  [cyan]1[/cyan]  Push directly to [bold]{main}[/bold]\n"
            "  [cyan]2[/cyan]  Push to a feature branch and open a Pull Request"
        )
        default_choice = "1" if strat == "direct" else "2"
        try:
            choice = Prompt.ask("Choose", choices=["1", "2"], default=default_choice)
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Push cancelled.[/dim]")
            return

        if choice == "1":
            self._push_direct(repo, main)
            # Remember preference
            self._cfg["branch_strategy"] = "direct"
            self._persist()
        else:
            self._push_pr(repo, main, msg)
            self._cfg["branch_strategy"] = "pr"
            self._persist()

    # ── private: setup helpers ────────────────────────────────────────────────

    def _init_new_repo(self) -> bool:
        """Initialise a brand-new local repository, optionally wiring a remote."""
        from rich.prompt import Prompt, Confirm

        repo_dir = self.taxonomy_path.parent
        r = _git("init", cwd=repo_dir)
        if r.returncode != 0:
            err.print(f"[red]git init failed:[/red] {r.stderr.strip()}")
            return False

        gi = repo_dir / ".gitignore"
        if not gi.exists():
            gi.write_text("# ster temp files\n.ster_session\n")

        _git("add", str(gi), cwd=repo_dir)
        _git("commit", "-m", "chore: initialise repository", cwd=repo_dir)

        if Confirm.ask("Add a remote (GitHub / GitLab / …)?", default=True):
            while True:
                url = Prompt.ask("Remote URL (https or ssh)")
                if not url:
                    break
                # Verify connectivity before storing
                console.print(f"[dim]Connecting to {url}…[/dim]")
                ls_r = _git("ls-remote", "--exit-code", url, cwd=repo_dir)
                if ls_r.returncode not in (0, 2):
                    err.print(
                        f"[red]Cannot reach {url}[/red]\n"
                        f"[dim]{ls_r.stderr.strip()}[/dim]"
                    )
                    if not Confirm.ask("Try a different URL?", default=True):
                        break
                    continue
                _git("remote", "add", "origin", url, cwd=repo_dir)
                _git("push", "-u", "origin",
                     self._local_branch(repo_dir), cwd=repo_dir)
                self._cfg["remote_url"] = url
                console.print(f"[green]✓ Remote set to {url}[/green]")
                break

        self._link_existing_repo(repo_dir)
        console.print(f"[green]✓[/green] Repository initialised at [bold]{repo_dir}[/bold]")
        return True

    def _clone_repo(self) -> bool:
        """Link the taxonomy directory to a remote repository.

        Works whether the directory is empty (true clone) or already contains
        files (init-in-place + fetch).  Loops until connectivity and sync are
        verified, or the user cancels.
        """
        from rich.prompt import Prompt, Confirm

        repo_dir = self.taxonomy_path.parent

        while True:
            # ── ask for URL ───────────────────────────────────────────────
            url = Prompt.ask("Repository URL (GitHub https or SSH)")
            if not url:
                return False

            # ── test connectivity ─────────────────────────────────────────
            console.print(f"[dim]Connecting to {url}…[/dim]")
            ls_r = _git("ls-remote", "--exit-code", "--heads", url, cwd=repo_dir)
            remote_empty = ls_r.returncode == 2   # connected, but no refs
            connected    = ls_r.returncode in (0, 2)

            if not connected:
                err.print(
                    f"[red]Cannot reach {url}[/red]\n"
                    f"[dim]{ls_r.stderr.strip()}[/dim]\n"
                    "[dim]Check the URL, your network, and credentials "
                    "(SSH key authorised? HTTPS token valid?)[/dim]"
                )
                if not Confirm.ask("Try a different URL?", default=True):
                    return False
                continue

            console.print("[green]✓ Remote reachable.[/green]")

            # ── is the directory empty enough to do a true clone? ─────────
            existing = [f for f in repo_dir.iterdir() if not f.name.startswith(".")]
            already_git = _git("rev-parse", "--git-dir", cwd=repo_dir).returncode == 0

            if not existing and not already_git:
                # Empty directory — plain git clone
                r = _git("clone", url, ".", cwd=repo_dir)
                if r.returncode != 0:
                    err.print(f"[red]Clone failed:[/red] {r.stderr.strip()}")
                    if not Confirm.ask("Try again?", default=True):
                        return False
                    continue
                console.print(f"[green]✓ Cloned to {repo_dir}[/green]")
            else:
                # Non-empty (or already a git dir) — init-in-place
                ok = self._init_inplace_with_remote(repo_dir, url, remote_empty)
                if not ok:
                    if not Confirm.ask("Try again with a different URL?", default=True):
                        return False
                    continue

            # ── final verification ────────────────────────────────────────
            self._link_existing_repo(repo_dir)
            self._cfg["remote_url"] = url
            self._persist()

            verify = _git("remote", "get-url", "origin", cwd=repo_dir)
            if verify.returncode == 0:
                console.print(
                    f"[bold green]✓ Git configured.[/bold green]  "
                    f"Remote: {verify.stdout.strip()}"
                )
                return True

            err.print("[red]Verification failed — remote not set correctly.[/red]")
            if not Confirm.ask("Retry?", default=True):
                return False

    def _init_inplace_with_remote(
        self, repo_dir: Path, url: str, remote_empty: bool
    ) -> bool:
        """Set up git in a non-empty directory and link it to *url*."""
        from rich.prompt import Prompt, Confirm

        # Init if needed
        already_git = _git("rev-parse", "--git-dir", cwd=repo_dir).returncode == 0
        if not already_git:
            _git("init", cwd=repo_dir)
            gi = repo_dir / ".gitignore"
            if not gi.exists():
                gi.write_text("# ster temp files\n.ster_session\n")

        # Add / update remote
        existing = self._get_remote_url(repo_dir)
        if existing and existing != url:
            console.print(f"[yellow]Replacing existing remote ({existing})[/yellow]")
            _git("remote", "set-url", "origin", url, cwd=repo_dir)
        elif not existing:
            _git("remote", "add", "origin", url, cwd=repo_dir)

        # Fetch to get remote refs
        fetch_r = _git("fetch", "origin", cwd=repo_dir)
        if fetch_r.returncode != 0:
            err.print(f"[red]Fetch failed:[/red] {fetch_r.stderr.strip()}")
            _git("remote", "remove", "origin", cwd=repo_dir)
            return False

        main = self._detect_remote_default_branch(repo_dir)
        self._cfg["main_branch"] = main

        has_remote_branch = (
            _git("rev-parse", f"origin/{main}", cwd=repo_dir).returncode == 0
        )

        if has_remote_branch:
            # ── remote has content: ask how to sync ───────────────────────
            console.print(
                f"\n[yellow]Remote already has content on branch '{main}'.[/yellow]\n"
                "How do you want to sync?\n"
                "  [cyan]1[/cyan]  Pull from remote into this directory\n"
                f"  [cyan]2[/cyan]  Push local files to remote "
                f"(overwrites '{main}' on the remote)\n"
                "  [cyan]3[/cyan]  Skip for now (track manually later)"
            )
            choice = Prompt.ask("Choose", choices=["1", "2", "3"], default="1")

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
        from rich.prompt import Confirm

        local_exists = _git("rev-parse", "--verify", main, cwd=repo_dir).returncode == 0

        if not local_exists:
            r = _git("checkout", "-b", main, "--track", f"origin/{main}", cwd=repo_dir)
        else:
            _git("checkout", main, cwd=repo_dir)
            r = _git("pull", "--ff-only", "origin", main, cwd=repo_dir)
            if r.returncode != 0:
                r = _git(
                    "pull", "--allow-unrelated-histories", "-m",
                    "chore: merge remote history",
                    "origin", main, cwd=repo_dir,
                )

        if r.returncode != 0:
            err.print(f"[red]Pull failed:[/red] {r.stderr.strip()}")
            return False

        console.print(f"[green]✓ Pulled '{main}' from remote.[/green]")
        return True

    def _push_local_to_remote(
        self, repo_dir: Path, main: str, force: bool
    ) -> bool:
        """Stage all local files, commit if needed, and push to remote."""
        from rich.prompt import Confirm

        self._ensure_on_branch(repo_dir, main)
        _git("add", ".", cwd=repo_dir)

        # Commit only if there is something staged
        status_r = _git("diff", "--cached", "--name-only", cwd=repo_dir)
        if status_r.stdout.strip():
            c = _git("commit", "-m", "chore: add existing taxonomy", cwd=repo_dir)
            if c.returncode != 0 and "nothing to commit" not in c.stdout + c.stderr:
                err.print(f"[red]Commit failed:[/red] {c.stderr.strip()}")
                return False

        push_args = ["push", "-u", "origin", main]
        if force:
            push_args.insert(1, "--force")
        push_r = _git(*push_args, cwd=repo_dir)

        if push_r.returncode != 0:
            err.print(f"[red]Push failed:[/red] {push_r.stderr.strip()}")
            if not force and Confirm.ask(
                "Force push? (overwrites remote history)", default=False
            ):
                push_r = _git("push", "--force", "-u", "origin", main, cwd=repo_dir)
                if push_r.returncode != 0:
                    err.print(f"[red]Force push failed:[/red] {push_r.stderr.strip()}")
                    return False
            else:
                return False

        console.print(f"[green]✓ Pushed to '{main}'.[/green]")
        return True

    @staticmethod
    def _ensure_on_branch(repo_dir: Path, branch: str) -> None:
        """Make sure the repo is on *branch*, creating it if necessary."""
        current = _git("branch", "--show-current", cwd=repo_dir).stdout.strip()
        if current == branch:
            return
        if _git("rev-parse", "--verify", branch, cwd=repo_dir).returncode == 0:
            _git("checkout", branch, cwd=repo_dir)
        else:
            _git("checkout", "-b", branch, cwd=repo_dir)

    def _detect_remote_default_branch(self, repo_dir: Path) -> str:
        """Return the remote's HEAD branch name, falling back to 'main'."""
        show_r = _git("remote", "show", "origin", cwd=repo_dir)
        for line in show_r.stdout.splitlines():
            if "HEAD branch:" in line:
                return line.split(":")[-1].strip()
        for branch in ("main", "master"):
            if _git("rev-parse", f"origin/{branch}", cwd=repo_dir).returncode == 0:
                return branch
        return "main"

    @staticmethod
    def _local_branch(repo_dir: Path) -> str:
        r = _git("branch", "--show-current", cwd=repo_dir)
        return r.stdout.strip() or "main"

    def _link_repo_interactive(self) -> bool:
        """Link to an existing local repository with retry."""
        from rich.prompt import Prompt, Confirm

        while True:
            default  = str(self.taxonomy_path.parent)
            path_str = Prompt.ask("Path to git repository", default=default)
            p        = Path(path_str).expanduser().resolve()
            if _git("rev-parse", "--git-dir", cwd=p).returncode == 0:
                self._link_existing_repo(p)
                console.print(f"[green]✓[/green] Linked to [bold]{p}[/bold]")
                return True
            err.print(f"[red]Not a git repository: {p}[/red]")
            if not Confirm.ask("Try a different path?", default=True):
                return False

    def _link_existing_repo(self, repo_root: Path) -> None:
        self._cfg["repo_path"] = str(repo_root)
        url = self._get_remote_url(repo_root)
        if url:
            self._cfg["remote_url"] = url
        self._detect_main_branch(repo_root)
        self._persist()

    def _ask_branch_strategy(self) -> None:
        from rich.prompt import Prompt
        console.print(
            "\n[bold]Default push strategy:[/bold]\n"
            "  [cyan]1[/cyan]  Direct push to main  (single user, no review)\n"
            "  [cyan]2[/cyan]  Feature branch + Pull Request  (team workflow)"
        )
        choice = Prompt.ask("Choose", choices=["1", "2"], default="1")
        self._cfg["branch_strategy"] = "direct" if choice == "1" else "pr"
        self._persist()

    # ── private: push helpers ─────────────────────────────────────────────────

    def _push_direct(self, repo: Path, branch: str) -> None:
        r = _git("push", "origin", branch, cwd=repo)
        if r.returncode == 0:
            console.print(f"[green]✓ Pushed to[/green] [bold]{branch}[/bold]")
        else:
            err.print(f"[red]Push failed:[/red] {r.stderr.strip()}")

    def _push_pr(self, repo: Path, main: str, commit_msg: str) -> None:
        from rich.prompt import Prompt

        # Generate a default branch name
        ts       = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        default  = f"ster/{ts}"
        fb       = Prompt.ask("Feature branch name", default=default)

        # Push HEAD to a new remote branch without switching locally
        push_ref = f"HEAD:refs/heads/{fb}"
        r        = _git("push", "origin", push_ref, cwd=repo)
        if r.returncode != 0:
            err.print(f"[red]Push failed:[/red] {r.stderr.strip()}")
            return
        console.print(f"[green]✓ Pushed to[/green] [bold]{fb}[/bold]")

        # PR details
        pr_title = Prompt.ask("PR title", default=commit_msg)
        pr_body  = Prompt.ask("PR description (optional)", default="")

        pr_url = self._create_pr(repo, fb, main, pr_title, pr_body)
        if pr_url:
            console.print(f"[bold green]✓ Pull Request:[/bold green] {pr_url}")
        else:
            remote = self._cfg.get("remote_url", "")
            if "github.com" in remote:
                clean = remote.rstrip("/").removesuffix(".git")
                console.print(
                    f"\n[yellow]Create a PR at:[/yellow]\n"
                    f"  {clean}/compare/{main}...{fb}"
                )

    def _create_pr(
        self, repo: Path, head: str, base: str, title: str, body: str
    ) -> Optional[str]:
        """Try gh CLI, then GitHub REST API.  Returns PR URL or None."""
        # ── 1. gh CLI ─────────────────────────────────────────────────────────
        gh_r = subprocess.run(
            ["gh", "pr", "create",
             "--title", title,
             "--body",  body or " ",
             "--base",  base,
             "--head",  head],
            cwd=repo, capture_output=True, text=True,
        )
        if gh_r.returncode == 0:
            return gh_r.stdout.strip()

        # ── 2. GitHub REST API ────────────────────────────────────────────────
        token = self._get_github_token()
        if not token:
            return None
        owner_repo = self._parse_github_owner_repo(
            self._cfg.get("remote_url", "")
        )
        if not owner_repo:
            return None

        import urllib.request
        import urllib.error

        owner, repo_name = owner_repo
        data = json.dumps({
            "title": title, "body": body,
            "head": head, "base": base,
        }).encode()
        req = urllib.request.Request(
            f"https://api.github.com/repos/{owner}/{repo_name}/pulls",
            data=data,
            headers={
                "Authorization": f"token {token}",
                "Content-Type":  "application/json",
                "User-Agent":    "ster-taxonomy-editor/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read()).get("html_url")
        except urllib.error.HTTPError as exc:
            err.print(f"[red]GitHub API {exc.code}:[/red] {exc.reason}")
            return None
        except Exception as exc:
            err.print(f"[red]GitHub API error:[/red] {exc}")
            return None

    # ── private: github helpers ───────────────────────────────────────────────

    def _get_github_token(self) -> Optional[str]:
        """Session-only token: try gh CLI, then prompt (never saved by default)."""
        # 1. gh CLI auth token
        gh_r = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True
        )
        if gh_r.returncode == 0 and gh_r.stdout.strip():
            return gh_r.stdout.strip()

        # 2. Stored token (user explicitly opted to save it previously)
        stored = self._cfg.get("github_token")
        if stored:
            return stored

        # 3. Prompt
        from rich.prompt import Prompt, Confirm
        console.print(
            "\n[yellow]GitHub token needed for PR creation.[/yellow]\n"
            "[dim]Create one at github.com/settings/tokens (needs 'repo' scope).[/dim]\n"
            "[dim]Recommended: authenticate via `gh auth login` instead.[/dim]"
        )
        token = Prompt.ask("Personal Access Token (Enter to skip)", default="")
        if not token:
            return None

        if Confirm.ask(
            "[yellow]⚠ Save token in plaintext (~/.config/ster/git_repos.json)?[/yellow]",
            default=False,
        ):
            self._cfg["github_token"] = token
            self._persist()
        return token

    @staticmethod
    def _parse_github_owner_repo(url: str) -> Optional[tuple[str, str]]:
        m = re.search(r"github\.com[:/]([^/]+)/([^/\\.]+)", url)
        return (m.group(1), m.group(2)) if m else None

    # ── private: git utility ──────────────────────────────────────────────────

    def _find_repo_root(self) -> Optional[Path]:
        r = _git("rev-parse", "--show-toplevel", cwd=self.taxonomy_path.parent)
        return Path(r.stdout.strip()) if r.returncode == 0 else None

    def _repo(self) -> Optional[Path]:
        rp = self._cfg.get("repo_path")
        if rp:
            p = Path(rp)
            return p if p.exists() else None
        return None

    def _get_remote_url(self, repo: Path) -> Optional[str]:
        r = _git("remote", "get-url", "origin", cwd=repo)
        return r.stdout.strip() if r.returncode == 0 else None

    def _detect_main_branch(self, repo: Path) -> None:
        for branch in ("main", "master"):
            if _git("rev-parse", "--verify", branch, cwd=repo).returncode == 0:
                self._cfg["main_branch"] = branch
                return
        r = _git("branch", "--show-current", cwd=repo)
        self._cfg["main_branch"] = r.stdout.strip() or "main"

    # ── private: config persistence ──────────────────────────────────────────

    def _persist(self) -> None:
        self._global_cfg[str(self.taxonomy_path)] = self._cfg
        _save_global_config(self._global_cfg)
