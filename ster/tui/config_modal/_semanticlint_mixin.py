"""``ConfigModal`` mixin: the Semantic Lint tab — feature toggles, quality
thresholds, check-selection filters, and the "export to onto-ci.yml" action."""

from __future__ import annotations

from typing import Final

from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, Input, Static

from ster.tui.check import Check

from ..focus_group import FormGroup
from ._percent import _pct_display, _pct_parse
from ._state import _ModalState

_LIT_CFG_HINT: Final = "cfg-hint"


class _SemanticLintMixin(_ModalState):
    """Semantic Lint tab: install status + titled bordered sections (features,
    thresholds, check selection, CI export)."""

    #: feature toggles surfaced in the Semantic Lint tab (id suffix → label).
    _SL_FEATURES = (
        ("icons", "Colour entity icons by issue severity"),
        ("detail", "Annotate issues in the detail panel"),
        ("quality_block", "Show the Quality & Coverage block"),
        ("check_on_open", "Check the file for errors when it opens"),
        ("enforce", "Enforce properties with SHACL rules (author shapes.ttl)"),
    )
    #: numeric coverage thresholds (0.0–1.0) offered in the Semantic Lint tab.
    _SL_THRESHOLDS = (
        ("min_label_coverage", "Concept prefLabel coverage (QUA001)"),
        ("min_definition_coverage", "Concept definition coverage (QUA002)"),
        ("min_class_label_coverage", "Class label coverage (QUA004)"),
        ("min_property_label_coverage", "Property label coverage (QUA005)"),
    )
    #: threshold name → the quality key holding its per-language "required in" list.
    #: Each maps a label-type coverage to per-language requirements sourced from the
    #: configured languages (definition coverage, QUA002, has no language row).
    _SL_LANG_KEYS = {
        "min_label_coverage": "languages",  # QUA001/QUA003 — concept prefLabel
        "min_class_label_coverage": "class_label_languages",  # QUA004 — class rdfs:label
        "min_property_label_coverage": "property_label_languages",  # QUA005 — property rdfs:label
    }

    @staticmethod
    def _sl_section(title: str, *widgets):  # type: ignore[no-untyped-def]
        """A titled, bordered section for the Semantic Lint tab."""
        section = Vertical(*widgets, classes="cfg-sl-section")
        section.border_title = title
        return section

    def _sl_threshold_rows(self, cfg: dict):  # type: ignore[no-untyped-def]
        """One group per coverage threshold: the ``name  [nn]%`` row and — for label-type
        coverages — its 'required in language' checkbox row, tucked directly beneath."""
        quality = cfg["quality"]
        for name, label in self._SL_THRESHOLDS:
            row = Horizontal(
                Static(label, classes="cfg-sl-label"),
                Input(
                    value=_pct_display(quality.get(name)),
                    id=f"cfg-slthr-{name}",
                    classes="cfg-sl-input cfg-sl-num",
                ),
                Static("%", classes="cfg-sl-pct"),
                classes="cfg-sl-thresh",
            )
            lang_key = self._SL_LANG_KEYS.get(name)
            members = (
                [row, *self._sl_language_row(lang_key, quality.get(lang_key, []))]
                if lang_key
                else [row]
            )
            yield Vertical(*members, classes="cfg-sl-thresh-group")

    def _sl_language_row(self, lang_key: str, required: list):  # type: ignore[no-untyped-def]
        """A 'required in' row for a label type: one checkbox per configured language
        (checked = every entity of this type must carry a label in that language)."""
        if not self._configured:
            yield Static("  (add configured languages in the General tab)", classes=_LIT_CFG_HINT)
            return
        required_set = set(required)
        yield Horizontal(
            Static("required in:", classes="cfg-sl-langcaption"),
            *(
                Check(
                    lang,
                    value=(lang in required_set),
                    id=f"cfg-sllang-{lang_key}-{lang}",
                    classes="cfg-sl-langbox",
                )
                for lang in self._configured
            ),
            classes="cfg-sl-langrow",
        )

    def _semanticlint_widgets(self):  # type: ignore[no-untyped-def]
        """The Semantic Lint tab body: install status + titled bordered sections
        (features, thresholds, check selection, CI export), all inside one FormGroup so
        the arrow keys rove them (one Tab stop, consistent styling).

        Yields a single FormGroup so this also works standalone when the tab is added
        dynamically via TabbedContent.add_pane (no `with` compose-context needed)."""
        from ster.plugins.semanticlint import config, deps

        cfg = config.load_config()
        sections: list = []
        if not deps.is_installed():
            sections.append(
                Static(
                    "[yellow]semanticlint is not installed.[/] Run: pip install 'ster[semanticlint]'",
                    classes=_LIT_CFG_HINT,
                )
            )
        sections.append(
            self._sl_section(
                "Features",
                *(
                    Check(label, value=cfg["features"].get(name, True), id=f"cfg-slfeat-{name}")
                    for name, label in self._SL_FEATURES
                ),
            )
        )
        sections.append(self._sl_section("Quality thresholds (%)", *self._sl_threshold_rows(cfg)))
        sections.append(
            self._sl_section(
                "Check selection",
                Static("Run only these checks (ids/prefixes)", classes="cfg-label"),
                Input(
                    value=", ".join(cfg["select"]),
                    id="cfg-slselect",
                    classes="cfg-sl-input cfg-sl-text",
                ),
                Static("Ignore these checks (ids/prefixes)", classes="cfg-label"),
                Input(
                    value=", ".join(cfg["ignore"]),
                    id="cfg-slignore",
                    classes="cfg-sl-input cfg-sl-text",
                ),
            )
        )
        sections.append(
            self._sl_section(
                "GitHub Actions CI",
                Static(
                    "onto-ci.yml drives GitHub CI — export the above to align it:",
                    classes=_LIT_CFG_HINT,
                ),
                Button("Write onto-ci.yml", id="cfg-sl-export", classes="cfg-mp-new"),
            )
        )
        yield FormGroup(*sections, id="cfg-sl-group")

    def _semanticlint_result(self) -> dict:
        """The Semantic Lint tab's config (features + thresholds) for persistence."""
        features = {
            name: self.query_one(f"#cfg-slfeat-{name}", Checkbox).value
            for name, _ in self._SL_FEATURES
        }
        quality: dict = {}
        for name, _ in self._SL_THRESHOLDS:
            pct = _pct_parse(self.query_one(f"#cfg-slthr-{name}", Input).value)
            if pct is not None:  # blank/invalid → leave unset → keeps the stored/default value
                quality[name] = pct
        # Per-language "required in" lists — the checked configured languages per label
        # type (replaces the old comma-separated QUA003 field; scoped to configured langs).
        if self._configured:
            for lang_key in self._SL_LANG_KEYS.values():
                quality[lang_key] = [
                    lang
                    for lang in self._configured
                    if self.query_one(f"#cfg-sllang-{lang_key}-{lang}", Checkbox).value
                ]
        return {
            "features": features,
            "quality": quality,
            "select": self._csv("#cfg-slselect"),
            "ignore": self._csv("#cfg-slignore"),
        }

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.has_class("cfg-sl-input"):
            self._save()  # thresholds / languages / select / ignore changed → persist

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "cfg-sl-export":
            return
        event.stop()
        self._save()  # ensure quality.json reflects the current inputs first
        self.post_message(self.WriteOntoCi())
