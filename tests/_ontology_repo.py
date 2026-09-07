"""A throw-away git repository holding a tracked turtle file.

`RepoBuilder` lets the semanticdiff git adapter be tested against real git
plumbing rather than against a mock of it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ONTOLOGY = "onto.ttl"

PREFIXES = """
@prefix ex:   <http://example.org/> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
"""


class RepoBuilder:
    """A minimal git repository with a tracked ontology file."""

    def __init__(self, root: Path) -> None:
        self.path = root
        root.mkdir(parents=True, exist_ok=True)
        self._git("init", "-b", "main")
        self._git("config", "user.name", "Ada Lovelace")
        self._git("config", "user.email", "ada@example.test")

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(self.path), *args],
            capture_output=True,
            text=True,
            check=True,
        )

    def commit(
        self,
        *,
        ttl: str | None = None,
        raw: str | None = None,
        files: dict[str, str] | None = None,
        message: str = "change the ontology",
    ) -> str:
        """Write the ontology (and any extra files), commit, return the sha."""
        if ttl is not None:
            (self.path / ONTOLOGY).write_text(PREFIXES + ttl, encoding="utf-8")
        if raw is not None:
            (self.path / ONTOLOGY).write_text(raw, encoding="utf-8")
        for name, body in (files or {}).items():
            (self.path / name).write_text(body, encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-m", message)
        return self._git("rev-parse", "HEAD").stdout.strip()

    def tag(self, name: str) -> None:
        self._git("tag", name)
