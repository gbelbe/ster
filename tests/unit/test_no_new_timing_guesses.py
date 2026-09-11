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
_BASELINE = 67

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


def test_the_baseline_is_not_stale() -> None:
    """A ratchet nobody tightens is a ceiling. When conversions bring the real
    count below the baseline, this fails and asks for the baseline to follow —
    otherwise the budget silently refills and new guesses slip in."""
    total = sum(_offenders().values())

    assert total >= _BASELINE, (
        f"Only {total} fixed-count waits remain but the baseline says {_BASELINE}.\n"
        f"Lower _BASELINE to {total} so the ground that was gained is held."
    )
