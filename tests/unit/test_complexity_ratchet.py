"""Unit tests for the complexity-ratchet core (scripts/check_complexity_ratchet.py)."""

from __future__ import annotations

import pytest

from scripts.check_complexity_ratchet import compute_complexity, find_violations

# ── find_violations (pure core) ───────────────────────────────────────────────


def test_new_function_over_threshold_is_violation() -> None:
    assert find_violations({}, {"m.py::a": 16})


def test_increase_on_existing_offender_is_violation() -> None:
    assert find_violations({"m.py::a": 18}, {"m.py::a": 20})


def test_decrease_on_offender_is_allowed() -> None:
    assert find_violations({"m.py::a": 18}, {"m.py::a": 14}) == []


def test_unchanged_offender_is_grandfathered() -> None:
    assert find_violations({"m.py::a": 24}, {"m.py::a": 24}) == []


def test_new_function_within_threshold_is_allowed() -> None:
    assert find_violations({}, {"m.py::a": 15}) == []


def test_function_crossing_threshold_is_violation() -> None:
    assert find_violations({"m.py::a": 14}, {"m.py::a": 16})


def test_empty_diff_has_no_violations() -> None:
    base = {"m.py::a": 30, "m.py::b": 5}
    assert find_violations(base, dict(base)) == []


def test_violation_message_names_the_function() -> None:
    [msg] = find_violations({}, {"m.py::a": 16})
    assert "m.py::a" in msg and "16" in msg


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


# ── Cognitive complexity (S3776) ──────────────────────────────────────────────
# Cyclomatic complexity does not charge for nesting, so a function radon calls
# simple can still be over SonarQube's limit. These two rules cost this project
# three round-trips through CI before they were checked locally.


def test_cognitive_complexity_charges_for_nesting(tmp_path) -> None:
    """The same four conditions, flat and nested — the metric must tell them apart."""
    from scripts.check_complexity_ratchet import compute_cognitive

    (tmp_path / "m.py").write_text(
        "def flat(a, b, c, d):\n"
        "    if a: return 1\n"
        "    if b: return 2\n"
        "    if c: return 3\n"
        "    if d: return 4\n"
        "    return 0\n"
        "def nested(a, b, c, d):\n"
        "    if a:\n"
        "        if b:\n"
        "            if c:\n"
        "                if d:\n"
        "                    return 1\n"
        "    return 0\n"
    )

    scores = compute_cognitive(tmp_path)

    assert scores["m.py::nested"] > scores["m.py::flat"]


def test_a_function_is_charged_for_the_one_declared_inside_it(tmp_path) -> None:
    """SonarQube scored _register_locate 17 for the endpoint declared inside it.

    A registrar whose own body is a single def would otherwise look free, and the
    branching that actually got flagged would go unmeasured.
    """
    from scripts.check_complexity_ratchet import compute_cognitive

    (tmp_path / "m.py").write_text(
        "def register():\n    def handler(xs):\n        for x in xs:\n"
        "            if x:\n                return x\n        return None\n    return handler\n"
    )

    scores = compute_cognitive(tmp_path)

    assert scores["m.py::register"] >= scores["m.py::register.handler"] > 0


# ── Invariant return (S3516) ──────────────────────────────────────────────────


def test_returning_the_same_mutated_name_twice_is_reported(tmp_path) -> None:
    """place_ancestors, exactly: a list built up and handed back from two places."""
    from scripts.check_complexity_ratchet import compute_invariant_returns

    (tmp_path / "m.py").write_text(
        "def walk(xs):\n"
        "    chain = []\n"
        "    for x in xs:\n"
        "        if x is None:\n"
        "            return chain\n"
        "        chain.append(x)\n"
        "    return chain\n"
    )

    assert compute_invariant_returns(tmp_path) == {"m.py::walk": "chain"}


def test_a_rebound_name_really_does_return_different_values(tmp_path) -> None:
    """place_level has the same shape but reassigns its counter — not a finding."""
    from scripts.check_complexity_ratchet import compute_invariant_returns

    (tmp_path / "m.py").write_text(
        "def depth_of(xs):\n"
        "    depth = 0\n"
        "    for x in xs:\n"
        "        if x is None:\n"
        "            return depth\n"
        "        depth = depth + 1\n"
        "    return depth\n"
    )

    assert compute_invariant_returns(tmp_path) == {}


def test_returns_of_different_things_are_not_a_finding(tmp_path) -> None:
    from scripts.check_complexity_ratchet import compute_invariant_returns

    (tmp_path / "m.py").write_text(
        "def f(a):\n    out = []\n    if a:\n        return a\n    return out\n"
    )

    assert compute_invariant_returns(tmp_path) == {}


def test_one_return_is_never_invariant(tmp_path) -> None:
    """The rule is about two paths that look different and are not."""
    from scripts.check_complexity_ratchet import compute_invariant_returns

    (tmp_path / "m.py").write_text(
        "def f(xs):\n    out = []\n    for x in xs:\n        out.append(x)\n    return out\n"
    )

    assert compute_invariant_returns(tmp_path) == {}


def test_a_nested_function_does_not_steal_its_owners_returns(tmp_path) -> None:
    from scripts.check_complexity_ratchet import compute_invariant_returns

    (tmp_path / "m.py").write_text(
        "def outer(a):\n"
        "    def inner():\n"
        "        acc = []\n"
        "        if a:\n"
        "            return acc\n"
        "        return acc\n"
        "    return inner\n"
    )

    assert compute_invariant_returns(tmp_path) == {"m.py::outer.inner": "acc"}


def test_the_metric_label_appears_in_the_message() -> None:
    """One report carries both metrics, so each violation must say which it is."""
    message = find_violations({}, {"m.py::a": 17}, metric="cognitive complexity")[0]

    assert "cognitive complexity" in message
