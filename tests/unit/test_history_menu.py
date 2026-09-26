"""The home menu offers the semantic history, and dispatches it."""

from __future__ import annotations

from pathlib import Path

from ster.cli import _constants, _query_launcher, _workspace_ui
from ster.plugins import semanticdiff


def test_the_home_menu_hides_semantic_history_when_the_plugin_is_inactive(monkeypatch) -> None:
    monkeypatch.setattr(semanticdiff, "is_active", lambda: False)
    labels = [label for _s, label in _workspace_ui._home_actions()]

    assert not any("History" in label for label in labels)


def test_the_active_plugin_adds_a_history_row_with_its_own_sentinel(monkeypatch) -> None:
    monkeypatch.setattr(semanticdiff, "is_active", lambda: True)
    sentinels = [s for s, _label in _workspace_ui._home_actions()]

    assert _constants._HISTORY_SENTINEL in sentinels


def test_the_history_sentinel_has_a_colour_like_every_other_row() -> None:
    assert _constants._HISTORY_SENTINEL in _constants._MENU_COLOURS


def test_the_sentinel_is_distinct_from_every_other() -> None:
    sentinels = [s for s, _label in _workspace_ui._home_actions()]

    assert len(sentinels) == len(set(sentinels))


def test_choosing_history_dispatches_rather_than_opening_the_file(monkeypatch) -> None:
    called: list[list[Path]] = []
    monkeypatch.setattr(semanticdiff, "is_active", lambda: True)
    monkeypatch.setattr(
        "ster.cli._history._run_history_interactive", lambda files: called.append(files)
    )

    handled = _query_launcher._dispatch_menu_action(_constants._HISTORY_SENTINEL, [Path("a.ttl")])

    assert handled is True
    assert called == [[Path("a.ttl")]]
