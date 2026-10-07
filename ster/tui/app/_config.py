"""The config modal round-trip: opening it, applying the returned config (plugins, theme, SHACL enforcement, ontology CI writing), and persisting it."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from ster.model import Taxonomy

from .. import data
from ..choice_modal import ChoiceModal
from ..theme import THEME_CYCLE
from ._persistence import _StorePersistence
from ._state import _AppState

_LIT_CONFIGURED: Final = "configured"
_LIT_ENTITY_METADATA_PROPS: Final = "entity_metadata_props"
_LIT_SEMANTICLINT: Final = "semanticlint"
_LIT_WARNING: Final = "warning"


class _ConfigMixin(_AppState):
    """Mixin: the config modal round-trip: opening it, applying the returned config (plugins, theme, SHACL enforcement, ontology CI writing), and persisting it."""

    def action_open_config(self) -> None:
        """Open the global configuration modal (it auto-saves via ConfigModal.Changed)."""
        from ster.annotation_properties import is_annotation_property

        from ..config_modal import ConfigModal

        available = data.languages_in_use(self.tax)
        themes = sorted(self.available_themes)
        self.push_screen(
            ConfigModal(
                self.lang,
                self.configured_langs,
                available,
                themes,
                self.theme,
                metadata_props=self.metadata_props,
                entity_metadata_props=self.entity_metadata_props,
                annotation_verifier=lambda uri: is_annotation_property(self.tax, uri),
                can_declare=self._service is not None and self._path is not None,
                base_uri=self.tax.base_uri(),
                project_path=self._path.parent if self._path is not None else None,
                trace_base_url=self._trace_base_url(),
            )
        )

    def on_config_modal_changed(self, message) -> None:  # type: ignore[no-untyped-def]
        """A setting changed in the config modal → apply it live and persist."""
        self._apply_config(message.result)

    def on_config_modal_write_onto_ci(self, message) -> None:  # type: ignore[no-untyped-def]
        """Export the plugin's quality config to the repo's onto-ci.yml (aligns CI)."""
        if self._path is None:
            self.notify("No file open — can't locate the repo.", severity=_LIT_WARNING)
            return
        from ster.plugins.semanticlint import config

        path = config.write_onto_ci(self._path.parent)
        self.notify(f"Wrote {path.name} (aligned with quality.json).")

    def on_declare_annotation_property(self, message) -> None:  # type: ignore[no-untyped-def]
        """A config-modal predicate was confirmed despite not being a known annotation
        property → declare it locally as an ``owl:AnnotationProperty`` (skip if it is
        already a property of some kind)."""
        uri = message.uri
        if self._path is None or uri in self.tax.owl_properties:
            return
        from ster.core.commands import OwlAddProperty, OwlSetComment

        label = getattr(message, "label", "")
        self._apply_command(OwlAddProperty(self._path, uri, "AnnotationProperty", label, self.lang))
        comment = getattr(message, "comment", "")
        if comment:
            self._apply_command(OwlSetComment(self._path, uri, self.lang, comment))

    #: SHACL enforcement targets for the entity-metadata catalog (user decision:
    #: classes and concepts only — not individuals or properties).
    _ENTITY_SHACL_TARGETS = (
        (
            "http://www.w3.org/2002/07/owl#Class",  # NOSONAR - RDF predicate/property IRI
            "every class",
        ),
        (
            "http://www.w3.org/2004/02/skos/core#Concept",  # NOSONAR - RDF predicate/property IRI
            "every concept",
        ),
    )

    def on_enforce_shacl_requested(self, message) -> None:  # type: ignore[no-untyped-def]
        """A config-tab enforce button toggled → write (or remove) the SHACL rule(s)
        making an annotation property mandatory, then re-lint."""
        import datetime

        from ster.plugins.semanticlint import shapes_author as shacl

        if self._path is None:
            self.notify("Read-only session — open the ontology first.", severity=_LIT_WARNING)
            return
        targets = self._shacl_targets(message.scope)
        if not targets:
            self.notify("No ontology node to enforce on.", severity=_LIT_WARNING)
            return
        shapes_path = shacl.shapes_path_for(self._path)
        if message.enforce:
            today = datetime.date.today().isoformat()
            rules = [
                self._annotation_rule(t, t_label, message.predicate, message.label, today)
                for t, t_label in targets
            ]
            shacl.append_rules(shapes_path, rules)
            self.notify(f"Enforced “{message.label}” via SHACL.")
        else:
            iris = [shacl.shape_iri(t, message.predicate) for t, _ in targets]
            shacl.remove_rules(shapes_path, iris)
            self.notify(f"Removed the SHACL rule for “{message.label}”.")
        self._invalidate_lint()
        self._refresh_lint_async()

    def _shacl_targets(self, scope: str) -> list[tuple[str, str]]:
        """(target_uri, label) pairs for a catalog *scope*: the ontology node, or every
        class + concept."""
        if scope == "ontology":
            ont = self.tax.ontology_uri
            return [(ont, "the ontology")] if ont else []
        return list(self._ENTITY_SHACL_TARGETS)

    def _annotation_rule(
        self, target: str, target_label: str, predicate: str, label: str, date: str
    ):  # type: ignore[no-untyped-def]
        """Build the mandatory rule for *predicate* on *target* — a node rule for the
        ontology, else a class rule."""
        from ster.plugins.semanticlint import shapes_author as shacl

        if target == self.tax.ontology_uri:
            return shacl.mandatory_on_node_rule(
                target, predicate, node_label=target_label, prop_label=label, date=date
            )
        return shacl.mandatory_property_rule(
            target, predicate, target_label=target_label, prop_label=label, date=date
        )

    def _apply_config(self, result: dict) -> None:
        """Apply + persist the chosen languages and theme. Re-renders the detail
        whenever the configured set changes (so new add-label rows appear), and
        offers to purge data for any language that was removed."""
        new_lang = result["display"] or self.lang
        display_changed = new_lang != self.lang
        removed = sorted(set(self.configured_langs) - set(result[_LIT_CONFIGURED]))
        langs_changed = set(self.configured_langs) != set(result[_LIT_CONFIGURED])
        # An entity-metadata catalog edit changes the overview's coverage %, so refresh
        # the detail (but not the tree — icons don't depend on the catalog).
        entity_meta_changed = self._entity_meta_changed(result)
        plugins_changed = self._apply_plugins(result)  # persists + invalidates lint cache
        self.configured_langs = result[_LIT_CONFIGURED]  # exact selection (may be empty)
        self.lang = new_lang
        self._update_lang_indicator()
        self._apply_theme(result)
        self._persist_config(result, new_lang)
        self._refresh_after_config(
            result, display_changed, langs_changed, plugins_changed, entity_meta_changed
        )
        for lang in removed:
            self._maybe_purge_language(lang)

    def _refresh_after_config(
        self,
        result: dict,
        display_changed: bool,
        langs_changed: bool,
        plugins_changed: bool,
        entity_meta_changed: bool,
    ) -> None:
        """Repaint tree / detail / lint to reflect an applied config change."""
        if display_changed:
            self._refresh_search_rows()
        if display_changed or plugins_changed:
            # A plugin toggle flips the lint-feature flags — rebuild so icon colours
            # (and their absence) repaint instead of lingering from the last build.
            self._rebuild_tree()
        if _LIT_SEMANTICLINT in result:  # thresholds / feature toggles changed → re-lint
            self._invalidate_lint()
            self._refresh_lint_async()
        elif display_changed or langs_changed or plugins_changed or entity_meta_changed:
            self._show(self._detail_uri)  # reflect configured-language rows / lint UI / coverage

    @staticmethod
    def _trace_base_url() -> str:
        from ster.api_server import load_server_config

        url, port = load_server_config()
        return f"{url}:{port}"

    def _apply_plugins(self, result: dict) -> bool:
        """Persist plugin enable-states from the config result. Returns True when any
        changed — a signal to invalidate the lint cache and re-render the detail (lint
        rows appear/disappear)."""
        from ster import plugins

        changed = False
        for plugin_id, enabled in result.get("plugins", {}).items():
            if plugins.is_enabled(plugin_id) != bool(enabled):
                plugins.set_enabled(plugin_id, bool(enabled))
                changed = True
        if changed:
            self._invalidate_lint()  # force a recompute with the new active state
        if "mcp_query_trace" in result.get("plugins", {}):
            from ster.query_trace import configure

            directory = (
                self._path.parent / ".ster" / "query-traces"
                if self._path is not None
                else Path(".ster/query-traces")
            )
            configure(bool(result["plugins"]["mcp_query_trace"]), str(directory))
        return changed

    def _apply_theme(self, result: dict) -> None:
        """Live-preview the chosen theme when it is one we know."""
        theme = result.get("theme")
        if theme and theme in self.available_themes:
            self.theme = theme

    def _entity_meta_changed(self, result: dict) -> bool:
        """True when the config result carries an entity-metadata catalog that differs
        from the current one — a signal to refresh the overview's coverage rows."""
        return _LIT_ENTITY_METADATA_PROPS in result and (
            list(result[_LIT_ENTITY_METADATA_PROPS]) != self.entity_metadata_props
        )

    def _persist_config(self, result: dict, new_lang: str) -> None:
        """Save the config modal's settings (theme + metadata catalog globally,
        display + configured languages per-file)."""
        from ster.nav.prefs import (
            _save_lang_pref,
            _save_prefs,
            save_configured_langs,
            save_entity_metadata_props,
            save_metadata_props,
        )

        _save_prefs({"theme": self.theme})  # theme is a global preference
        if "metadata_props" in result:  # the configurable "Add metadata" catalog (global)
            self.metadata_props = list(result["metadata_props"])
            save_metadata_props(self.metadata_props)
        if _LIT_ENTITY_METADATA_PROPS in result:  # the entity-metadata catalog (global)
            self.entity_metadata_props = list(result[_LIT_ENTITY_METADATA_PROPS])
            save_entity_metadata_props(self.entity_metadata_props)
        if _LIT_SEMANTICLINT in result:  # the plugin's global quality config
            from ster.plugins.semanticlint import config

            config.save_config(result[_LIT_SEMANTICLINT])
        if self._path is not None:
            _save_lang_pref(self._path, new_lang)
            save_configured_langs(self._path, self.configured_langs)

    def _maybe_purge_language(self, lang: str) -> None:
        """A configured language was removed: if the file still has data in it,
        ask whether to delete every ⟨lang⟩ literal or keep it."""
        from ster.operations import language_in_use

        if self._service is None or self._path is None or not language_in_use(self.tax, lang):
            return
        path = self._path
        prompt = f"Delete all “{lang}” labels, comments, definitions & scope notes?"

        def _on_choice(choice: str | None) -> None:
            if choice == "delete":
                from ster.core.commands import RemoveLanguage

                self._apply_command(RemoveLanguage(path, lang))

        self.push_screen(
            ChoiceModal(
                prompt, [("Delete all", "delete"), ("Keep them in the file", "keep")], danger=True
            ),
            _on_choice,
        )

    def _make_service(self, taxonomy: Taxonomy, path: Path | None):  # type: ignore[no-untyped-def]
        """Build the TaxonomyService when editing a real file (None = read-only)."""
        if path is None:
            return None
        from ster import graph_layout
        from ster.core.service import TaxonomyService
        from ster.core.validation import SkosValidatorAdapter
        from ster.workspace import TaxonomyWorkspace

        self._workspace = TaxonomyWorkspace.from_taxonomy(taxonomy, path)
        service = TaxonomyService(self._workspace, _StorePersistence(), SkosValidatorAdapter())
        service.add_rename_listener(graph_layout.rename_nodes)  # positions follow renames
        return service

    def action_cycle_theme(self) -> None:
        """Step through the curated theme shortlist (the full list is in the palette)."""
        cycle = [name for name in THEME_CYCLE if name in self.available_themes]
        if not cycle:
            return
        try:
            i = cycle.index(self.theme)
        except ValueError:
            i = -1
        self.theme = cycle[(i + 1) % len(cycle)]
        self.notify(f"Theme: {self.theme}", timeout=2)
