"""Unit tests for the complexity-ratchet core (scripts/check_complexity_ratchet.py)."""

from __future__ import annotations

import pytest

from scripts.check_complexity_ratchet import compute_complexity, find_violations

# ── find_violations (pure core) ───────────────────────────────────────────────


def test_new_function_over_threshold_is_violation() -> None:
    assert find_violations({}, {"m.py::a": 12})


def test_increase_on_existing_offender_is_violation() -> None:
    assert find_violations({"m.py::a": 18}, {"m.py::a": 20})


def test_decrease_on_offender_is_allowed() -> None:
    assert find_violations({"m.py::a": 18}, {"m.py::a": 14}) == []


def test_unchanged_offender_is_grandfathered() -> None:
    assert find_violations({"m.py::a": 24}, {"m.py::a": 24}) == []


def test_new_function_within_threshold_is_allowed() -> None:
    assert find_violations({}, {"m.py::a": 9}) == []


def test_function_crossing_threshold_is_violation() -> None:
    assert find_violations({"m.py::a": 8}, {"m.py::a": 11})


def test_empty_diff_has_no_violations() -> None:
    base = {"m.py::a": 30, "m.py::b": 5}
    assert find_violations(base, dict(base)) == []


def test_violation_message_names_the_function() -> None:
    [msg] = find_violations({}, {"m.py::a": 12})
    assert "m.py::a" in msg and "12" in msg


# ── compute_complexity (radon integration) ────────────────────────────────────


def test_compute_complexity_scores_functions(tmp_path) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("radon")
    (tmp_path / "m.py").write_text(
        "def simple():\n"
        "    return 1\n"
        "\n"
        "def branchy(x):\n"
        + "".join(f"    if x == {i}:\n        return {i}\n" for i in range(6))
        + "    return -1\n"
    )
    cc = compute_complexity(tmp_path)
    simple = next(v for k, v in cc.items() if k.endswith("::simple"))
    branchy = next(v for k, v in cc.items() if k.endswith("::branchy"))
    assert simple == 1
    assert branchy > simple
