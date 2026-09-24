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


@runtime_checkable
class Renames(Protocol):
    """Optional: a command that can change one entity's URI says which, old → new.

    Anything keyed by URI outside the model — the remembered graph layout — needs
    telling, or it keeps entries under URIs that no longer exist.
    """

    def renamed_uris(self) -> dict[str, str]: ...


@runtime_checkable
class RenamesInModel(Protocol):
    """Optional: a command whose renames depend on the model it was applied to.

    A namespace change moves every local entity, so which URIs moved can only be
    read from the model *before* it ran. Kept apart from :class:`Renames` so a
    single-entity rename is not handed a model it has no use for.
    """

    def renamed_uris_in(self, before: Taxonomy) -> dict[str, str]: ...


def renamed_pair(old_uri: str, new_uri: str) -> dict[str, str]:
    """``{old: new}`` when a single-entity edit really changed the URI, else nothing."""
    return {old_uri: new_uri} if new_uri and new_uri != old_uri else {}


def renames_of(command: object, before: Taxonomy) -> dict[str, str]:
    """What *command* renamed, when applied to *before*; nothing if it cannot rename."""
    if isinstance(command, RenamesInModel):
        return command.renamed_uris_in(before)
    if isinstance(command, Renames):
        return command.renamed_uris()
    return {}


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

    def renamed_uris_in(self, before: Taxonomy) -> dict[str, str]:
        """Everything the batch's commands renamed."""
        renamed: dict[str, str] = {}
        for command in self.commands:
            renamed.update(renames_of(command, before))
        return renamed
