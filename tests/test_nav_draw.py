"""Smoke tests for all TaxonomyViewer _draw_* / _render_* methods.

Uses FakeScreen instead of a real curses window so the tests run without a
terminal.  Each test just verifies the method doesn't raise; correctness is
not checked here (that belongs in visual / integration tests).
"""

from __future__ import annotations

import curses
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from ster.handles import assign_handles
from ster.model import (
    Concept,
    ConceptScheme,
    Definition,
    Label,
    Taxonomy,
)
from ster.nav import TaxonomyViewer
from ster.nav.state import (
    AiInstallState,
    AiSetupState,
    BatchConceptDraft,
    BatchCreateState,
    ClassToIndividualState,
    ConfirmDeleteState,
    CreateState,
    EditState,
    IndividualToClassState,
    LangPickState,
    MapConceptPickState,
    MapSchemePickState,
    MovePickState,
    OntologySetupState,
    QueryState,
    SchemeCreateState,
    WelcomeState,
)

BASE = "https://example.org/test/"

# ── FakeScreen ────────────────────────────────────────────────────────────────


class FakeScreen:
    """Minimal stub that satisfies curses.window calls without a terminal."""

    ROWS = 40
    COLS = 120

    def getmaxyx(self) -> tuple[int, int]:
        return self.ROWS, self.COLS

    def erase(self) -> None:
        pass

    def refresh(self) -> None:
        pass

    def getch(self) -> int:
        return -1

    def keypad(self, flag: bool) -> None:  # noqa: FBT001
        pass

    def addstr(self, *args: Any, **kwargs: Any) -> None:
        pass

    def addch(self, *args: Any, **kwargs: Any) -> None:
        pass

    def chgat(self, *args: Any, **kwargs: Any) -> None:
        pass

    def move(self, y: int, x: int) -> None:
        pass

    def clrtoeol(self) -> None:
        pass


# ── session-level curses patch ────────────────────────────────────────────────


@pytest.fixture(autouse=True, scope="module")
def _patch_curses_colors() -> Any:
    """Patch curses functions that require an active curses session."""
    with (
        patch("curses.color_pair", return_value=0),
        patch.object(curses, "ACS_VLINE", ord("|"), create=True),
        patch.object(curses, "ACS_HLINE", ord("-"), create=True),
    ):
        yield


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def simple_tax() -> Taxonomy:
    t = Taxonomy()
    scheme = ConceptScheme(
        uri=BASE + "Scheme",
        labels=[Label(lang="en", value="Test Taxonomy")],
        top_concepts=[BASE + "Top"],
        base_uri=BASE,
    )
    top = Concept(
        uri=BASE + "Top",
        labels=[Label(lang="en", value="Top Concept")],
        definitions=[Definition(lang="en", value="The root.")],
        narrower=[BASE + "Child"],
        top_concept_of=BASE + "Scheme",
    )
    child = Concept(
        uri=BASE + "Child",
        labels=[Label(lang="en", value="Child")],
        broader=[BASE + "Top"],
    )
    t.schemes[scheme.uri] = scheme
    for c in (top, child):
        t.concepts[c.uri] = c
    assign_handles(t)
    return t


@pytest.fixture
def viewer(simple_tax: Taxonomy, tmp_path: Path) -> TaxonomyViewer:
    f = tmp_path / "vocab.ttl"
    f.write_text("")
    with (
        patch("ster.nav.viewer._load_prefs", return_value={"help_seen": True}),
        patch("ster.nav.viewer._load_lang_pref", return_value=None),
    ):
        v = TaxonomyViewer(simple_tax, f, lang="en")
    return v


@pytest.fixture
def scr() -> FakeScreen:
    return FakeScreen()


def _rc(scr: FakeScreen) -> tuple[int, int]:
    return scr.ROWS, scr.COLS


# ── welcome ───────────────────────────────────────────────────────────────────


def test_draw_welcome(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = WelcomeState()
    viewer._draw_welcome(scr, *_rc(scr))  # type: ignore[arg-type]


# ── tree ──────────────────────────────────────────────────────────────────────


def test_draw_tree(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._draw_tree(scr, *_rc(scr))  # type: ignore[arg-type]


def test_draw_tree_with_status(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._status = "Saved"
    viewer._draw_tree(scr, *_rc(scr))  # type: ignore[arg-type]


def test_draw_tree_with_search(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._search_active = True
    viewer._search_query = "top"
    viewer._search_matches = [0]
    viewer._draw_tree(scr, *_rc(scr))  # type: ignore[arg-type]


def test_draw_search_bar_empty(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._search_query = ""
    viewer._draw_search_bar(scr, scr.ROWS - 1, 0, scr.COLS)  # type: ignore[arg-type]


def test_draw_search_bar_no_match(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._search_query = "xyz"
    viewer._search_matches = []
    viewer._draw_search_bar(scr, scr.ROWS - 1, 0, scr.COLS)  # type: ignore[arg-type]


def test_draw_search_bar_with_matches(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._search_query = "top"
    viewer._search_matches = [0]
    viewer._draw_search_bar(scr, scr.ROWS - 1, 0, scr.COLS)  # type: ignore[arg-type]


def test_draw_tree_preview(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._draw_tree_preview(scr, *_rc(scr))  # type: ignore[arg-type]


def test_render_tree_col(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._render_tree_col(scr, scr.ROWS, 0, scr.COLS, 0, highlight_uri=None)  # type: ignore[arg-type]


# ── detail / split ────────────────────────────────────────────────────────────


def test_draw_split_narrow(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    scr.COLS = 80
    viewer._draw_split(scr, scr.ROWS, scr.COLS)  # type: ignore[arg-type]


def test_draw_split_wide(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._draw_split(scr, *_rc(scr))  # type: ignore[arg-type]


def test_render_detail_col(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._render_detail_col(scr, scr.ROWS, 0, scr.COLS)  # type: ignore[arg-type]


def test_draw_edit_bar(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    from ster.nav.logic import DetailField

    field = DetailField("pref_label", "Pref Label", "Top Concept", editable=True)
    viewer._state = EditState(buffer="Top Concept", pos=3, field=field)
    viewer._draw_edit_bar(scr, *_rc(scr))  # type: ignore[arg-type]


# ── create ────────────────────────────────────────────────────────────────────


def test_draw_create_form(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = CreateState(parent_uri=BASE + "Scheme", step="form")
    viewer._draw_create(scr, *_rc(scr))  # type: ignore[arg-type]


def test_draw_create_choose(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = CreateState(parent_uri=BASE + "Scheme", step="choose")
    viewer._draw_create(scr, *_rc(scr))  # type: ignore[arg-type]


def test_draw_create_context_review(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = CreateState(
        parent_uri=BASE + "Scheme",
        step="context_review",
        context_name="Test",
        context_def_buffer="A description.",
    )
    viewer._draw_create(scr, *_rc(scr))  # type: ignore[arg-type]


def test_draw_create_prompt_review(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = CreateState(
        parent_uri=BASE + "Scheme",
        step="prompt_review",
        prompt_buffer="Suggest concepts for...",
    )
    viewer._draw_create(scr, *_rc(scr))  # type: ignore[arg-type]


def test_draw_create_ai_pick(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = CreateState(
        parent_uri=BASE + "Scheme",
        step="ai_pick",
        ai_candidates=["Alpha", "Beta"],
        ai_checked=[True, False],
    )
    viewer._draw_create(scr, *_rc(scr))  # type: ignore[arg-type]


# ── scheme create ─────────────────────────────────────────────────────────────


def test_draw_scheme_create(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = SchemeCreateState()
    viewer._draw_scheme_create(scr, *_rc(scr))  # type: ignore[arg-type]


# ── ontology setup ────────────────────────────────────────────────────────────


def test_draw_ontology_setup(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = OntologySetupState()
    viewer._draw_ontology_setup(scr, *_rc(scr))  # type: ignore[arg-type]


# ── confirm delete ────────────────────────────────────────────────────────────


def test_draw_confirm(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = ConfirmDeleteState(uri=BASE + "Child")
    viewer._draw_confirm(scr, *_rc(scr))  # type: ignore[arg-type]


def test_render_confirm_col(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = ConfirmDeleteState(uri=BASE + "Child")
    viewer._render_confirm_col(scr, scr.ROWS, 0, scr.COLS)  # type: ignore[arg-type]


# ── class ↔ individual conversions ────────────────────────────────────────────


def test_draw_class_to_individual_confirm(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = ClassToIndividualState(
        class_uri=BASE + "Top",
        affected_uris=[BASE + "Child"],
        parent_uris=[],
    )
    viewer._draw_class_to_individual_confirm(scr, *_rc(scr))  # type: ignore[arg-type]


def test_draw_individual_to_class_confirm(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = IndividualToClassState(individual_uri=BASE + "Child")
    viewer._draw_individual_to_class_confirm(scr, *_rc(scr))  # type: ignore[arg-type]


# ── move / map ────────────────────────────────────────────────────────────────


def test_draw_move(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = MovePickState(
        source_uri=BASE + "Child",
        candidates=[(BASE + "Top", "Top Concept")],
    )
    viewer._draw_move(scr, *_rc(scr))  # type: ignore[arg-type]


def test_draw_map_scheme_pick(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = MapSchemePickState(
        source_uri=BASE + "Child",
        map_type="exactMatch",
        candidates=[(BASE + "Scheme", "Test Taxonomy")],
    )
    viewer._draw_map_scheme_pick(scr, *_rc(scr))  # type: ignore[arg-type]


def test_draw_map_concept_pick(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = MapConceptPickState(
        source_uri=BASE + "Child",
        map_type="exactMatch",
        target_scheme=BASE + "Scheme",
        candidates=[(BASE + "Top", "Top Concept")],
    )
    viewer._draw_map_concept_pick(scr, *_rc(scr))  # type: ignore[arg-type]


# ── lang pick ─────────────────────────────────────────────────────────────────


def test_draw_lang_pick(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = LangPickState(options=["en", "fr", "de"])
    viewer._draw_lang_pick(scr, *_rc(scr))  # type: ignore[arg-type]


# ── AI install / setup ────────────────────────────────────────────────────────


def test_draw_ai_install_pending(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = AiInstallState(pending_action="suggest")
    viewer._draw_ai_install(scr, *_rc(scr))  # type: ignore[arg-type]


def test_draw_ai_install_installing(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = AiInstallState(installing=True, lines=["Collecting llm..."])
    viewer._draw_ai_install(scr, *_rc(scr))  # type: ignore[arg-type]


def test_draw_ai_install_done(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = AiInstallState(done=True)
    viewer._draw_ai_install(scr, *_rc(scr))  # type: ignore[arg-type]


def test_draw_ai_install_error(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = AiInstallState(error="pip failed")
    viewer._draw_ai_install(scr, *_rc(scr))  # type: ignore[arg-type]


def test_draw_ai_setup_mode(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = AiSetupState(step="mode")
    viewer._draw_ai_setup(scr, *_rc(scr))  # type: ignore[arg-type]


def test_draw_ai_setup_provider(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = AiSetupState(
        step="provider",
        mode="online",
        online_providers=[("openai", "OpenAI", [("gpt-4o", "GPT-4o")])],
    )
    viewer._draw_ai_setup(scr, *_rc(scr))  # type: ignore[arg-type]


def test_draw_ai_setup_model(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = AiSetupState(
        step="model",
        mode="online",
        selected_provider_id="openai",
        online_providers=[("openai", "OpenAI", [("gpt-4o", "GPT-4o")])],
    )
    viewer._draw_ai_setup(scr, *_rc(scr))  # type: ignore[arg-type]


def test_draw_ai_setup_done(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = AiSetupState(step="done", selected_model_id="gpt-4o")
    viewer._draw_ai_setup(scr, *_rc(scr))  # type: ignore[arg-type]


# ── batch create wizard ───────────────────────────────────────────────────────


def _make_batch_state(step: str) -> BatchCreateState:
    draft = BatchConceptDraft(
        name="Alpha",
        pref_label="Alpha",
        alt_labels=["A", "B"],
        alt_checked=[True, False],
        definition="A concept.",
    )
    return BatchCreateState(
        parent_uri=BASE + "Scheme",
        drafts=[draft],
        current=0,
        step=step,
        label_buffer="Alpha",
    )


def test_draw_batch_label(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = _make_batch_state("label")
    viewer._draw_batch(scr, *_rc(scr))  # type: ignore[arg-type]


def test_draw_batch_definition(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = _make_batch_state("definition")
    viewer._draw_batch(scr, *_rc(scr))  # type: ignore[arg-type]


def test_draw_batch_alt_prompt_review(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = _make_batch_state("alt_prompt_review")
    viewer._draw_batch(scr, *_rc(scr))  # type: ignore[arg-type]


def test_draw_batch_alt_labels(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = _make_batch_state("alt_labels")
    viewer._draw_batch(scr, *_rc(scr))  # type: ignore[arg-type]


def test_draw_batch_confirm(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = _make_batch_state("confirm")
    viewer._draw_batch(scr, *_rc(scr))  # type: ignore[arg-type]


def test_draw_batch_recap(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = _make_batch_state("recap")
    viewer._draw_batch(scr, *_rc(scr))  # type: ignore[arg-type]


# ── query ─────────────────────────────────────────────────────────────────────


def test_draw_query_empty(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = QueryState(file_paths=[Path("/tmp/test.ttl")])
    viewer._draw_query(scr, *_rc(scr))  # type: ignore[arg-type]


def test_draw_query_with_results(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = QueryState(
        file_paths=[Path("/tmp/test.ttl")],
        query_buffer="SELECT * WHERE { ?s ?p ?o }",
        columns=["s", "p", "o"],
        rows=[["a", "b", "c"]],
        panel="results",
    )
    viewer._draw_query(scr, *_rc(scr))  # type: ignore[arg-type]


def test_draw_query_presets(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = QueryState(
        file_paths=[Path("/tmp/test.ttl")],
        show_presets=True,
    )
    viewer._draw_query(scr, *_rc(scr))  # type: ignore[arg-type]


def test_draw_query_kw_popup(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    # SEL prefix triggers keyword autocomplete
    viewer._state = QueryState(
        file_paths=[Path("/tmp/test.ttl")],
        query_buffer="SEL",
        query_pos=3,
        panel="editor",
    )
    viewer._draw_query(scr, *_rc(scr))  # type: ignore[arg-type]


def test_draw_query_ai_ask(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = QueryState(
        file_paths=[Path("/tmp/test.ttl")],
        ai_step="ask",
        ai_question="show all concepts",
    )
    viewer._draw_query(scr, *_rc(scr))  # type: ignore[arg-type]


def test_draw_query_ai_prompt_review(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = QueryState(
        file_paths=[Path("/tmp/test.ttl")],
        ai_step="prompt_review",
        ai_prompt_buffer="Generate SPARQL for...",
    )
    viewer._draw_query(scr, *_rc(scr))  # type: ignore[arg-type]


def test_draw_query_ac(viewer: TaxonomyViewer, scr: FakeScreen) -> None:
    viewer._state = QueryState(
        file_paths=[Path("/tmp/test.ttl")],
        query_buffer="@",
        query_pos=1,
        ac_active=True,
        panel="editor",
    )
    viewer._draw_query(scr, *_rc(scr))  # type: ignore[arg-type]
