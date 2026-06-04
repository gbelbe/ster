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


# ── refactor-on-touch ceiling (parse_changed_lines / touched_functions) ────────


def test_parse_changed_lines_multiline_hunk() -> None:
    from scripts.check_complexity_ratchet import parse_changed_lines

    diff = (
        "diff --git a/ster/x.py b/ster/x.py\n"
        "--- a/ster/x.py\n"
        "+++ b/ster/x.py\n"
        "@@ -10,0 +11,3 @@ def f():\n"
        "+a\n+b\n+c\n"
    )
    assert parse_changed_lines(diff) == {"ster/x.py": {11, 12, 13}}


def test_parse_changed_lines_single_line_hunk() -> None:
    from scripts.check_complexity_ratchet import parse_changed_lines

    diff = "+++ b/ster/y.py\n@@ -5 +6 @@\n+x\n"
    assert parse_changed_lines(diff) == {"ster/y.py": {6}}


def test_parse_changed_lines_pure_deletion_adds_nothing() -> None:
    from scripts.check_complexity_ratchet import parse_changed_lines

    diff = "+++ b/ster/z.py\n@@ -5,2 +4,0 @@\n"
    assert parse_changed_lines(diff) == {}


def test_touched_functions_overlap() -> None:
    from scripts.check_complexity_ratchet import touched_functions

    changed = {"ster/nav/v.py": {15}}
    ranges = {"nav/v.py::big": (10, 20), "nav/v.py::other": (30, 40)}
    assert touched_functions(changed, ranges, "ster") == {"nav/v.py::big"}


def test_touched_functions_no_overlap() -> None:
    from scripts.check_complexity_ratchet import touched_functions

    changed = {"ster/nav/v.py": {99}}
    ranges = {"nav/v.py::big": (10, 20)}
    assert touched_functions(changed, ranges, "ster") == set()


# ── touch_ceiling_violations (the no-dodge rule) ──────────────────────────────


def test_touching_god_function_without_reducing_is_violation() -> None:
    from scripts.check_complexity_ratchet import touch_ceiling_violations

    # touched, still above ceiling, complexity flat → must refactor down
    assert touch_ceiling_violations({"a::f"}, {"a::f": 127}, {"a::f": 127}, 25)


def test_touching_god_function_and_reducing_is_allowed() -> None:
    from scripts.check_complexity_ratchet import touch_ceiling_violations

    assert touch_ceiling_violations({"a::f"}, {"a::f": 127}, {"a::f": 120}, 25) == []


def test_touched_function_below_ceiling_is_allowed() -> None:
    from scripts.check_complexity_ratchet import touch_ceiling_violations

    assert touch_ceiling_violations({"a::f"}, {"a::f": 20}, {"a::f": 20}, 25) == []


def test_untouched_god_function_is_allowed() -> None:
    from scripts.check_complexity_ratchet import touch_ceiling_violations

    assert touch_ceiling_violations(set(), {"a::f": 127}, {"a::f": 127}, 25) == []
