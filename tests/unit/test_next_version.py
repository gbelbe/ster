"""The next version, read out of the commits that earned it.

Releases stop being a thing someone remembers to do. Conventional Commits
already say what each change was, so the version follows from the log rather
than from a hand-edited number that drifts from the tags — as ours had, at
0.11.0 in pyproject against v0.10.0 in git.

The rules: a breaking change moves the major, a feature the minor, a fix the
patch, and housekeeping moves nothing at all, so a docs-only merge cuts no tag.
While the major is still 0 a breaking change moves the *minor*, because nothing
should declare this project 1.0 by accident.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from next_version import bump_level, next_version  # noqa: E402


def test_a_fix_moves_the_patch() -> None:
    assert bump_level(["fix(map): stop the drill-down collapsing"]) == "patch"
    assert next_version("0.10.0", "patch") == "0.10.1"


def test_a_feature_moves_the_minor_and_zeroes_the_patch() -> None:
    assert bump_level(["feat(map): a dynamic facet menu"]) == "minor"
    assert next_version("0.10.4", "minor") == "0.11.0"


def test_the_highest_level_present_wins() -> None:
    """One feature among many fixes still makes it a minor release."""
    assert bump_level(["fix(a): one", "feat(b): two", "fix(c): three"]) == "minor"


def test_a_breaking_change_moves_the_minor_while_the_major_is_zero() -> None:
    """0.x is allowed to break; it must not silently become 1.0."""
    assert bump_level(["refactor!: remove LLM support"]) == "major"
    assert next_version("0.11.0", "major") == "0.12.0"


def test_a_breaking_change_moves_the_major_once_past_one() -> None:
    assert next_version("1.4.2", "major") == "2.0.0"


def test_breaking_change_in_the_body_counts_even_without_the_bang() -> None:
    message = "feat(api): new locate contract\n\nBREAKING CHANGE: uris replaces query."

    assert bump_level([message]) == "major"


def test_housekeeping_alone_releases_nothing() -> None:
    """A docs or CI merge must not cut a tag."""
    assert bump_level(["docs: fix a typo", "chore(deps): bump ruff", "ci: cache uv"]) is None


def test_a_message_that_is_not_conventional_is_ignored() -> None:
    assert bump_level(["merged upstream", "WIP"]) is None


def test_an_unconventional_message_does_not_hide_a_real_one() -> None:
    assert bump_level(["WIP", "feat(x): something real"]) == "minor"


def test_a_squash_merge_subject_still_parses() -> None:
    """GitHub appends the PR number; the type is still the first token."""
    subject = "fix(map): work on a file with no hierarchy, and stop clustering blanking it (#146)"

    assert bump_level([subject]) == "patch"


def test_the_first_release_of_an_untagged_repository() -> None:
    assert next_version(None, "patch") == "0.1.0"
    assert next_version(None, "minor") == "0.1.0"


@pytest.mark.parametrize(
    ("tag", "level", "expected"),
    [("v0.10.0", "patch", "0.10.1"), ("0.10.0", "minor", "0.11.0")],
)
def test_the_v_prefix_is_accepted_and_not_echoed(tag: str, level: str, expected: str) -> None:
    """Tags carry a v; the version itself never does."""
    assert next_version(tag, level) == expected
