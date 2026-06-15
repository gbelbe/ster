"""Unit tests for the picker's filter ranking (pure, no Textual)."""

from __future__ import annotations

from ster.tui.picker_modal import rank_options

_OPTS = [
    ("Cat", "c"),
    ("Caterpillar", "cp"),
    ("Dog", "d"),
    ("Concat", "cc"),
    ("Bobcat", "bc"),
]


def test_empty_query_returns_everything() -> None:
    assert rank_options(_OPTS, "") == _OPTS
    assert rank_options(_OPTS, "   ") == _OPTS


def test_ranking_is_exact_then_prefix_then_fuzzy() -> None:
    ranked = [v for _, v in rank_options(_OPTS, "cat")]
    assert ranked[0] == "c"  # exact "Cat"
    assert ranked[1] == "cp"  # prefix "Caterpillar"
    # fuzzy subsequence c…a…t matches "Concat" and "Bobcat", after exact/prefix
    assert set(ranked[2:]) == {"cc", "bc"}
    assert "d" not in ranked  # "Dog" doesn't match at all


def test_prefix_match_is_case_insensitive() -> None:
    assert [v for _, v in rank_options(_OPTS, "DOG")] == ["d"]
