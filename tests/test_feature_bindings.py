"""Guard: every Gherkin feature file must be bound to a test.

A ``.feature`` under ``tests/features/`` that no ``scenarios()`` / ``scenario()``
call references runs no tests — a silent gap that lets a spec be "written" yet
never executed. This module fails CI in that case, and unit-tests the small
parser that detects the bindings.
"""

from __future__ import annotations

import re
from pathlib import Path

# Matches the path argument of scenarios("../features/<...>.feature") /
# scenario("../features/<...>.feature", "..."), capturing the part after
# "features/" so it lines up with paths relative to tests/features/.
_FEATURE_REF_RE = re.compile(r"features/([A-Za-z0-9_./-]+\.feature)")


def _referenced_features(text: str) -> set[str]:
    """Return feature paths (relative to ``tests/features/``) referenced in *text*."""
    return set(_FEATURE_REF_RE.findall(text))


def _all_feature_files(features_dir: Path) -> set[str]:
    """Return every ``.feature`` under *features_dir*, relative to it."""
    return {p.relative_to(features_dir).as_posix() for p in features_dir.rglob("*.feature")}


# ── parser unit tests ─────────────────────────────────────────────────────────


def test_referenced_features_extracts_path() -> None:
    assert _referenced_features('scenarios("../features/ci/x.feature")') == {"ci/x.feature"}


def test_referenced_features_handles_scenario_call() -> None:
    assert _referenced_features('scenario("../features/ui/y.feature", "a name")') == {
        "ui/y.feature"
    }


def test_referenced_features_none() -> None:
    assert _referenced_features("no features referenced here") == set()


def test_referenced_features_multiple() -> None:
    text = 'a "../features/ci/a.feature" then "../features/ui/b.feature"'
    assert _referenced_features(text) == {"ci/a.feature", "ui/b.feature"}


# ── the gate ──────────────────────────────────────────────────────────────────


def test_every_feature_file_is_bound() -> None:
    tests_dir = Path(__file__).resolve().parent
    features_dir = tests_dir / "features"

    actual = _all_feature_files(features_dir)
    referenced: set[str] = set()
    for py in tests_dir.rglob("*.py"):
        referenced |= _referenced_features(py.read_text(encoding="utf-8"))

    orphans = actual - referenced
    assert not orphans, (
        "Feature files with no scenarios()/scenario() binding (they run no tests): "
        f"{sorted(orphans)}"
    )
