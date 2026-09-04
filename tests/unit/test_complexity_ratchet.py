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


# ── main() end-to-end (regression: the exit code must reflect violations) ────
# Every test above exercises find_violations()/compute_*() in isolation, which
# is exactly why this bug went unnoticed: main() computed `violations` but
# never checked it before printing "OK" and returning 0 — so the prek hook and
# the CI step calling this script as a subprocess never actually failed,
# regardless of what was found. Only the slow, separate SonarQube server job
# ever caught these before this test existed.


def _init_git_repo(path):  # type: ignore[no-untyped-def]
    """Init a throwaway repo and commit whatever files already exist at *path*
    (or an empty commit, if none do yet) as the base ref every caller diffs
    against."""
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t.example",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "base",
        ],
        cwd=path,
        check=True,
    )


def test_measure_at_ref_resolves_an_absolute_path_regression(tmp_path, monkeypatch) -> None:
    """``Path(worktree) / path`` silently drops ``worktree`` when *path* is
    absolute (a pathlib gotcha), so an absolute ``--path`` used to make the
    base-ref measurement read the real working tree instead of the checked-out
    ref — making base always equal head and every violation grandfathered
    away. Every test in this module uses pytest's ``tmp_path``, which is
    always absolute, so this is also what let the main() bug above hide.
    """
    from scripts.check_complexity_ratchet import _measure_at_ref

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    monkeypatch.chdir(repo)

    (repo / "m.py").write_text("def simple():\n    return 1\n")

    base_cc, _cog, _inv, _dup = _measure_at_ref("HEAD", str(repo))  # absolute path

    assert base_cc == {}  # the base commit has no m.py at all


def test_main_reports_violation_and_fails_regression(tmp_path, monkeypatch, capsys) -> None:
    """A brand-new, over-threshold function must make main() exit non-zero.

    Reproduces the bug directly: before the fix, this failed with exit code 0
    and no violation printed, even though the function scores well over 15.
    """
    from scripts.check_complexity_ratchet import main

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    monkeypatch.chdir(repo)

    bad = (
        "def bad(x):\n"
        + "".join(f"    if x == {i}:\n        return {i}\n" for i in range(20))
        + "    return -1\n"
    )
    (repo / "m.py").write_text(bad)

    exit_code = main(["--base", "HEAD", "--path", str(repo)])

    assert exit_code != 0
    out = capsys.readouterr()
    assert "m.py::bad" in (out.out + out.err)


def test_main_reports_ok_and_succeeds_when_no_violation(tmp_path, monkeypatch, capsys) -> None:
    """The counterpart: a change with no new violation must exit 0 and say OK."""
    from scripts.check_complexity_ratchet import main

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    monkeypatch.chdir(repo)

    (repo / "m.py").write_text("def simple():\n    return 1\n")

    exit_code = main(["--base", "HEAD", "--path", str(repo)])

    assert exit_code == 0
    out = capsys.readouterr()
    assert "OK" in out.out


def test_main_flags_a_function_moved_to_a_new_file_as_touched(tmp_path, monkeypatch) -> None:
    """A file move counts as touching the code — it must meet the threshold now.

    Explicit product decision: no rename-awareness. From the moment a function
    is moved (even byte-for-byte unchanged), it is treated the same as any
    other change to it and must respect the current threshold — it is not
    grandfathered just because an identically-named function existed
    somewhere else in the base ref.
    """
    from scripts.check_complexity_ratchet import main

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "old.py").write_text(
        "def helper(x):\n"
        + "".join(f"    if x == {i}:\n        return {i}\n" for i in range(20))
        + "    return -1\n"
    )
    _init_git_repo(repo)  # base commit: the complex function lives in old.py

    (repo / "old.py").unlink()
    (repo / "new.py").write_text(
        "def helper(x):\n"
        + "".join(f"    if x == {i}:\n        return {i}\n" for i in range(20))
        + "    return -1\n"
    )
    monkeypatch.chdir(repo)

    exit_code = main(["--base", "HEAD", "--path", str(repo)])

    assert exit_code != 0


# ── Duplicated string literals (SonarQube S1192) ─────────────────────────────


def test_compute_duplicate_literals_counts_repeats_in_one_file(tmp_path) -> None:
    from scripts.check_complexity_ratchet import compute_duplicate_literals

    (tmp_path / "m.py").write_text(
        'a = "repeated value"\nb = "repeated value"\nc = "repeated value"\nd = "only once"\n'
    )

    counts = compute_duplicate_literals(tmp_path)

    assert counts["m.py::'repeated value'"] == 3
    assert "m.py::'only once'" not in counts


def test_compute_duplicate_literals_ignores_short_strings(tmp_path) -> None:
    from scripts.check_complexity_ratchet import compute_duplicate_literals

    (tmp_path / "m.py").write_text('a = "hi"\nb = "hi"\nc = "hi"\n')

    counts = compute_duplicate_literals(tmp_path)

    assert counts == {}  # below the minimum length, never counted


def test_compute_duplicate_literals_excludes_docstrings(tmp_path) -> None:
    from scripts.check_complexity_ratchet import compute_duplicate_literals

    doc = "A repeated docstring line."
    (tmp_path / "m.py").write_text(
        f'"""{doc}"""\n\n\ndef f():\n    """{doc}"""\n\n\ndef g():\n    """{doc}"""\n'
    )

    counts = compute_duplicate_literals(tmp_path)

    assert counts == {}  # three occurrences, but every one is a bare docstring


def test_compute_duplicate_literals_counts_are_per_file(tmp_path) -> None:
    from scripts.check_complexity_ratchet import compute_duplicate_literals

    value = "cross-file value"
    (tmp_path / "a.py").write_text(f'x = "{value}"\ny = "{value}"\n')
    (tmp_path / "b.py").write_text(f'z = "{value}"\n')

    counts = compute_duplicate_literals(tmp_path)

    assert counts[f"a.py::{value!r}"] == 2
    assert f"b.py::{value!r}" not in counts  # one occurrence in its own file


def test_main_flags_a_newly_duplicated_literal(tmp_path, monkeypatch) -> None:
    from scripts.check_complexity_ratchet import main

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    monkeypatch.chdir(repo)

    (repo / "m.py").write_text(
        'a = "a duplicated value"\nb = "a duplicated value"\nc = "a duplicated value"\n'
    )

    exit_code = main(["--base", "HEAD", "--path", str(repo)])

    assert exit_code != 0


def test_main_grandfathers_a_pre_existing_duplicated_literal(tmp_path, monkeypatch) -> None:
    from scripts.check_complexity_ratchet import main

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "m.py").write_text(
        'a = "already duplicated"\nb = "already duplicated"\nc = "already duplicated"\n'
    )
    _init_git_repo(repo)
    monkeypatch.chdir(repo)

    exit_code = main(["--base", "HEAD", "--path", str(repo)])

    assert exit_code == 0


def test_main_flags_a_duplicated_literal_moved_to_a_new_file_as_touched(
    tmp_path, monkeypatch
) -> None:
    """Same file-move scenario as the complexity ratchet's own touched-by-move test."""
    from scripts.check_complexity_ratchet import main

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "old.py").write_text(
        'a = "moved duplicated value"\nb = "moved duplicated value"\nc = "moved duplicated value"\n'
    )
    _init_git_repo(repo)

    (repo / "old.py").unlink()
    (repo / "new.py").write_text(
        'a = "moved duplicated value"\nb = "moved duplicated value"\nc = "moved duplicated value"\n'
    )
    monkeypatch.chdir(repo)

    exit_code = main(["--base", "HEAD", "--path", str(repo)])

    assert exit_code != 0
