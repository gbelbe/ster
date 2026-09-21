"""A ratchet on waits that guess instead of waiting for a condition.

    for _ in range(4):
        await pilot.pause()
    assert something_happened()

This says "four turns of the event loop ought to be enough". Sometimes it is.
Under `-n auto` on a loaded machine it sometimes is not, and then a true
assertion fails — the worst kind of red, because the code is fine and the next
run is green, so the habit is to re-run rather than to look.

It has cost this repository real time. Five tests were converted to `_settle`
in one pass and three of those predicates still stopped one callback short of
what the test asserted; a scan-on-open test ran a full pySHACL pass against a
fifteen-second deadline; a highlight test waited for a label to land when the
thing that could move the highlight was the tree rebuild *after* it.

The alternative is always the same shape: wait for the condition the assertion
depends on. `_settle(pilot, predicate)` in tests/unit/test_tui_app.py, or the
`settle` fixture in conftest, return as soon as it holds — so a correct wait is
also the fastest one.

This is a ratchet, not a ban. The existing waits are grandfathered because
converting them all at once would be a large, risky diff across fifteen files.
The count may fall and must never rise.
"""

from __future__ import annotations

import pathlib
import re

# A fixed-count pump: `for _ in range(N): await pilot.pause()`.
_FIXED_WAIT = re.compile(r"for\s+_\s+in\s+range\(\s*\d+\s*\)\s*:\s*\n\s*await\s+pilot\.pause\(\)")

# Lowered as tests are converted; never raised. When it reaches zero, delete
# this module and add a lint rule instead.
#
# 67 -> 66: test_app_create_reveal's two waits. The background-lint one was the
# more instructive of the pair - six turns never reached the 1.5 s debounce, so
# the test ended with the worker still in flight, it landed during teardown, and
# rebuilding a tree that was already gone raised WorkerFailed. The flake was
# reporting a real race in _on_lint_ready, not a slow machine.
_BASELINE = 65

_TESTS = pathlib.Path(__file__).resolve().parents[1]


def _offenders() -> dict[str, int]:
    found: dict[str, int] = {}
    for path in sorted(_TESTS.rglob("*.py")):
        if path.name == pathlib.Path(__file__).name:
            continue
        hits = len(_FIXED_WAIT.findall(path.read_text(encoding="utf-8")))
        if hits:
            found[str(path.relative_to(_TESTS))] = hits
    return found


def test_no_new_fixed_count_waits() -> None:
    found = _offenders()
    total = sum(found.values())

    assert total <= _BASELINE, (
        f"{total - _BASELINE} new fixed-count wait(s) — a guess about timing, not a wait.\n"
        "Use _settle / the settle fixture with a predicate naming the condition the\n"
        "assertion depends on. Current counts:\n"
        + "\n".join(f"    {n:>3}  {f}" for f, n in sorted(found.items(), key=lambda kv: -kv[1]))
    )


# ── the second shape: a wall-clock wait on the wrong condition ───────────────
#
# Converting a fixed-count wait to `settle` fixes the deadline and leaves the
# harder half untouched — *what* is being waited for. The recurring instance in
# this repo is a screen: Textual swaps it, then mounts its children on a later
# turn, so
#
#     await settle(pilot, lambda: isinstance(app.screen, SomeModal))
#     assert len(app.screen.query(SomeRow)) == 1
#
# returns with the modal open and empty. It passes on an idle machine and fails
# under -n auto, which is the worst kind of red. It has been fixed twice — #202
# for the step_defs copy, and again here for the unit copy that fix missed — so
# it is a class, not an instance, and gets a rule rather than a third fix.
#
# Unlike the count above, this one starts at zero: there is no backlog to
# grandfather, because both known cases are fixed.

_SCREEN_ONLY_WAIT = re.compile(
    r"settle\(\s*\n?\s*pilot\s*,\s*\n?\s*lambda:[^\n]*isinstance\([^\n]*\.screen[^\n]*"
)
#: lines after the wait in which a child query belongs to the same thought
_WINDOW = 6


def _screen_only_waits() -> list[str]:
    """Waits naming a screen where the assertion needs that screen's children."""
    offences = []
    for path in sorted(_TESTS.rglob("*.py")):
        if path.name == pathlib.Path(__file__).name:
            continue
        lines = path.read_text(encoding="utf-8").split("\n")
        for index, line in enumerate(lines):
            nxt = lines[index + 1] if index + 1 < len(lines) else ""
            block = f"{line}\n{nxt}"
            if not _SCREEN_ONLY_WAIT.search(block) or "query(" in block:
                continue
            for offset, candidate in enumerate(lines[index + 1 : index + 1 + _WINDOW]):
                # A .query( inside a *later* settle is the correct fix, not an offence.
                if "settle(" in candidate:
                    break
                if ".query(" in candidate:
                    offences.append(
                        f"{path.relative_to(_TESTS)}:{index + 1} waits for the screen, "
                        f"then line {index + 2 + offset} queries its children"
                    )
                    break
    return offences


def test_no_wait_stops_at_the_screen_when_the_assertion_needs_its_children() -> None:
    offences = _screen_only_waits()

    assert not offences, (
        "A wait that names the screen returns before its children mount:\n"
        + "\n".join(f"    {o}" for o in offences)
        + "\n\nName the children in the predicate — `isinstance(app.screen, M) and "
        "app.screen.query(Row)` — or add a second settle for them."
    )


def test_the_baseline_is_not_stale() -> None:
    """A ratchet nobody tightens is a ceiling. When conversions bring the real
    count below the baseline, this fails and asks for the baseline to follow —
    otherwise the budget silently refills and new guesses slip in."""
    total = sum(_offenders().values())

    assert total >= _BASELINE, (
        f"Only {total} fixed-count waits remain but the baseline says {_BASELINE}.\n"
        f"Lower _BASELINE to {total} so the ground that was gained is held."
    )
