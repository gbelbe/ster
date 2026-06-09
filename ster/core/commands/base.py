"""The Command protocol — the generic shape ``TaxonomyService`` depends on."""

from __future__ import annotations

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
