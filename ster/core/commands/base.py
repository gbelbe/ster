"""The Command protocol — the generic shape ``TaxonomyService`` depends on."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from ...model import Taxonomy


@runtime_checkable
class Command(Protocol):
    """A user intent that applies itself to a taxonomy and reports affected URIs.

    A command is *intent* (serializable fields) plus a thin ``apply`` that
    delegates to the specialized domain logic in ``ster.operations``. The service
    never switches on command type — it just calls ``apply`` — so a new action is
    one dataclass, with no edit to the pipeline (open/closed).
    """

    target_path: Path  # the file the command mutates

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class ChangeSet:
    """An ordered batch of commands committed as one atomic transaction.

    All commands act on ``target_path``; ``apply`` runs them in order on the same
    working copy, so the whole batch commits or rolls back together. A ChangeSet
    itself satisfies the :class:`Command` protocol, so ``TaxonomyService.execute``
    runs it with no special-casing — one clone, one validation of the cumulative
    delta, one persist, one version bump.
    """

    target_path: Path
    commands: tuple[Command, ...]

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        affected: list[str] = []
        for command in self.commands:
            affected.extend(command.apply(taxonomy))
        return tuple(affected)
