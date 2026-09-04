"""Opening/collecting input from the create and edit modals for every entity kind (class, property, individual), plus delete confirmation and value-picker flows."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from ster.nav.logic import DetailField

from .. import data, detail, edits, uri_edit
from ..choice_modal import ChoiceModal
from ..edit_modal import EditModal
from ..picker_modal import PickerModal
from ..uri_modal import UriModal
from ._constants import _PROP_MENU, _READ_ONLY_MESSAGE
from ._helpers import _prop_section_key
from ._state import _AppState

_LIT_ACTION: Final = "action"
_LIT_COMMENTS: Final = "comments"
_LIT_LABELS: Final = "labels"
_LIT_WARNING: Final = "warning"


class _EditingModalsMixin(_AppState):
    """Mixin: opening/collecting input from the create and edit modals for every entity kind (class, property, individual), plus delete confirmation and value-picker flows."""

    def _open_input(self, field: DetailField, uri: str, path: Path) -> None:
        """Collect a single text/URI value in a modal, then run its action command."""
        action = field.meta.get(_LIT_ACTION, "")
        # Creating a class / individual opens its full modal (URI + labels + …).
        if action in self._CLASS_CREATE_ACTIONS:
            self._open_class_create(action, uri, path)
            return
        if action == "add_individual":
            self._open_individual_create(uri, path)
            return
        prompt, prefill_kind = edits.INPUT_ACTIONS[action]
        # For a URI-minting action the created entity's URI *is* the typed value,
        # so navigate to it once the tree rebuilds (make the create visible).
        mints = prefill_kind == "base_uri"

        def _on_submit(value: str | None) -> None:
            if value:
                self._warn_malformed_links(value)  # surface a broken Markdown link on create
                self._run_or_warn(
                    edits.action_command(action, uri, path, value, self.lang),
                    select=value if mints else None,
                )

        # A new URI is minted fragment-only under the locked ontology/scheme base.
        if mints:
            base = uri_edit.mint_base(self.tax, action, uri)
            self.push_screen(UriModal(prompt, base), _on_submit)
        else:
            self.push_screen(
                EditModal(
                    prompt, "", multiline=edits.is_long_text(field), autolink=edits.is_prose(field)
                ),
                _on_submit,
            )

    def _class_langs(self) -> list[str]:
        return self.configured_langs or [self.lang]

    def _open_property_create(self, prop_type: str) -> None:
        """Open the create modal for a property-tree header. Object properties get the full
        modal (domain + range pickers); datatype / annotation get the lightweight one."""
        if prop_type == "ObjectProperty":
            self._open_object_property_create()
        else:
            self._open_simple_property_create(prop_type)

    def _open_simple_property_create(self, prop_type: str) -> None:
        """Datatype / annotation properties → a lightweight modal (URI + labels/comments;
        no domain/range — add those afterwards via the property's own menu) → create command."""
        from ster.core.commands import OwlCreateProperty

        from ..entity_form import EntityFormModal

        path = self._path
        if self._service is None or path is None:
            self.notify(_READ_ONLY_MESSAGE, severity=_LIT_WARNING)
            return
        base = uri_edit.mint_base(self.tax, "create_owl_property", detail.OVERVIEW_URI)
        modal_title = _PROP_MENU[prop_type][3]

        def _on_submit(result: dict | None) -> None:
            if result:
                self._apply_command(
                    OwlCreateProperty(
                        path,
                        result["uri"],
                        tuple(result[_LIT_LABELS].items()),
                        tuple(result[_LIT_COMMENTS].items()),
                        prop_type=prop_type,
                    ),
                    select=result["uri"],
                )

        self.push_screen(
            EntityFormModal(prefix=base, langs=self._class_langs(), title=modal_title),
            _on_submit,
        )

    def _open_object_property_create(self) -> None:
        """Right-click on the Object Properties header → full add modal (URI + labels /
        comments per configured language + domain + range) → create command."""
        from ster.core.commands import OwlCreateProperty

        from ..object_property_modal import ObjectPropertyModal

        path = self._path
        if self._service is None or path is None:
            self.notify(_READ_ONLY_MESSAGE, severity=_LIT_WARNING)
            return
        base = uri_edit.mint_base(self.tax, "create_owl_property", detail.OVERVIEW_URI)
        classes = sorted(
            ((data.label_of(self.tax, u, self.lang), u) for u in self.tax.owl_classes),
            key=lambda t: t[0].lower(),
        )

        def _on_submit(result: dict | None) -> None:
            if result:
                self._apply_command(
                    OwlCreateProperty(
                        path,
                        result["uri"],
                        tuple(result[_LIT_LABELS].items()),
                        tuple(result[_LIT_COMMENTS].items()),
                        result["domain"],
                        result["range"],
                    ),
                    select=result["uri"],
                )

        self.push_screen(
            ObjectPropertyModal(prefix=base, langs=self._class_langs(), classes=classes),
            _on_submit,
        )

    def _open_class_create(self, action: str, uri: str, path: Path) -> None:
        """Open the full class modal to create a class (top-level or under *uri*)."""
        from ster.core.commands import OwlCreateClass

        from ..class_modal import ClassModal

        base = uri_edit.mint_base(self.tax, action, uri)
        parent = uri if action == "new_subclass" else None

        def _on_submit(result: dict | None) -> None:
            if result:
                self._apply_command(
                    OwlCreateClass(
                        path,
                        result["uri"],
                        parent,
                        tuple(result[_LIT_LABELS].items()),
                        tuple(result[_LIT_COMMENTS].items()),
                    ),
                    select=result["uri"],
                )

        self.push_screen(ClassModal(prefix=base, langs=self._class_langs()), _on_submit)

    @staticmethod
    def _split_values(values: dict) -> tuple[tuple, tuple]:  # type: ignore[type-arg]
        """Split the modal's ``{prop: (kind, value)}`` into (object, literal) pairs,
        dropping empties."""
        obj: list[tuple[str, str]] = []
        lit: list[tuple[str, str]] = []
        for prop_uri, (kind, value) in values.items():
            if value:
                (obj if kind == "object" else lit).append((prop_uri, value))
        return tuple(obj), tuple(lit)

    def _individual_candidates(self, range_uri: str | None) -> list[tuple[str, str]]:
        """Existing individuals typed as *range_uri* (or a subclass) — the object-property
        dropdown options, sorted by label."""
        if not range_uri or range_uri not in self.tax.owl_classes:
            return []
        subtree = self._subtree_uris(range_uri)
        out = [
            (data.label_of(self.tax, u, self.lang), u)
            for u, ind in self.tax.owl_individuals.items()
            if subtree & set(ind.types)
        ]
        return sorted(out, key=lambda t: t[0].lower())

    def _individual_prop_fields(self, class_uri: str) -> list:
        """Build the modal's property rows from the class's direct + inherited properties."""
        from ster.nav.logic import suggested_properties

        from ..individual_modal import PropField

        fields = []
        for sp in suggested_properties(self.tax, class_uri, self.lang):
            label = sp.label
            if sp.inherited_from:
                label += f"  (from {data.label_of(self.tax, sp.inherited_from, self.lang)})"
            candidates = self._individual_candidates(sp.range_uri) if sp.kind == "object" else []
            fields.append(
                PropField(
                    prop_uri=sp.prop_uri, label=label, kind=sp.kind, candidates=tuple(candidates)
                )
            )
        return fields

    def _open_individual_create(self, class_uri: str, path: Path) -> None:
        """Open the full individual modal to create an instance of *class_uri*."""
        from ster.core.commands import OwlCreateIndividualFull

        from ..individual_modal import IndividualModal

        base = uri_edit.mint_base(self.tax, "add_individual", class_uri)

        def _on_submit(result: dict | None) -> None:
            if result:
                obj_values, lit_values = self._split_values(result["values"])
                self._apply_command(
                    OwlCreateIndividualFull(
                        path,
                        result["uri"],
                        class_uri,
                        tuple(result[_LIT_LABELS].items()),
                        tuple(result[_LIT_COMMENTS].items()),
                        obj_values,
                        lit_values,
                    ),
                    select=result["uri"],
                )

        self.push_screen(
            IndividualModal(
                prefix=base,
                langs=self._class_langs(),
                type_label=data.label_of(self.tax, class_uri, self.lang),
                prop_fields=self._individual_prop_fields(class_uri),
            ),
            _on_submit,
        )

    def _open_individual_edit(self, uri: str, path: Path) -> None:
        """Open the full individual modal to edit an existing individual (URI / labels /
        comments). Types and property values stay managed via the per-row actions."""
        from ster.core.commands import OwlSaveIndividual

        from ..individual_modal import IndividualModal

        ind = self.tax.owl_individuals.get(uri)
        if ind is None:
            return
        prefix, fragment = uri_edit.split_namespace(uri)
        labels = {lbl.lang: lbl.value for lbl in ind.labels}
        comments = {c.lang: c.value for c in ind.comments}
        type_label = ", ".join(data.label_of(self.tax, t, self.lang) for t in ind.types)

        def _on_submit(result: dict | None) -> None:
            if result:
                self._apply_command(
                    OwlSaveIndividual(
                        path,
                        uri,
                        result["uri"],
                        tuple(result[_LIT_LABELS].items()),
                        tuple(result[_LIT_COMMENTS].items()),
                    ),
                    select=result["uri"],
                )

        self.push_screen(
            IndividualModal(
                prefix=prefix,
                fragment=fragment,
                langs=self._class_langs(),
                type_label=type_label,
                labels=labels,
                comments=comments,
                title="Edit individual",
            ),
            _on_submit,
        )

    def _open_class_edit(self, uri: str, path: Path) -> None:
        """Open the full class modal to edit an existing class (URI / labels / comments)."""
        from ster.core.commands import OwlSaveClass

        from ..class_modal import ClassModal

        cls = self.tax.owl_classes.get(uri)
        if cls is None:
            return
        prefix, fragment = uri_edit.split_namespace(uri)
        labels = {lbl.lang: lbl.value for lbl in cls.labels}
        comments = {c.lang: c.value for c in cls.comments}

        def _on_submit(result: dict | None) -> None:
            if result:
                self._apply_command(
                    OwlSaveClass(
                        path,
                        uri,
                        result["uri"],
                        tuple(result[_LIT_LABELS].items()),
                        tuple(result[_LIT_COMMENTS].items()),
                    ),
                    select=result["uri"],  # keep the highlight on the (possibly renamed) class
                )

        self.push_screen(
            ClassModal(
                prefix=prefix,
                fragment=fragment,
                langs=self._class_langs(),
                labels=labels,
                comments=comments,
                title="Edit class",
            ),
            _on_submit,
        )

    def _open_property_edit(self, prop_uri: str, path: Path) -> None:
        """Open the edit modal for a property (URI + labels/comments per language) → save.
        Its domain / range are preserved (edited via the property context menu)."""
        from ster.core.commands import OwlSaveProperty

        from ..property_edit_modal import PropertyEditModal

        prop = self.tax.owl_properties.get(prop_uri)
        if prop is None:
            return
        prefix, fragment = uri_edit.split_namespace(prop_uri)
        labels = {lbl.lang: lbl.value for lbl in prop.labels}
        comments = {c.lang: c.value for c in prop.comments}
        domains, ranges = tuple(prop.domains), tuple(prop.ranges)  # preserved as-is

        def _on_submit(result: dict | None) -> None:
            if result:
                self._apply_command(
                    OwlSaveProperty(
                        path,
                        prop_uri,
                        result["uri"],
                        tuple(result[_LIT_LABELS].items()),
                        tuple(result[_LIT_COMMENTS].items()),
                        domains,
                        ranges,
                    ),
                    select=result["uri"],  # highlight follows the (possibly renamed) property
                )

        self.push_screen(
            PropertyEditModal(
                prefix=prefix,
                fragment=fragment,
                langs=self._class_langs(),
                labels=labels,
                comments=comments,
            ),
            _on_submit,
        )

    def _open_meta_input(self, field: DetailField, uri: str, path: Path) -> None:
        """Edit one existing value (the row's meta names which) via a prefilled modal."""
        action = field.meta.get(_LIT_ACTION, "")
        prompt, prefill_key = edits.META_INPUT_ACTIONS[action]

        def _on_submit(value: str | None) -> None:
            if value:
                self._run_or_warn(edits.meta_input_command(field, uri, path, value, self.lang))
            else:
                self._refocus_edited_row()  # cancel → stay on the edited row

        # base_uri-kind meta inputs (e.g. add_class_property) mint a new URI fragment-only.
        if prefill_key == "base_uri":
            base = uri_edit.mint_base(self.tax, action, uri)
            self.push_screen(UriModal(prompt, base), _on_submit)
            return

        self.push_screen(
            EditModal(
                prompt,
                field.meta.get(prefill_key, ""),
                multiline=edits.is_long_text(field),
                autolink=edits.is_prose(field),
            ),
            _on_submit,
        )

    def _confirm_delete(self, field: DetailField, uri: str, path: Path) -> None:
        """Ask for the delete mode, then run the delete and land the cursor on the deleted
        entity's parent (its super-class / broader / super-property / section / Ontology …)."""
        action = field.meta.get(_LIT_ACTION, "")
        prompt = f"Delete «{data.label_of(self.tax, uri, self.lang)}»?"

        def _on_choice(mode: str | None) -> None:
            if mode is None:
                return
            target = self._delete_focus_target(uri)  # capture before the tree is rebuilt
            self._run_or_warn(edits.delete_command(action, uri, path, mode))
            self._focus_after_delete(target)

        self.push_screen(ChoiceModal(prompt, edits.DELETE_CHOICES[action], danger=True), _on_choice)

    def _delete_focus_target(self, uri: str) -> str | None:
        """The tree node to focus after *uri* is deleted: its parent in the hierarchy. The
        property tree is flat, so a sub-property points at its parent property and a
        top-level property at its section; everything else uses its tree parent (which is
        the super-class / broader concept / scheme / Ontology / Taxonomy node)."""
        prop = self.tax.owl_properties.get(uri)
        if prop is not None:
            for parent_prop in prop.sub_property_of:  # a sub-property → its parent property
                if parent_prop in self._uri_nodes:
                    return parent_prop
            return _prop_section_key(prop.prop_type)  # top-level → its section
        node = self._uri_nodes.get(uri)
        parent = node.parent if node is not None else None
        return parent.data if parent is not None else None

    def _focus_after_delete(self, target: str | None) -> None:
        """Move the cursor onto *target* (the deleted entity's parent), keeping it expanded so
        the former-sibling list stays unfolded; clear the pane when there is no parent."""
        node = self._uri_nodes.get(target) if target else None
        if node is None:
            self._show(None)
            return
        node.expand()  # keep the (former sibling) list unfolded — e.g. a class's individuals
        self._reveal_in_tree(target, focus=True)  # type: ignore[arg-type]
        self._show(target)

    def _confirm_convert(self, field: DetailField, uri: str, path: Path) -> None:
        """Confirm a class↔individual punning conversion, then run it (URI is kept)."""
        action = field.meta.get(_LIT_ACTION, "")
        cls = self.tax.owl_classes.get(uri)
        parents = tuple(sorted(cls.sub_class_of)) if cls else ()
        target = "class" if action == "individual_to_class" else "individual"
        prompt = f"Convert «{data.label_of(self.tax, uri, self.lang)}» to an OWL {target}?"

        def _on_choice(choice: str | None) -> None:
            if choice is None:
                return
            self._run_or_warn(edits.convert_command(action, uri, path, choice, parents))
            self._show(uri)  # same URI, now a different kind of entity

        self.push_screen(ChoiceModal(prompt, edits.convert_choices(action, parents)), _on_choice)

    def _pick_relation(self, field: DetailField, uri: str, path: Path) -> None:
        """Pick a target entity for a relation action (add superclass/type/broader/related)."""
        action = field.meta.get(_LIT_ACTION, "")
        prompt, kind = edits.PICKER_ACTIONS[action]
        # Tagging an individual needs a concept to point at — guide the user to make one
        # first rather than showing an empty picker. (Concept-relation actions on concepts
        # can't reach here with zero concepts, so this only bites the tag-an-individual case.)
        if kind == "concept" and not self.tax.concepts:
            self.notify(
                "No concepts yet — create a concept scheme first "
                "(right-click “Taxonomy” → Add concept scheme).",
                severity=_LIT_WARNING,
            )
            return

        def _on_pick(target: str | None) -> None:
            if target is not None:
                self._run_or_warn(edits.relation_command(action, uri, path, target))

        self._open_picker(prompt, kind, uri, _on_pick)

    def _pick_meta_relation(self, field: DetailField, uri: str, path: Path) -> None:
        """Pick a replacement entity for a meta-aware value edit (e.g. change object value)."""
        prompt, kind = edits.META_PICKER_ACTIONS[field.meta.get(_LIT_ACTION, "")]

        def _on_pick(target: str | None) -> None:
            if target is not None:
                self._run_or_warn(edits.meta_relation_command(field, uri, path, target))
            else:
                self._refocus_edited_row()  # cancel → stay on the edited row

        self._open_picker(prompt, kind, uri, _on_pick)

    def _add_property_value(self, field: DetailField, uri: str, path: Path) -> None:
        """Two-step: pick a property, then pick an individual (object) or type a literal."""
        props = sorted(
            ((data.label_of(self.tax, p, self.lang), p) for p in self.tax.owl_properties),
            key=lambda t: t[0].lower(),
        )
        if not props:
            self.notify("No properties defined — create one first.", severity=_LIT_WARNING)
            return

        def _on_prop(prop_uri: str | None) -> None:
            if prop_uri is not None:
                self._collect_value_for(uri, path, prop_uri)

        self.push_screen(
            PickerModal("Add a value — pick a property", props, kind_label="property"), _on_prop
        )

    def _collect_value_for(self, uri: str, path: Path, prop_uri: str) -> None:
        """Step 2 of add-value: object properties pick an individual, others type a literal."""
        prop = self.tax.owl_properties.get(prop_uri)
        if prop is not None and prop.prop_type == "ObjectProperty":

            def _on_target(target: str | None) -> None:
                if target is not None:
                    self._apply_command(edits.add_object_value_command(uri, path, prop_uri, target))

            self._open_picker("Pick the value — an individual", "individual", uri, _on_target)
            return

        def _on_literal(value: str | None) -> None:
            if value:
                self._apply_command(edits.add_literal_value_command(uri, path, prop_uri, value))

        self.push_screen(EditModal("Literal value", "", multiline=True), _on_literal)
