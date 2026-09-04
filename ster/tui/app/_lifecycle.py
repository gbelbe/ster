"""App startup/shutdown lifecycle: __init__ state setup, progressive taxonomy loading (background workers), tree/browser initialization staging, and mount/unmount hooks."""

from __future__ import annotations

import threading
from functools import partial
from pathlib import Path
from typing import Final

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Footer, Header, Static, Tree
from textual.widgets.tree import TreeNode

from ster.metadata_coverage import MetaProp
from ster.model import Taxonomy
from ster.nav.logic import DetailField

from .. import data, detail
from ..context_menu import ContextMenu
from ..detail_view import DetailView
from ..theme import STER_THEME
from ._constants import (
    _DETAIL_SELECTOR,
    _LARGE_TAXONOMY_THRESHOLD,
    _LOADING_SELECTOR,
    _ONTOLOGY_TREE_SELECTOR,
    _PROPERTY_TREE_SELECTOR,
    _TREE_SELECTOR,
)
from ._helpers import _start_context_server
from ._state import _AppState
from ._tree_widget import OntologyTree

_LIT_PREPARING: Final = "Preparing"


class _LifecycleMixin(_AppState):
    """Mixin: app startup/shutdown lifecycle: __init__ state setup, progressive taxonomy loading (background workers), tree/browser initialization staging, and mount/unmount hooks."""

    def __init__(
        self,
        taxonomy: Taxonomy | None,
        source: str = "ontology",
        lang: str = "en",
        path: Path | None = None,
        open_query: bool = False,
        progressive_startup: bool = False,
    ) -> None:
        super().__init__()
        self._open_query_on_start = open_query
        self._progressive_startup = progressive_startup or taxonomy is None
        self._loading = self._progressive_startup
        self._loading_from_file = taxonomy is None
        self._loading_spinner_frame = 0
        self._loading_spinner_timer: Timer | None = None
        self._context_server_started = False
        self._browser_mounted = False
        self._loaded_successfully = taxonomy is not None
        self._browser_ready = False  # overview shown + first lint computed + tree recoloured
        self.register_theme(STER_THEME)  # available alongside every built-in theme
        from ster.nav.prefs import _load_prefs

        self.theme = _load_prefs().get("theme") or "solarized-light"  # saved pref, else default
        self.tax = taxonomy or Taxonomy()
        if path is not None:
            from ster.nav.prefs import _load_lang_pref

            lang = _load_lang_pref(path) or lang  # restore the saved display language
        self.lang = lang
        self.source = source
        self._path = path
        self.configured_langs = self._load_configured_langs(path, lang)
        self.metadata_props = self._load_metadata_props()  # ontology-metadata catalog
        self.entity_metadata_props = self._load_entity_metadata_props()  # entity-metadata catalog
        self._configure_taxonomy_state(taxonomy, path, lang)
        self._uri_nodes: dict[str, TreeNode] = {}
        self._deferred_individuals: dict[int, tuple[TreeNode, list[str]]] = {}
        self._deferred_tree_nodes: dict[int, tuple[TreeNode, str, bool]] = {}
        self._individuals_by_class: dict[str, list[str]] = {}
        self._untyped_individuals: list[str] = []
        self._detail_text = ""  # last-rendered detail markup (handy for tests)
        self._detail_uri: str | None = None  # entity currently shown in the detail pane
        self._active_main_tree_id = "tree"  # last-focused main pane: "tree" (unified) or "ont-tree"
        self._detail_source_pid = (
            "tree"  # the pane Tab/→ crossed from; Escape in detail returns here
        )
        self._detail_source_uri: str | None = None  # the tree item Tab in the detail toggles to
        self._entered_pid: str | None = (
            None  # the pane currently entered (item layer); None = panel layer
        )
        self._folded_panels: set[str] = set()  # left panes folded to their title bar
        self._activity_cache: dict | None = None  # lazily-computed git activity (per session)
        self._activity_computed = False
        # Semanticlint result (counts, issues) + a uri→worst-severity index for O(1)
        # per-entity lookups (icon colours, detail annotations). Recomputed in the
        # background after edits when the plugin is active.
        self._lint_cache: tuple[dict, list] | None = None
        self._lint_computed = False
        self._lint_index: dict[str, str] = {}
        self._lint_issues: dict[str, list[dict]] = {}  # uri → its issues (drives hover tooltip)
        self._lint_icons_on = False  # cached (plugin + 'icons' feature on)
        self._lint_detail_on = False  # cached (plugin + 'detail' feature on)
        self._lint_quality_on = False  # cached (plugin + 'quality_block' feature on)
        self._overview_quality_on = True  # overview Quality & Coverage group visible
        # The value row whose Edit/Delete submenu is open (set while it is shown).
        self._row_menu_field: DetailField | None = None
        self._row_menu_delete: DetailField | None = None
        self._row_menu_goto: str | None = None  # nav target for the row menu's "Go to" item
        self._row_menu_origin: Widget | None = None  # row to refocus after the submenu
        # Persist off the UI thread (the slow part of an edit); the lock serialises writes
        # and each save writes the latest authority, so the disk converges to it.
        self._save_lock = threading.Lock()
        self._save_dirty = False
        self._lint_timer: Timer | None = None  # debounce handle for the heavy re-lint
        self._activities: dict[str, str] = {}  # running background jobs → label (Saving/Checking)
        self._busy_timer: Timer | None = None  # spinner animation handle
        self._spinner_frame = 0
        # The detail row (by field key) that was being edited, so focus lands back on it
        # after a mutation rebuilds the pane — not on the first row / tree.
        self._pending_focus_key: str | None = None
        # A scan-on-open fix ran under the Problems modal; rebuild the panes on close.
        self._dirty_after_fix = False

    def _configure_taxonomy_state(
        self, taxonomy: Taxonomy | None, path: Path | None, lang: str
    ) -> None:
        """Set load, persistence, search and navigation state for the initial taxonomy."""
        self._navigation_index_built = taxonomy is not None and not self.tax.owl_individuals
        self._service = self._make_service(self.tax, path) if taxonomy is not None else None
        self._defer_search_rows = (
            taxonomy is not None and self._entity_count(taxonomy) > _LARGE_TAXONOMY_THRESHOLD
        )
        if taxonomy is None or self._defer_search_rows:
            self.search_rows = []
        else:
            self.search_rows = data.search_rows(self.tax, lang)

    def _load_metadata_props(self) -> list[MetaProp]:
        """The configured ontology-metadata predicate catalog (built-in defaults
        when the user has never customised it)."""
        from ster.nav.logic import default_annotation_catalog
        from ster.nav.prefs import load_metadata_props

        return load_metadata_props() or default_annotation_catalog()

    def _load_entity_metadata_props(self) -> list[MetaProp]:
        """The configured entity-metadata predicate catalog (built-in defaults when
        the user has never customised it)."""
        from ster.nav.logic import default_entity_annotation_catalog
        from ster.nav.prefs import load_entity_metadata_props

        return load_entity_metadata_props() or default_entity_annotation_catalog()

    def _load_configured_langs(self, path: Path | None, lang: str) -> list[str]:
        """Per-file configured languages, defaulting to the display language."""
        if path is None:
            return [lang]
        from ster.nav.prefs import load_configured_langs

        return load_configured_langs(path) or [lang]

    @staticmethod
    def _entity_count(taxonomy: Taxonomy) -> int:
        return sum(
            len(getattr(taxonomy, name))
            for name in ("owl_classes", "owl_individuals", "owl_properties", "concepts")
        )

    def _start_search_rows_worker(self) -> None:
        """Build the large command-palette index after the first UI frame."""
        if not self._defer_search_rows:
            return
        self.run_worker(
            partial(self._search_rows_worker, self.tax, self.lang),
            thread=True,
            exclusive=True,
            group="search-rows",
            name="ster-search-rows",
        )

    def _search_rows_worker(self, taxonomy: Taxonomy, lang: str) -> None:
        rows = data.search_rows(taxonomy, lang)
        self.call_from_thread(self._set_search_rows, taxonomy, lang, rows)

    def _set_search_rows(
        self, taxonomy: Taxonomy, lang: str, rows: list[tuple[str, str, str]]
    ) -> None:
        if self.tax is taxonomy and self.lang == lang:
            self.search_rows = rows

    def _refresh_search_rows(self) -> None:
        """Refresh the command-palette index without blocking large-taxonomy edits."""
        self._defer_search_rows = self._entity_count(self.tax) > _LARGE_TAXONOMY_THRESHOLD
        if self._defer_search_rows:
            self.search_rows = []
            self._start_search_rows_worker()
        else:
            self.search_rows = data.search_rows(self.tax, self.lang)

    def _load_taxonomy_worker(self) -> None:
        """Load the source file away from Textual's event loop."""
        from ster import store

        if self._path is None:
            self.call_from_thread(self._show_load_error, ValueError("No taxonomy file was given."))
            return
        try:
            taxonomy = store.load(
                self._path,
                progress_callback=lambda percent, message: self.call_from_thread(
                    self._set_loading_progress, "Loading", percent, message
                ),
            )
        except Exception as exc:  # noqa: BLE001 — loading errors belong in the TUI
            self.call_from_thread(self._show_load_error, exc)
            return
        self.call_from_thread(self._finish_loading, taxonomy)

    def _finish_loading(self, taxonomy: Taxonomy) -> None:
        """Install the loaded model and replace the loading message in this app."""
        self.tax = taxonomy
        self._loaded_successfully = True
        self._service = self._make_service(taxonomy, self._path)
        self._defer_search_rows = self._entity_count(taxonomy) > _LARGE_TAXONOMY_THRESHOLD
        self.search_rows = [] if self._defer_search_rows else data.search_rows(taxonomy, self.lang)
        self._set_loading_progress(_LIT_PREPARING, 0, "Building navigation index")
        self.run_worker(
            partial(self._prepare_navigation_worker, taxonomy, self.lang),
            thread=True,
            exclusive=True,
            group="navigation-index",
            name="ster-navigation-index",
        )

    def _prepare_navigation_worker(self, taxonomy: Taxonomy, lang: str) -> None:
        self.call_from_thread(
            self._set_loading_progress, _LIT_PREPARING, 20, "Indexing individuals"
        )
        index = data.individual_index(taxonomy, lang)
        self.call_from_thread(self._navigation_index_ready, taxonomy, index)

    def _navigation_index_ready(
        self, taxonomy: Taxonomy, index: tuple[dict[str, list[str]], list[str]]
    ) -> None:
        if self.tax is not taxonomy:
            return
        self._individuals_by_class, self._untyped_individuals = index
        self._navigation_index_built = True
        if self._browser_mounted:
            self._set_loading_progress(_LIT_PREPARING, 80, "Building browser")
        else:
            self._set_loading_progress(_LIT_PREPARING, 60, "Building browser")
        self._mount_browser()
        self.call_after_refresh(self._initialize_browser)

    def _show_load_error(self, exc: Exception) -> None:
        """Keep the app open with a readable load failure instead of a blank terminal."""
        self._loading = False
        if self._loading_spinner_timer is not None:
            self._loading_spinner_timer.stop()
            self._loading_spinner_timer = None
        self._set_loading_message(f"Unable to load {self.source}: {exc}\n\nPress q to quit.")

    def _set_loading_message(self, message: str) -> None:
        try:
            self.query_one(_LOADING_SELECTOR, Static).update(message)
        except NoMatches:
            pass

    def _set_loading_progress(self, phase: str, percent: int, message: str) -> None:
        """Render a phase percentage while the loader still covers the browser."""
        self._set_loading_message(
            f"{self._LOADING_SPINNER[self._loading_spinner_frame]} {phase} {percent}%\n{message}"
        )

    def _advance_loading_spinner(self) -> None:
        """Animate the loader independently of the coarse phase percentage."""
        if not self._loading:
            return
        self._loading_spinner_frame = (self._loading_spinner_frame + 1) % len(self._LOADING_SPINNER)
        loading = self.query(_LOADING_SELECTOR)
        if loading:
            widget = loading.first(Static)
            text = str(widget.render())
            if "\n" in text:
                _, details = text.split("\n", 1)
                self._set_loading_message(
                    f"{self._LOADING_SPINNER[self._loading_spinner_frame]} {text.splitlines()[0][2:]}\n{details}"
                )

    def _mount_browser(self) -> None:
        """Mark the browser widgets as available; they are composed from the start."""
        if self._browser_mounted:
            return
        self._browser_mounted = True

    def _initialize_browser(self) -> None:
        """Start browser work after its widgets have had a chance to paint."""
        if not self._browser_mounted or self._browser_ready:
            return
        if not self._progressive_startup:
            self._initialize_browser_direct()
            return
        self._set_loading_progress(_LIT_PREPARING, 75, "Configuring browser")
        if not self._context_server_started:
            threading.Thread(
                target=_start_context_server,
                args=(self.tax, self._path),
                daemon=True,
                name="ster-context-server",
            ).start()
            self._context_server_started = True
        for tree in self.query(Tree):
            tree.show_root = False
            tree.guide_depth = 3
        self._sync_lint_features()
        if not self._navigation_index_built:
            self._set_loading_progress(_LIT_PREPARING, 78, "Indexing individuals")
            self.run_worker(
                partial(self._prepare_navigation_worker, self.tax, self.lang),
                thread=True,
                exclusive=True,
                group="navigation-index",
                name="ster-navigation-index",
            )
            return
        self.call_after_refresh(self._build_property_tree_stage)

    def _initialize_browser_direct(self) -> None:
        """Keep the historical synchronous path for callers with a ready taxonomy."""
        threading.Thread(
            target=_start_context_server,
            args=(self.tax, self._path),
            daemon=True,
            name="ster-context-server",
        ).start()
        for tree in self.query(Tree):
            tree.show_root = False
            tree.guide_depth = 3
        self._sync_lint_features()
        if self.tax.owl_individuals and not self._individuals_by_class:
            self._individuals_by_class, self._untyped_individuals = data.individual_index(
                self.tax, self.lang
            )
        self._navigation_index_built = True
        self._build_prop_tree(self.query_one(_PROPERTY_TREE_SELECTOR, Tree))
        self._folded_panels = self._default_folded()
        self._build_main_trees()
        self._start_search_rows_worker()
        self.query_one(_TREE_SELECTOR, Tree).border_title = "Mixed SKOS/OWL"
        self.query_one(_ONTOLOGY_TREE_SELECTOR, Tree).border_title = "Ontology"
        self.query_one(_PROPERTY_TREE_SELECTOR, Tree).border_title = "Properties"
        self.query_one(_DETAIL_SELECTOR, DetailView).border_title = "Details"
        self.query_one(_TREE_SELECTOR, Tree).focus()
        self.call_after_refresh(self._initial_show)
        self._update_lang_indicator()

    def _build_property_tree_stage(self) -> None:
        """Build the small property pane in its own UI turn."""
        if not self._browser_mounted or self._browser_ready:
            return
        self._set_loading_progress(_LIT_PREPARING, 84, "Building properties")
        self._build_prop_tree(self.query_one(_PROPERTY_TREE_SELECTOR, Tree))
        self._folded_panels = self._default_folded()
        self.call_after_refresh(self._build_main_tree_stage)

    def _build_main_tree_stage(self) -> None:
        """Build the main panes in a separate UI turn."""
        if not self._browser_mounted or self._browser_ready:
            return
        self._set_loading_progress(_LIT_PREPARING, 92, "Building browser tree")
        self._deferred_individuals.clear()
        self._deferred_tree_nodes.clear()
        self._build_unified_tree(self.query_one(_TREE_SELECTOR, Tree))
        self.call_after_refresh(self._build_ontology_tree_stage)

    def _build_ontology_tree_stage(self) -> None:
        """Build the ontology pane after the unified pane can render."""
        if not self._browser_mounted or self._browser_ready:
            return
        self._set_loading_progress(_LIT_PREPARING, 95, "Building ontology tree")
        self._build_ontology_tree(self.query_one(_ONTOLOGY_TREE_SELECTOR, Tree))
        self._apply_layout()
        self.call_after_refresh(self._finish_browser_initialization)

    def _finish_browser_initialization(self) -> None:
        """Finish labels and focus after the tree has had a chance to render."""
        if not self._browser_mounted or self._browser_ready:
            return
        self._set_loading_progress(_LIT_PREPARING, 98, "Finalizing browser")
        self._start_search_rows_worker()
        self.query_one(_TREE_SELECTOR, Tree).border_title = "Mixed SKOS/OWL"
        self.query_one(_ONTOLOGY_TREE_SELECTOR, Tree).border_title = "Ontology"
        self.query_one(_PROPERTY_TREE_SELECTOR, Tree).border_title = "Properties"
        self.query_one(_DETAIL_SELECTOR, DetailView).border_title = "Details"
        self.query_one(_TREE_SELECTOR, Tree).focus()
        self.call_after_refresh(self._initial_show)
        self._update_lang_indicator()
        self._set_loading_progress(_LIT_PREPARING, 100, "Ready")
        self._loading = False
        loading = self.query(_LOADING_SELECTOR)
        if loading:
            loading.first(Static).display = False
        if self._loading_spinner_timer is not None:
            self._loading_spinner_timer.stop()
            self._loading_spinner_timer = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            if self._loading:
                yield Static(
                    f"{self._LOADING_SPINNER[0]} Loading {self.source}... 0%\nStarting",
                    id="loading",
                )
            with Vertical(id="nav"):
                yield OntologyTree("unified", id="tree", classes="main-tree")
                yield OntologyTree("ontology", id="ont-tree", classes="main-tree")
                yield OntologyTree("properties", id="prop-tree")
            yield DetailView(id="detail")
        yield Footer()
        yield Static("", id="lang-indicator")  # bottom-right status: selected language
        yield Static("", id="busy")  # bottom-left status: Saving… / Checking… spinner
        yield ContextMenu(id="ctx-menu")  # hidden overlay; shown on right-click

    def on_mount(self) -> None:
        from ster._version import __version__ as _version  # noqa: PLC0415

        self.title = f"STER version {_version} - {self.source}"
        self.sub_title = ""
        if self._progressive_startup:
            self._loading_spinner_timer = self.set_interval(0.12, self._advance_loading_spinner)
        if self._loading_from_file:
            self.run_worker(
                self._load_taxonomy_worker,
                thread=True,
                exclusive=True,
                group="taxonomy-load",
                name="ster-taxonomy-load",
            )
            return
        self._mount_browser()
        self._initialize_browser()

    def _initial_show(self) -> None:
        """First paint. Opening straight into the query workspace skips the browser's
        overview + lint + tree-recolour (none of it is needed to run SPARQL) — that runs
        lazily the first time the browser is actually shown, so the query screen appears
        without waiting on a full semanticlint pass over a large ontology."""
        if self._open_query_on_start:  # home-menu "Query" opens straight into the query screen
            self.action_open_query()
            return
        self._ensure_browser_ready()

    def _ensure_browser_ready(self) -> None:
        """Show the overview (which computes the first lint result), then recolour the tree.
        Idempotent — the browser's first paint, deferred when we open into the query screen."""
        if self._browser_ready:
            return
        self._browser_ready = True
        self._show(detail.OVERVIEW_URI)
        if self._lint_icons_on:
            self._rebuild_tree()
        self.call_after_refresh(self._maybe_scan_on_open)

    def on_unmount(self) -> None:
        """Flush a pending background save when the app closes."""
        self._flush_save()
