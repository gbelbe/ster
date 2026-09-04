"""``ConfigModal`` mixin: the Annotation properties tab (the two metadata
catalogs, ontology-level and entity-level) and its auto-save handler."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Collapsible, Static

from ._metadata_catalog import _MetaCatalog
from ._state import _ModalState


class _PropsMixin(_ModalState):
    """Annotation properties tab: the ontology-metadata and entity-metadata
    predicate catalogs."""

    def _props_tab(self) -> ComposeResult:
        yield Static(
            "Set up ster's pre-configured menu options — the annotation properties offered "
            "in the “Add metadata” menus for the ontology and for entities.",
            classes="cfg-tab-intro",
        )
        with Collapsible(title="Ontology Metadata", collapsed=False, id="cfg-ont-meta-group"):
            yield Static(
                "Offered when adding metadata to the ontology overview.", classes="cfg-hint"
            )
            yield _MetaCatalog(
                self._metadata,
                id="cfg-ont-meta",
                prev_target="#cfg-ont-meta-group CollapsibleTitle",  # Shift+Tab → own header
                next_target="#cfg-entity-meta-group CollapsibleTitle",  # Tab → next group
                verifier=self._annotation_verifier,
                can_declare=self._can_declare,
                base_uri=self._base_uri,
                scope="ontology",  # enforced on the ontology node
            )
        with Collapsible(title="Entity metadata", collapsed=False, id="cfg-entity-meta-group"):
            yield Static(
                "Offered when adding metadata to a class, property or individual.",
                classes="cfg-hint",
            )
            yield _MetaCatalog(
                self._entity_metadata,
                id="cfg-entity-meta",
                prev_target="#cfg-entity-meta-group CollapsibleTitle",  # Shift+Tab → own header
                next_target="Tabs",  # Tab → tab bar
                verifier=self._annotation_verifier,
                can_declare=self._can_declare,
                base_uri=self._base_uri,
                scope="entity",  # enforced on every owl:Class and skos:Concept
            )

    # ── metadata catalogs ───────────────────────────────────────────────────────
    def on__meta_catalog_changed(self, event: _MetaCatalog.Changed) -> None:
        """A predicate was added to either catalog → auto-save (toggles are handled
        by ``_StateMixin.on_checkbox_changed``)."""
        self._save()
