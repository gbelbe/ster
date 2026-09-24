"""The context-file prompt has to be reached, and its answer has to arrive.

store.load(path, context=[...]) and the read-only lock in the tree both shipped
working, but nothing ever called the prompt and nothing passed its answer on:
`prompt_for_context_files` was defined, tested in isolation, and dead. The
existing tests all exercised the pieces — parsing, the prompt called directly,
a taxonomy built with context already set — so a green suite said nothing about
whether ster ever asks.

These tests assert the wire itself, which is the part that was missing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ster import cli


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    ttl = "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n<https://ex.org/{n}> a skos:ConceptScheme .\n"
    for name in ("main", "places", "products"):
        (tmp_path / f"{name}.ttl").write_text(ttl.replace("{n}", name), encoding="utf-8")
    return tmp_path


# ── the prompt is reached ─────────────────────────────────────────────────────


def test_more_than_one_file_in_the_folder_asks(folder, monkeypatch) -> None:
    asked: list[tuple] = []
    monkeypatch.setattr(
        cli._workspace_ui, "prompt_for_context_files", lambda e, f, **_: asked.append((e, f)) or []
    )

    cli.context_files_for(folder / "main.ttl", sorted(folder.glob("*.ttl")))

    assert len(asked) == 1


def test_a_folder_with_one_file_skips_the_step(tmp_path, monkeypatch) -> None:
    """Nothing to offer, so asking would be a keystroke for no reason."""
    only = tmp_path / "solo.ttl"
    only.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        cli._workspace_ui, "prompt_for_context_files", lambda e, f, **_: pytest.fail("asked anyway")
    )

    assert cli.context_files_for(only, [only]) == []


def test_the_editable_file_is_never_offered_as_its_own_context(folder, monkeypatch) -> None:
    offered: list[list[Path]] = []

    def spy(editable, found, **_):
        offered.append([f for f in found if f != editable])
        return []

    monkeypatch.setattr(cli._workspace_ui, "prompt_for_context_files", spy)
    cli.context_files_for(folder / "main.ttl", sorted(folder.glob("*.ttl")))

    assert folder / "main.ttl" not in offered[0]


# ── remembered from last time ─────────────────────────────────────────────────


def test_the_files_chosen_last_time_start_ticked(folder, monkeypatch) -> None:
    from ster.project import Project

    project = Project(root=folder)
    project.remember_context(folder / "main.ttl", [folder / "products.ttl"])
    seen: dict = {}

    def spy(editable, found, ticked=()):
        seen["ticked"] = list(ticked)
        return list(ticked)

    monkeypatch.setattr(cli._workspace_ui, "prompt_for_context_files", spy)
    cli.context_files_for(folder / "main.ttl", sorted(folder.glob("*.ttl")), project)

    assert seen["ticked"] == [folder / "products.ttl"]


def test_the_confirmed_choice_is_saved_for_next_time(folder, monkeypatch) -> None:
    from ster.project import Project

    monkeypatch.setattr("ster.project._git_root", lambda cwd: None)
    project = Project(root=folder)
    monkeypatch.setattr(
        cli._workspace_ui, "prompt_for_context_files", lambda e, f, **_: [folder / "places.ttl"]
    )
    cli.context_files_for(folder / "main.ttl", sorted(folder.glob("*.ttl")), project)

    assert Project.load(folder).remembered_context(folder / "main.ttl") == [folder / "places.ttl"]


def test_a_remembered_file_no_longer_offered_is_not_ticked(folder, monkeypatch) -> None:
    from ster.project import Project

    project = Project(root=folder)
    project.remember_context(folder / "main.ttl", [folder / "places.ttl"])
    seen: dict = {}
    monkeypatch.setattr(
        cli._workspace_ui,
        "prompt_for_context_files",
        lambda e, f, ticked=(): seen.setdefault("ticked", list(ticked)) or [],
    )
    offered = [folder / "main.ttl", folder / "products.ttl"]  # places.ttl no longer offered
    cli.context_files_for(folder / "main.ttl", offered, project)

    assert seen["ticked"] == []


# ── the answer arrives ────────────────────────────────────────────────────────


def test_the_chosen_files_reach_the_viewer(monkeypatch, tmp_path) -> None:
    """_open_viewer must hand the context on, or the choice is silently dropped."""
    seen: dict = {}
    monkeypatch.setattr(cli._viewer, "_is_interactive_terminal", lambda: True)
    monkeypatch.setattr(cli._viewer, "_prewarm_lint", lambda p: None)
    monkeypatch.setattr(cli._viewer, "_start_git_fetch", lambda gm: None)

    import ster.tui as tui

    def fake_launch(path, source=None, lang="en", open_query=False, context=None):
        seen["context"] = context
        return None

    monkeypatch.setattr(tui, "launch_file", fake_launch)
    main = tmp_path / "main.ttl"
    main.write_text("", encoding="utf-8")

    cli._viewer._open_viewer(main, lang="en", context=[tmp_path / "places.ttl"])

    assert seen["context"] == [tmp_path / "places.ttl"]


def test_the_viewer_passes_context_into_store_load() -> None:
    """The last link: OntologyApp must forward it to store.load."""
    import inspect

    from ster.tui.app import OntologyApp
    from ster.tui.app._lifecycle import _LifecycleMixin

    assert "context" in inspect.signature(OntologyApp.__init__).parameters

    source = inspect.getsource(_LifecycleMixin)
    assert "context=self._context_files" in source


def test_launch_file_accepts_context() -> None:
    import inspect

    from ster.tui import launch_file

    assert "context" in inspect.signature(launch_file).parameters


# ── the CLI flag ──────────────────────────────────────────────────────────────


def test_show_offers_a_context_files_flag() -> None:
    import inspect

    params = inspect.signature(cli.cmd_show).parameters

    assert "context_files" in params


def test_the_context_attribute_does_not_shadow_a_textual_internal() -> None:
    """`_context` is Textual's own: DOMNode calls it as `watcher_object._context()`.

    Assigning a list — or None — to it breaks every reactive watcher on the app,
    which surfaces as `TypeError: 'NoneType' object is not callable` from deep
    inside textual.reactive, nowhere near the assignment.
    """
    from textual.dom import DOMNode

    from ster.tui.app import OntologyApp

    assert hasattr(DOMNode, "_context"), "Textual no longer owns this name"
    assert "self._context " not in _source_of(OntologyApp.__init__)


def _source_of(func) -> str:
    import inspect

    return inspect.getsource(func)
