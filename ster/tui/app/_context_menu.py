"""The right-click / context-menu system: opening it for a tree row or section header, filtering its actions, and routing the chosen action."""

from __future__ import annotations

from typing import Final

from textual.widgets import Tree

from ster.nav.logic import DetailField

from .. import data, detail, edits, uri_edit
from ..context_menu import ContextMenu
from ..picker_modal import PickerModal
from ..uri_modal import UriModal
from ._constants import _CONTEXT_MENU_SELECTOR, _PROP_CREATE_ACTIONS, _PROP_MENU, _READ_ONLY_MESSAGE
from ._helpers import _parse_add_prop
from ._state import _AppState

_LIT_ACTION: Final = "action"
_LIT_WARNING: Final = "warning"


class _ContextMenuMixin(_AppState):
    """Mixin: the right-click / context-menu system: opening it for a tree row or section header, filtering its actions, and routing the chosen action."""

    def action_context_menu(self) -> None:
        """'.' → open the context menu for the selected entity, at the tree cursor."""
        if self._detail_uri:
            self.open_context_menu(self._detail_uri, self._tree_cursor_anchor())

    def _tree_cursor_anchor(self) -> tuple[int, int] | None:
        """Screen position of the focused tree's cursor row (for menu anchoring)."""
        tree = self.focused if isinstance(self.focused, Tree) else None
        if tree is None:
            return None
        region = tree.region
        return (region.x + 2, region.y + max(0, tree.cursor_line - tree.scroll_offset.y))

    def open_context_menu(self, uri: str, anchor: tuple[int, int] | None = None) -> None:
        """Right-click / '.' handler: select the node and offer kind-appropriate
        quick actions. *anchor* is the cursor position; the menu pops up there
        (centred when None).
        """
        prop_type = _parse_add_prop(uri)
        if prop_type is not None:  # a property-tree header → "＋ Add <kind> property"
            title, add_label, action, _modal = _PROP_MENU[prop_type]
            self.query_one(_CONTEXT_MENU_SELECTOR, ContextMenu).show(
                title, [(add_label, action)], anchor
            )
            return
        if uri == detail.OVERVIEW_URI:  # the Ontology section → "＋ Add class"
            self._show_section_menu(uri, "Ontology", ("＋ Add class", "create_owl_class"), anchor)
            return
        if uri == detail.TAXONOMY_URI:  # the Taxonomy section → "＋ Add concept scheme"
            self._show_section_menu(
                uri, "Taxonomy", ("＋ Add concept scheme", "add_scheme"), anchor
            )
            return
        items = self._filter_plugin_actions(edits.context_actions(edits.menu_kind(self.tax, uri)))
        items = self._filter_class_actions(uri, items)
        if not items:
            return
        self._show(uri)  # select it, so the actions target this entity
        label = data.label_of(self.tax, uri, self.lang)
        self.query_one(_CONTEXT_MENU_SELECTOR, ContextMenu).show(label, items, anchor)

    def _show_section_menu(
        self, uri: str, title: str, item: tuple[str, str], anchor: tuple[int, int] | None
    ) -> None:
        """Select a section node (Ontology / Taxonomy) so its create action has the right
        target, then pop its single-item context menu."""
        self._show(uri)
        self.query_one(_CONTEXT_MENU_SELECTOR, ContextMenu).show(title, [item], anchor)

    #: context-menu actions that belong to an opt-in plugin feature (SHACL enforce).
    _ENFORCE_ACTIONS = frozenset({"enforce_shacl", "unenforce_shacl"})

    def _filter_plugin_actions(self, items: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """Hide plugin-gated actions when their feature is off — the SHACL enforce/remove
        items only appear when semanticlint's ``enforce`` feature is active."""
        from ster.plugins import semanticlint

        if semanticlint.enforce_active():
            return items
        return [(lbl, act) for lbl, act in items if act not in self._ENFORCE_ACTIONS]

    def _filter_class_actions(
        self, uri: str, items: list[tuple[str, str]]
    ) -> list[tuple[str, str]]:
        """Hide '↑ Add superclass' on non-top-level classes — only a root class (no
        rdfs:subClassOf parent) may gain a superclass from the menu."""
        cls = self.tax.owl_classes.get(uri)
        if cls is None or not cls.sub_class_of:  # not a class, or a top-level class → keep all
            return items
        return [(lbl, act) for lbl, act in items if act != "link_superclass"]

    def _handle_row_menu_action(self, action: str) -> bool:
        """The detail-row submenu — Edit / Delete / Go-to. Returns True when it handled *action*.

        Value rows carry an edit *action* (a picker for object values / class membership, a
        text modal for literals) — dispatch it; plain editable rows (labels, comments, URI)
        open the generic edit modal."""
        if action == "row_edit" and self._row_menu_field is not None:
            field, self._row_menu_field = self._row_menu_field, None
            self._row_menu_delete = None
            if field.meta.get(_LIT_ACTION):
                self._run_field_action(field)
            else:
                self._open_edit_modal(field, origin=self._row_menu_origin)
            return True
        if action == "row_delete" and self._row_menu_delete is not None:
            delete_field, self._row_menu_delete = self._row_menu_delete, None
            menu_field, self._row_menu_field = self._row_menu_field, None
            label = menu_field.display if menu_field is not None else delete_field.display
            self._apply_row_delete(delete_field, label=label)
            return True
        if action == "row_goto" and self._row_menu_goto is not None:
            target, self._row_menu_goto = self._row_menu_goto, None
            self._row_menu_field = self._row_menu_delete = None
            self.jump_to(target)  # navigate to the value's target entity
            return True
        return False

    def on_context_menu_chosen(self, message: ContextMenu.Chosen) -> None:
        """A context-menu action was picked → run it against the selected entity."""
        # Detail-row Edit / Delete / Go-to submenu (takes priority over the tree-node menu).
        if self._handle_row_menu_action(message.action):
            return

        prop_type = _PROP_CREATE_ACTIONS.get(message.action)
        if prop_type is not None:  # "＋ Add <kind> property" from a property-tree header
            self._open_property_create(prop_type)
            return

        uri = self._detail_uri
        if uri is None:
            return
        if message.action == "rename":
            self._rename_entity(uri)
        else:  # synthesise the row this action would come from, then run it
            self._run_field_action(
                DetailField(
                    "ctx",
                    "",
                    "",
                    editable=False,
                    meta={"type": _LIT_ACTION, _LIT_ACTION: message.action},
                )
            )

    def _rename_entity(self, uri: str) -> None:
        """Open a modal to rename *uri* (cascades across every reference)."""
        if self._service is None or self._path is None:
            self.notify(_READ_ONLY_MESSAGE, severity=_LIT_WARNING)
            return
        path = self._path
        field = DetailField("uri", "URI", uri, editable=True, meta={"type": "uri"})

        def _on_submit(value: str | None) -> None:
            if value and value != uri:
                command = edits.edit_command(field, uri, path, value)
                if command is not None:
                    # select=value so the highlight + detail follow the entity to its new
                    # URI (the old one is gone, so restoring _detail_uri would lose it).
                    self._apply_command(command, select=value)

        prefix, fragment = uri_edit.split_namespace(uri)
        self.push_screen(UriModal("Rename URI", prefix, fragment), _on_submit)

    def _route_action(self, action: str):  # type: ignore[no-untyped-def]
        """Pick the flow opener for *action* — first table whose set contains it."""
        routes = (
            (edits.DELETE_CHOICES, self._confirm_delete),
            (edits.PICKER_ACTIONS, self._pick_relation),
            (edits.META_PICKER_ACTIONS, self._pick_meta_relation),
            (edits.CONVERT_ACTIONS, self._confirm_convert),
            (edits.CHAINED_ACTIONS, self._add_property_value),
            (edits.SCHEME_ACTIONS, self._create_scheme),
            (edits.ONTOLOGY_RENAME_ACTIONS, self._edit_ontology_identity),
            (edits.ANNOTATION_ADD_ACTIONS, self._add_ont_annotation),
            (edits.ENTITY_ANNOTATION_ADD_ACTIONS, self._add_entity_annotation),
            (edits.META_INPUT_ACTIONS, self._open_meta_input),
            (edits.INPUT_ACTIONS, self._open_input),
        )
        return next((opener for collection, opener in routes if action in collection), None)

    def _pool_for(self, kind: str) -> dict:  # type: ignore[type-arg]
        """The candidate entity dict for a picker *kind*."""
        if kind == "concept":
            return self.tax.concepts
        if kind == "individual":
            return self.tax.owl_individuals
        return self.tax.owl_classes

    def _open_picker(self, prompt: str, kind: str, exclude: str, on_pick) -> None:  # type: ignore[no-untyped-def]
        """Show a picker of all *kind* entities (excluding *exclude*) → callback with the URI."""
        candidates = sorted(
            (
                (data.label_of(self.tax, u, self.lang), u)
                for u in self._pool_for(kind)
                if u != exclude
            ),
            key=lambda t: t[0].lower(),
        )
        if not candidates:
            self.notify(f"No other {kind}s to link to.", severity=_LIT_WARNING)
            return
        self.push_screen(PickerModal(prompt, candidates, kind_label=kind), on_pick)

    def _run_or_warn(self, command: object | None, select: str | None = None) -> None:
        """Apply *command*, or warn if the dispatch produced nothing."""
        if command is None:
            self.notify("This action isn't wired up yet.", severity=_LIT_WARNING)
            return
        self._apply_command(command, select=select)

    _CLASS_CREATE_ACTIONS = frozenset({"create_owl_class", "new_subclass"})
