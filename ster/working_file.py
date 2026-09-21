"""Which of the open files is the writable one — the working-file role swap.

A session loads several files and keeps exactly one writable; the rest are
read-only context (see ``store.load``'s *context* argument and
``Taxonomy.context_source``). Changing that choice mid-session is a fact about
*paths*, not about the model: no taxonomy is mutated here, and nothing is
parsed. Keeping it that way is what lets the editor, the API and the tests all
reach the same decision without any of them owning it.

Sequencing is the whole risk of this operation, so it lives in :func:`switch`
rather than inside the editor's background worker. Every way a switch goes
wrong is an ordering mistake — writing a pending edit *after* the roles moved
puts one file's model in another file's path — and ordering that is reachable
only through a Textual worker can only be tested by racing it. The side
effects are therefore injected: the caller supplies *flush*, *load* and
*apply*, and this module decides when each one runs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

__all__ = [
    "MissingWorkingFile",
    "SwitchOutcome",
    "UnknownWorkingFile",
    "WorkingFileError",
    "switch",
    "switch_roles",
]


class WorkingFileError(ValueError):
    """A working-file switch that cannot be carried out."""


class UnknownWorkingFile(WorkingFileError):
    """The chosen file is not one of the session's open files.

    Switching only ever reorders roles among files that are already loaded; it
    is not a way to open something new, so a path from outside that set is a
    caller error rather than a silent no-op.
    """


class MissingWorkingFile(WorkingFileError):
    """The chosen file is open in the session but no longer on disk.

    Worth its own type: the session is not confused about which files it has,
    the file was deleted or moved underneath it, and the fix the user needs to
    hear about is a filesystem one.
    """


def switch_roles(chosen: Path, loaded: list[Path]) -> tuple[Path, list[Path]]:
    """Return the ``(editable, context)`` pair that makes *chosen* writable.

    *loaded* is every file in the session, in the order the menu shows them;
    that order is preserved in the returned context list so reopening the menu
    never reshuffles the rows. Choosing the file that is already writable
    returns the roles unchanged, which is how the caller knows to skip the
    reload entirely.

    Which file is *currently* writable is not needed: the answer is derived from
    *chosen* and *loaded* alone, and "already writable" falls out of the result
    matching what the caller had. The parameter was taken and ignored.
    """
    if chosen not in loaded:
        raise UnknownWorkingFile(f"{chosen} is not open in this session")
    return chosen, [path for path in loaded if path != chosen]


@dataclass(frozen=True)
class SwitchOutcome:
    """What a switch settled on, and whether it cost a reload."""

    editable: Path
    context: list[Path]
    reloaded: bool


class _Apply(Protocol):
    def __call__(self, taxonomy: object, editable: Path, context: list[Path]) -> None: ...


def switch(
    chosen: Path,
    *,
    current: Path,
    loaded: list[Path],
    flush: Callable[[], None],
    load: Callable[[Path, list[Path]], object],
    apply: _Apply,
) -> SwitchOutcome:
    """Make *chosen* the working file, running the steps in the only safe order.

    *flush* persists any pending edit, *load* re-parses (``store.load``), and
    *apply* installs the result — swapping the model, the path and the context
    together, which callers that save in the background must do atomically.

    The order is the point:

    1. **Validate first.** A refused switch must leave the session exactly as
       it was, so nothing is flushed or parsed on behalf of a switch that is
       not going to happen.
    2. **No-op early.** Choosing the file that is already writable returns
       without flushing, parsing or applying — re-parsing a large ontology
       because someone reopened a menu and picked the current row is a freeze
       with nothing to show for it.
    3. **Flush before the roles move.** A pending edit belongs to the file that
       is writable *now*. Flushing afterwards writes the old model through the
       new path, which is how one ontology ends up inside another's file.
    4. **Load before apply.** A parse failure leaves the previous model in
       place rather than a half-switched session.
    """
    if chosen not in loaded:
        raise UnknownWorkingFile(f"{chosen} is not open in this session")
    if not chosen.exists():
        raise MissingWorkingFile(f"{chosen} is no longer on disk")

    editable, context = switch_roles(chosen, loaded=loaded)
    if chosen == current:
        return SwitchOutcome(editable, context, reloaded=False)

    flush()
    taxonomy = load(editable, context)
    apply(taxonomy, editable, context)
    return SwitchOutcome(editable, context, reloaded=True)
