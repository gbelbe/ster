"""Ontology-level identity edits (base URI/prefix rename) and adding ontology/entity annotations or a new SKOS scheme."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from textual.widget import Widget

from ster.nav.logic import DetailField

from .. import edits
from ..choice_modal import ChoiceModal
from ..edit_modal import EditModal
from ..ontology_identity_modal import OntologyIdentityModal
from ..picker_modal import PickerModal
from ._state import _AppState

_LIT_PREFIX: Final = "prefix"


class _OntologyIdentityMixin(_AppState):
    """Mixin: ontology-level identity edits (base URI/prefix rename) and adding ontology/entity annotations or a new SKOS scheme."""

    def _edit_ontology_identity(self, field: DetailField, uri: str, path: Path) -> None:
        """Edit the ontology base URI (or its domain), cascading across every entity."""
        from ster.operations import ontology_domain

        is_domain = field.meta.get("action") == "edit_ontology_domain"
        if not is_domain:  # base URI → dedicated separator picker + impact confirm
            self._edit_ontology_uri(path, origin=self.focused)
            return
        prompt = "Ontology domain (host)"
        prefill = field.value or ontology_domain(self.tax)
        origin = self.focused

        def _on_submit(value: str | None) -> None:
            if not value:
                if origin is not None:
                    origin.focus()
                return
            base = self._resolve_domain_base(value)
            if base is not None:
                self._apply_command(edits.ontology_rename_command(path, base))

        self.push_screen(EditModal(prompt, prefill), _on_submit)

    def _resolve_domain_base(self, value: str) -> str | None:
        """The new base URI (with separator) for a host swap, or None if invalid."""
        from ster.operations import count_domain_rename_changes, validate_domain

        err = validate_domain(value)
        if err:
            self.notify(err, severity="error")
            return None
        return count_domain_rename_changes(self.tax, value)[1]  # new_base, sep included

    def _edit_ontology_uri(self, path: Path, origin: Widget | None = None) -> None:
        """Open the ontology-identity modal (domain / path / sep / prefix)."""
        scheme, domain, ont_path, sep, prefix = self._ontology_identity_parts()

        def _on_done(result: dict | None) -> None:
            if result is None:
                if origin is not None:
                    origin.focus()
                return
            self._apply_identity_changes(path, scheme, result, prefix, origin)

        self.push_screen(
            OntologyIdentityModal(domain=domain, path=ont_path, sep=sep, prefix=prefix), _on_done
        )

    def _ontology_identity_parts(self) -> tuple[str, str, str, str, str]:
        """Decompose the ontology URI into (scheme, domain, path, sep, prefix)."""
        from urllib.parse import urlsplit

        from ster.domain.onto import ontology_prefix

        root = (self.tax.ontology_uri or "").rstrip("#/")
        sep = "#"
        for u in list(self.tax.owl_classes) + list(self.tax.owl_individuals):
            if len(u) > len(root) and u.startswith(root) and u[len(root)] in ("#", "/"):
                sep = u[len(root)]
                break
        parts = urlsplit(root)
        return (
            parts.scheme or "https",
            parts.netloc,
            parts.path.strip("/"),
            sep,
            ontology_prefix(self.tax) or "",
        )

    def _apply_identity_changes(
        self, path: Path, scheme: str, result: dict, old_prefix: str, origin: Widget | None
    ) -> None:
        """Recompose the URI; confirm + cascade the rename, then set the prefix."""
        from ster.operations import count_ontology_rename_changes

        new_root = f"{scheme}://{result['domain']}"
        if result["path"]:
            new_root += "/" + result["path"]
        sep = result["sep"]
        old_base, new_base, count = count_ontology_rename_changes(self.tax, new_root, sep)
        prefix_changed = result[_LIT_PREFIX] != (old_prefix or "")

        def _set_prefix() -> None:
            if prefix_changed and result[_LIT_PREFIX]:
                self._apply_command(
                    edits.action_command("edit_ontology_prefix", "", path, result[_LIT_PREFIX])
                )

        if old_base != new_base:  # URI changed → confirm the cascade first
            noun = "entity" if count == 1 else "entities"
            prompt = f"Rename → {new_base}   ·   {count} {noun} updated"

            def _on_confirm(choice: str | None) -> None:
                if choice == "ok":
                    self._apply_command(edits.ontology_rename_command(path, new_root + sep))
                    _set_prefix()
                elif origin is not None:
                    origin.focus()

            self.push_screen(ChoiceModal(prompt, [("Confirm rename", "ok")]), _on_confirm)
        elif prefix_changed:
            _set_prefix()
        elif origin is not None:
            origin.focus()

    def _add_ont_annotation(self, field: DetailField, uri: str, path: Path) -> None:
        """Two-step: pick a predicate from the catalog, then enter the value."""
        from ster.nav.logic import annotation_catalog_options

        options = annotation_catalog_options(self.tax, self.metadata_props)
        if not options:
            self.notify("All known annotation predicates are already present.", severity="warning")
            return

        # PickerModal expects (label, value) — use the display label, value is the predicate URI.
        picker_options = [(label, pred) for pred, label in options]

        def _on_predicate(predicate: str | None) -> None:
            if not predicate:
                return

            def _on_value(value: str | None) -> None:
                if value:
                    from ster.core.commands import OntoSetAnnotation

                    self._apply_command(OntoSetAnnotation(path, predicate, "", value))

            # Derive a short prompt from the label (strip the parenthetical hint).
            label = next((lbl for pred, lbl in options if pred == predicate), predicate)
            short = label.split("  ")[0]
            self.push_screen(EditModal(f"Value for {short}", ""), _on_value)

        self.push_screen(
            PickerModal("Add metadata — pick a predicate", picker_options), _on_predicate
        )

    def _add_entity_annotation(self, field: DetailField, uri: str, path: Path) -> None:
        """Add a configured annotation to the shown entity — the predicate is known from the
        affordance's meta, so a single value-input modal completes it."""
        from ster.core.commands import EntitySetAnnotation
        from ster.nav.logic import _annotation_display

        predicate = field.meta.get("predicate", "")
        is_iri = bool(field.meta.get("is_iri"))
        short = _annotation_display(predicate)

        def _on_value(value: str | None) -> None:
            if value:
                self._apply_command(EntitySetAnnotation(path, uri, predicate, value, is_iri=is_iri))

        self.push_screen(EditModal(f"Value for {short}", ""), _on_value)

    def _create_scheme(self, field: DetailField, uri: str, path: Path) -> None:
        """Two-step: collect the scheme title, then its URI, and create it."""

        def _on_title(title: str | None) -> None:
            if not title:
                return

            def _on_uri(scheme_uri: str | None) -> None:
                if scheme_uri:
                    self._apply_command(
                        edits.create_scheme_command(path, scheme_uri, title, self.lang)
                    )

            self.push_screen(EditModal("Scheme URI", self.tax.base_uri()), _on_uri)

        self.push_screen(EditModal(f"Scheme title [{self.lang}]", ""), _on_title)
