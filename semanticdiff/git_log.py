"""The git adapter — the only module that shells out to git.

Everything above this file works on graphs and dataclasses, so a change of
version-control backend touches one module.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

RDF_SUFFIXES = frozenset({".ttl", ".rdf", ".owl", ".jsonld", ".nt", ".n3", ".trig", ".nq"})

_FIELD = "\x1f"
_RECORD = "\x1e"
_FORMAT = f"{_RECORD}%H{_FIELD}%h{_FIELD}%an{_FIELD}%aI{_FIELD}%s"


class GitError(RuntimeError):
    """git refused the command."""


class UnknownRevisionError(GitError):
    """The revision or range does not resolve in this repository."""


@dataclass(frozen=True)
class Commit:
    """One commit that touched the tracked ontology."""

    sha: str
    short_sha: str
    author: str
    date: str
    subject: str
    other_files: int = 0


def walk(repo: Path, rev_range: str, path: str) -> list[Commit]:
    """Commits in `rev_range` that touched `path`, oldest first."""
    _require_tracked(repo, path)
    out = _git(repo, "log", "--reverse", f"--format={_FORMAT}", "--name-only", rev_range)
    return list(_records(out, path))


def raw_diff(repo: Path, sha: str, path: str) -> str:
    """The unified diff hunk for `path` in one commit — the last layer of the drill-down."""
    return _git(repo, "show", "--format=", sha, "--", path)


def read_blob(repo: Path, rev: str, path: str) -> str | None:
    """The file's content at a revision, or None when it does not exist there."""
    result = _run(repo, "show", f"{rev}:{path}")
    return None if result.returncode != 0 else result.stdout


def list_tracked(repo: Path) -> list[str]:
    """Every path git tracks at HEAD."""
    return [line for line in _git(repo, "ls-files").splitlines() if line]


def resolve(repo: Path, rev: str) -> str | None:
    """`rev` as a commit sha, or None when it does not exist (a root's parent).

    Used to key a parse cache: `<sha>^` and the sha of the commit before it name
    the same revision, and only the resolved form makes them share an entry.
    """
    result = _run(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    return result.stdout.strip() or None


def repo_root(path: Path) -> Path | None:
    """The repository `path` lives in, or None when it is not tracked anywhere."""
    result = _run(path.parent if path.is_file() else path, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def tags_by_commit(repo: Path) -> dict[str, tuple[str, ...]]:
    """`{sha: tags}` — the release markers a history list shows beside a commit."""
    out = _git(repo, "for-each-ref", "--format=%(objectname) %(refname:short)", "refs/tags")
    tags: dict[str, list[str]] = {}
    for line in out.splitlines():
        sha, _, name = line.partition(" ")
        if name:
            tags.setdefault(_peel(repo, sha), []).append(name)
    return {sha: tuple(sorted(names)) for sha, names in tags.items()}


def _peel(repo: Path, sha: str) -> str:
    """The commit a tag points at, following an annotated tag's own object."""
    return _git(repo, "rev-list", "-n", "1", sha).strip() or sha


def _require_tracked(repo: Path, path: str) -> None:
    """Fail loudly when the path was never in this repository at all.

    Checked over the whole history rather than the requested range, so that an
    empty range reports no commits instead of a missing file.
    """
    if not _git(repo, "log", "--all", "--format=%H", "-n", "1", "--", path).strip():
        raise FileNotFoundError(f"{path} is not tracked in {repo}")


def _records(out: str, path: str) -> Iterator[Commit]:
    for record in out.split(_RECORD):
        if not record.strip():
            continue
        commit = _record(record, path)
        if commit is not None:
            yield commit


def _record(record: str, path: str) -> Commit | None:
    header, _, body = record.strip("\n").partition("\n")
    sha, short_sha, author, date, subject = header.split(_FIELD)
    files = [line for line in body.splitlines() if line.strip()]
    if path not in files:
        return None
    return Commit(
        sha=sha,
        short_sha=short_sha,
        author=author,
        date=date,
        subject=subject,
        other_files=sum(1 for f in files if Path(f).suffix.lower() not in RDF_SUFFIXES),
    )


# git translates its messages, so a French machine reports "révision inconnue"
# where CI reports "unknown revision". Pin the locale rather than the wording.
_C_LOCALE = {"LC_ALL": "C", "LANG": "C"}


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **_C_LOCALE},
    )


def _git(repo: Path, *args: str) -> str:
    result = _run(repo, *args)
    if result.returncode != 0:
        raise _translate(result.stderr)
    return result.stdout


def _translate(stderr: str) -> GitError:
    message = stderr.strip() or "git failed"
    if "unknown revision" in stderr or "bad revision" in stderr:
        return UnknownRevisionError(message)
    return GitError(message)
