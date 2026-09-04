"""Push strategies: direct push to main, or feature-branch + Pull Request
(via ``gh`` CLI first, falling back to the GitHub REST API)."""

from __future__ import annotations

import datetime
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from . import _console, _subprocess
from ._state import _ManagerState


class _PushMixin(_ManagerState):
    """Direct-push and PR-creation helpers used by ``commit_and_push``."""

    def _push_direct(self, repo: Path, branch: str) -> None:
        r = _subprocess._git("push", "origin", branch, cwd=repo)
        if r.returncode == 0:
            _console.console.print(f"[green]✓ Pushed to[/green] [bold]{branch}[/bold]")
        else:
            _console.err.print(f"[red]Push failed:[/red] {r.stderr.strip()}")

    def _push_pr(self, repo: Path, main: str, commit_msg: str) -> None:
        from rich.prompt import Prompt

        # Generate a default branch name
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        default = f"ster/{ts}"
        fb = Prompt.ask("Feature branch name", default=default)

        # Push HEAD to a new remote branch without switching locally
        push_ref = f"HEAD:refs/heads/{fb}"
        r = _subprocess._git("push", "origin", push_ref, cwd=repo)
        if r.returncode != 0:
            _console.err.print(f"[red]Push failed:[/red] {r.stderr.strip()}")
            return
        _console.console.print(f"[green]✓ Pushed to[/green] [bold]{fb}[/bold]")

        # PR details
        pr_title = Prompt.ask("PR title", default=commit_msg)
        pr_body = Prompt.ask("PR description (optional)", default="")

        pr_url = self._create_pr(repo, fb, main, pr_title, pr_body)
        if pr_url:
            _console.console.print(f"[bold green]✓ Pull Request:[/bold green] {pr_url}")
        else:
            remote = self._cfg.get("remote_url", "")
            if match := self._parse_github_owner_repo(remote):
                owner, repo_name = match
                _console.console.print(
                    f"\n[yellow]Create a PR at:[/yellow]\n"
                    f"  https://github.com/{owner}/{repo_name}/compare/{main}...{fb}"
                )

    def _create_pr(self, repo: Path, head: str, base: str, title: str, body: str) -> str | None:
        """Try gh CLI, then GitHub REST API.  Returns PR URL or None."""
        # ── 1. gh CLI ─────────────────────────────────────────────────────────
        gh_r = subprocess.run(
            [
                "gh",
                "pr",
                "create",
                "--title",
                title,
                "--body",
                body or " ",
                "--base",
                base,
                "--head",
                head,
            ],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        if gh_r.returncode == 0:
            return gh_r.stdout.strip()

        # ── 2. GitHub REST API ────────────────────────────────────────────────
        token = self._get_github_token()
        if not token:
            return None
        owner_repo = self._parse_github_owner_repo(self._cfg.get("remote_url", ""))
        if not owner_repo:
            return None

        import urllib.error
        import urllib.request

        owner, repo_name = owner_repo
        data = json.dumps(
            {
                "title": title,
                "body": body,
                "head": head,
                "base": base,
            }
        ).encode()
        req = urllib.request.Request(
            f"https://api.github.com/repos/{owner}/{repo_name}/pulls",
            data=data,
            headers={
                "Authorization": f"token {token}",
                "Content-Type": "application/json",
                "User-Agent": "ster-taxonomy-editor/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read()).get("html_url")
        except urllib.error.HTTPError as exc:
            _console.err.print(f"[red]GitHub API {exc.code}:[/red] {exc.reason}")
            return None
        except Exception as exc:
            _console.err.print(f"[red]GitHub API error:[/red] {exc}")
            return None

    # ── private: github helpers ───────────────────────────────────────────────

    def _get_github_token(self) -> str | None:
        """Session-only token: try gh CLI, then prompt (never saved by default)."""
        # 1. gh CLI auth token
        gh_r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
        if gh_r.returncode == 0 and gh_r.stdout.strip():
            return gh_r.stdout.strip()

        # 2. Stored token (user explicitly opted to save it previously)
        stored = self._cfg.get("github_token")
        if stored:
            return stored

        # 3. Prompt
        from rich.prompt import Confirm, Prompt

        _console.console.print(
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
    def _parse_github_owner_repo(url: str) -> tuple[str, str] | None:
        if not url:
            return None

        # 1. Try URL parsing for schemes like https:// or ssh://
        # This handles explicit ports correctly: ssh://git@github.com:443/owner/repo
        if "://" in url:
            try:
                parsed = urlparse(url)
                # Path is usually /owner/repo or /owner/repo.git.
                path_parts = parsed.path.strip("/").split("/")
                if parsed.hostname == "github.com" and len(path_parts) >= 2:
                    owner, repo = path_parts[0], path_parts[1]
                    return owner, repo.removesuffix(".git")
            except Exception:
                pass

        # 2. Try scp-style parsing (git@github.com:owner/repo.git)
        # We only match if it looks like a github.com host followed by a colon
        scp_pattern = r"^(?:git@)?github\.com:([^/ \?#]+)/([^/ \?#]+)"
        match = re.search(scp_pattern, url)
        if match:
            owner, repo = match.groups()
            return owner, repo.removesuffix(".git")

        return None
