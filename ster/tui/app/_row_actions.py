"""Detail-row interactions: edit/menu/action requests fired by a DetailRow, and the entity-action handlers they dispatch to (promote/demote/tag/link concepts)."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from textual.widget import Widget

from ster.nav.logic import DetailField

from .. import data, edits, uri_edit
from ..choice_modal import ChoiceModal
from ..context_menu import ContextMenu
from ..detail_view import DetailRow
from ..edit_modal import EditModal
from ..uri_modal import UriModal
from ._constants import _CONTEXT_MENU_SELECTOR, _READ_ONLY_MESSAGE
from ._state import _AppState

_LIT_WARNING: Final = "warning"


class _RowActionsMixin(_AppState):
    """Mixin: detail-row interactions: edit/menu/action requests fired by a DetailRow, and the entity-action handlers they dispatch to (promote/demote/tag/link concepts)."""

    def on_detail_row_edit_requested(self, message: DetailRow.EditRequested) -> None:
        """An edit-only value row asked to be edited → open the modal → command."""
        self._pending_focus_key = message.field.key  # refocus this row after the edit
        self._open_edit_modal(message.field, origin=self.focused)

    def _warn_malformed_links(self, value: str) -> None:
        """Warn (non-blocking) when a submitted value carries a Markdown link that won't
        resolve — a missing/typo'd scheme, a host-less URL, etc. Runs on every create /
        update so a broken link is caught at edit time, not silently saved. No-op when the
        value has no links or they are all valid (web or URN)."""
        from ..urls import malformed_markdown_links

        bad = malformed_markdown_links(value)
        if bad:
            self.notify(
                "This value has a link that won't open:\n" + "\n".join(bad),
                title="Malformed link",
                severity=_LIT_WARNING,
                timeout=8,
            )

    def _open_edit_modal(self, field: DetailField, origin: Widget | None = None) -> None:
        """Open the prefilled edit modal for *field* and apply the resulting command.

        On cancel, focus returns to *origin* (the row being edited) so it stays in
        the detail pane instead of jumping back to the tree.
        """
        # A field may target a different entity than the shown one (e.g. the taxonomy
        # overview edits the primary scheme via meta["target_uri"]).
        uri, path = field.meta.get("target_uri") or self._detail_uri, self._path
        if self._service is None or uri is None or path is None:
            self.notify(_READ_ONLY_MESSAGE, severity=_LIT_WARNING)
            return
        # Entities merged from a context file belong to another file; naming it is
        # the difference between "you can't" and "you can, over there".
        if (source := self.tax.context_source.get(uri)) is not None:
            self.notify(
                f"Read-only — defined in {source.name}. Open that file to edit it.",
                title="Context file",
                severity=_LIT_WARNING,
            )
            return

        def _on_submit(value: str | None) -> None:
            if value is None:
                self._pending_focus_key = None
                if origin is not None:
                    origin.focus()  # Esc/cancel: keep focus in the detail pane
                return
            command = edits.edit_command(field, uri, path, value)
            if command is None:
                self.notify("This field isn't editable yet.", severity=_LIT_WARNING)
                return
            self._warn_malformed_links(value)  # surface a broken Markdown link on update
            self._apply_command(command)

        # A URI value is renamed fragment-only: lock its namespace, edit the local name.
        if field.meta.get("type") == "uri":
            prefix, fragment = uri_edit.split_namespace(field.value)
            self.push_screen(UriModal(field.display, prefix, fragment), _on_submit)
        else:
            self.push_screen(
                EditModal(
                    field.display,
                    field.value,
                    multiline=edits.is_long_text(field),
                    autolink=edits.is_prose(field),
                ),
                _on_submit,
            )

    def on_detail_row_menu_requested(self, message: DetailRow.MenuRequested) -> None:
        """A value row with both edit and delete was activated → Edit / Delete submenu, plus a
        generic "Go to «target»" when the value points at a navigable entity (e.g. an object
        property's target, or a dct:subject tag's concept)."""
        self._row_menu_field = message.field
        self._row_menu_delete = message.delete_field
        self._row_menu_origin = self.focused  # the row, before the menu grabs focus
        self._pending_focus_key = message.field.key  # refocus this row after edit/delete
        items = [("✎ Edit", "row_edit"), ("⊘ Delete", "row_delete")]
        meta = message.field.meta
        target = meta.get("val_uri") or meta.get("uri")
        self._row_menu_goto = target if meta.get("nav") and target else None
        if self._row_menu_goto is not None:
            items.append((f"→ Go to «{message.field.value}»", "row_goto"))
        self.query_one(_CONTEXT_MENU_SELECTOR, ContextMenu).show(
            message.field.display, items, message.anchor
        )

    def _apply_row_delete(self, delete_field: DetailField, *, label: str | None = None) -> None:
        """Confirm, then run the paired removal command for a row's Delete submenu choice.

        On confirm the row is gone, so focus lands on the entity's tree node (``focus_tree``)
        — one Tab/arrow back to the detail pane; on cancel it stays on the edited row."""
        uri, path = self._detail_uri, self._path
        if self._service is None or uri is None or path is None:
            self.notify(_READ_ONLY_MESSAGE, severity=_LIT_WARNING)
            return
        command = edits.direct_command(delete_field, uri, path)
        if command is None:
            return
        prompt = f"Delete «{label or delete_field.display}»?"

        def _on_choice(choice: str | None) -> None:
            if choice is None:
                self._refocus_edited_row()  # cancel → stay on the edited row
                return
            self._apply_command(command, focus_tree=True)

        self.push_screen(ChoiceModal(prompt, [("Delete", "ok")], danger=True), _on_choice)

    def on_detail_row_action_requested(self, message: DetailRow.ActionRequested) -> None:
        """An action row was activated → run it (shared with the right-click menu)."""
        self._pending_focus_key = message.field.key  # refocus this row after the action
        self._run_field_action(message.field)

    #: (uri, path) entity actions that open a dedicated flow — dispatched by name so
    #: adding one is a table row, not another branch in _run_field_action.
    _ENTITY_ACTION_HANDLERS = {
        "edit_class": "_open_class_edit",  # full class modal (URI + labels + comments)
        "edit_individual": "_open_individual_edit",  # full individual modal
        "enforce_shacl": "_enforce_shacl",  # write a mandatory SHACL rule, then re-lint
        "unenforce_shacl": "_unenforce_shacl",  # remove the property's SHACL rule
        "promote": "_promote_concept",  # concept → pun (new class) or foaf:focus link
        "demote": "_demote_pun",  # pun → concept (drop the owl:Class facet)
        "unlink": "_unlink_concept",  # linked → concept (drop the foaf:focus link)
        "tag_individuals": "_tag_individuals",  # bulk-tag individuals with this concept
    }

    def _run_field_action(self, field: DetailField) -> None:
        """Dispatch an action *field*: graph view, meta-driven removal, or a flow."""
        action = field.meta.get("action", "")
        if self._run_view_action(action, field):  # read-only views need no service
            return
        uri, path = self._detail_uri, self._path
        if self._service is None or uri is None or path is None:
            self.notify(_READ_ONLY_MESSAGE, severity=_LIT_WARNING)
            return
        if action == "edit_property":  # the field names the property (not the shown class)
            self._open_property_edit(field.meta.get("uri", ""), path)
            return
        handler = self._ENTITY_ACTION_HANDLERS.get(action)
        if handler is not None:
            getattr(self, handler)(uri, path)
            return
        direct = edits.direct_command(field, uri, path)
        if direct is not None:  # meta-driven removal — run immediately, no modal
            self._apply_command(direct)
            return
        opener = self._route_action(action)
        if opener is None:
            self.notify("This action isn't wired up yet.", severity=_LIT_WARNING)
            return
        opener(field, uri, path)

    def _run_view_action(self, action: str, field: DetailField) -> bool:
        """Handle read-only view actions (graph, lint) that need no service. Returns
        True when *action* was one of them (and has been handled)."""
        if action in ("view_ontology_graph", "view_focused_graph"):
            self._open_graph(action, field)
            return True
        if action == "view_lint":
            self._open_lint(field.meta.get("lint_severity"))
            return True
        return False

    def _promote_concept(self, uri: str, path: Path) -> None:
        """Promote a concept — first pick *how*: mint a new same-URI class (a pun), or link
        it to an existing OWL class via foaf:focus (which surfaces that class's individuals)."""

        def _on_choice(mode: str | None) -> None:
            if mode == "pun":
                from ster.core.commands import PromoteConceptToClass

                self._apply_command(PromoteConceptToClass(path, uri))
            elif mode == "link":
                self._link_concept_to_class(uri, path)

        self.push_screen(
            ChoiceModal(
                f"Promote «{data.label_of(self.tax, uri, self.lang)}»",
                [
                    ("Create a new class (pun, same URI)", "pun"),
                    ("Link to an existing class (foaf:focus)", "link"),
                ],
            ),
            _on_choice,
        )

    def _link_concept_to_class(self, uri: str, path: Path) -> None:
        """Pick an existing OWL class → foaf:focus link. No classes yet → guide the user."""
        if not self.tax.owl_classes:
            self.notify("Add a class in the Ontology section first.", severity=_LIT_WARNING)
            return

        def _on_pick(target: str | None) -> None:
            if target is not None:
                from ster.core.commands import LinkConceptToClass

                self._apply_command(LinkConceptToClass(path, uri, target), select=uri)

        self._open_picker("Link to an existing class — pick a class", "class", uri, _on_pick)

    def _unlink_concept(self, uri: str, path: Path) -> None:
        """Linked concept → plain concept: drop the foaf:focus link (non-destructive)."""
        from ster.core.commands import UnlinkConceptFromClass

        self._apply_command(UnlinkConceptFromClass(path, uri))

    def _demote_pun(self, uri: str, path: Path) -> None:
        """Pun → concept: drop the owl:Class facet (subclasses re-root, individuals keep)."""
        from ster.core.commands import DemotePunToConcept

        self._apply_command(DemotePunToConcept(path, uri))

    def _tag_individuals(self, uri: str, path: Path) -> None:
        """Bulk-tag: pick several individuals from a checklist, then dct:subject each to
        the concept *uri*. No-op if there are no individuals to tag."""
        from ster.core.commands import TagIndividuals
        from ster.tui.multi_picker_modal import MultiPickerModal

        individuals = sorted(
            self.tax.owl_individuals, key=lambda u: data.label_of(self.tax, u, self.lang).lower()
        )
        options = [(data.label_of(self.tax, u, self.lang), u) for u in individuals]
        if not options:
            self.notify("No individuals to tag yet.", severity=_LIT_WARNING)
            return
        label = data.label_of(self.tax, uri, self.lang)

        def _on_pick(chosen: list[str] | None) -> None:
            if chosen:
                self._apply_command(TagIndividuals(path, tuple(chosen), uri))

        self.push_screen(MultiPickerModal(f"Tag individuals with “{label}”", options), _on_pick)
