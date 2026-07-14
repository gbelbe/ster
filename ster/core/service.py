"""TaxonomyService — the single transactional pipeline for every mutation.

``execute`` runs one command (later: a batch) as a transaction:
per-file lock → optimistic-concurrency check → clone → apply → persist →
swap → bump version. A failure discards the clone, so the live model and the
file on disk are never left half-changed. (The validation gate lands in Phase 3,
between *apply* and *persist*.)
"""

from __future__ import annotations

import copy
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..exceptions import SkostaxError
from ..model import Taxonomy
from .commands import Command
from .ports import Persistence, Validator, Workspace
from .validation import ValidationReport


@dataclass(frozen=True)
class CommandResult:
    """Outcome of a command: applied, rejected (stale version), or failed (domain/validation)."""

    status: Literal["ok", "failed", "rejected"]
    version: int | None = None
    affected_uris: tuple[str, ...] = ()
    error: str | None = None
    validation: ValidationReport | None = None  # delta issues (warnings on ok, errors on block)

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class TaxonomyService:
    """Owns the loaded workspace as the single source of truth for mutations."""

    def __init__(
        self,
        workspace: Workspace,
        persistence: Persistence,
        validator: Validator | None = None,
    ) -> None:
        self._workspace = workspace
        self._persistence = persistence
        self._validator = validator
        self._versions: dict[Path, int] = {}
        self._locks: dict[Path, threading.Lock] = {}
        self._guard = threading.Lock()

    def version(self, path: Path) -> int:
        """Current optimistic-concurrency version for *path* (0 before any commit)."""
        return self._versions.get(path, 0)

    def _lock_for(self, path: Path) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(path, threading.Lock())

    def _validate_delta(self, before: Taxonomy, after: Taxonomy) -> ValidationReport | None:
        """Issues the change introduces (None when no validator is configured)."""
        if self._validator is None:
            return None
        return ValidationReport.delta(self._validator.check(before), self._validator.check(after))

    def execute(
        self, command: Command, *, base_version: int | None = None, persist: bool = True
    ) -> CommandResult:
        """Run *command* as a transaction; see module docstring for the pipeline.

        ``persist=False`` mutates + validates + swaps the in-memory authority but skips
        the (potentially slow) disk write — the caller is then responsible for persisting
        the new authority (e.g. the TUI writes it on a background worker so edits stay
        snappy on large ontologies)."""
        path = command.target_path
        with self._lock_for(path):
            current = self._versions.get(path, 0)
            if base_version is not None and base_version != current:
                return CommandResult(
                    "rejected",
                    version=current,
                    error=f"version conflict: based on {base_version}, current is {current}",
                )
            taxonomy = self._workspace.taxonomies.get(path)
            if taxonomy is None:
                return CommandResult("failed", error=f"no taxonomy loaded for {path}")

            working = copy.deepcopy(taxonomy)
            try:
                affected = command.apply(working)
            except SkostaxError as exc:
                return CommandResult("failed", error=str(exc))

            report = self._validate_delta(taxonomy, working)
            if report is not None and report.blocks():
                return CommandResult(
                    "failed",
                    error=f"change introduces {len(report.errors)} validation error(s)",
                    validation=report,
                )

            if persist:
                self._persistence.save(working, path)
            self._workspace.taxonomies[path] = working  # atomic swap of the authority
            new_version = current + 1
            self._versions[path] = new_version
            return CommandResult(
                "ok", version=new_version, affected_uris=affected, validation=report
            )
