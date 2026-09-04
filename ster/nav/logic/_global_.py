"""Backward-compat aliases, the scheme dashboard, and the global (multi-taxonomy) overview."""

from __future__ import annotations

from typing import Final

from ...analysis_base import pct_bar as _pct_bar
from ...model import OWLIndividual, Taxonomy
from ...owl_analysis import (
    compute_owl_analysis,
)
from ...taxonomy_analysis import SchemeAnalysis
from ...workspace import TaxonomyWorkspace
from . import _concept, _fields, _tree

_LIT_ACTION: Final = "action"


def build_detail_fields(
    taxonomy: Taxonomy,
    uri: str,
    lang: str,
    show_mappings: bool = False,  # noqa: ARG001 - retained for backward compatibility  # NOSONAR - same reason
) -> list[_fields.DetailField]:
    """Backward-compat alias for _concept.build_concept_detail."""
    return _concept.build_concept_detail(taxonomy, uri, lang)


def _display_lang_field(lang: str) -> _fields.DetailField:
    """Shared 'display language' action field used in every detail panel."""
    return _fields.DetailField(
        "display_lang",
        "display language",
        lang,
        editable=False,
        meta={"type": _LIT_ACTION, _LIT_ACTION: "pick_lang"},
    )


def _scheme_langs(scheme) -> set[str]:
    langs: set[str] = set()
    for lbl in scheme.labels:
        langs.add(lbl.lang)
    for desc in scheme.descriptions:
        langs.add(desc.lang)
    langs.update(scheme.languages)
    return langs


def _concept_langs(taxonomy: Taxonomy) -> set[str]:
    langs: set[str] = set()
    for concept in taxonomy.concepts.values():
        for lbl in concept.labels:
            langs.add(lbl.lang)
        for defn in concept.definitions:
            langs.add(defn.lang)
    return langs


def _owl_entity_langs(taxonomy: Taxonomy) -> set[str]:
    langs: set[str] = set()
    for cls in taxonomy.owl_classes.values():
        for lbl in cls.labels:
            langs.add(lbl.lang)
    for ind in taxonomy.owl_individuals.values():
        for lbl in ind.labels:
            langs.add(lbl.lang)
    for prop in taxonomy.owl_properties.values():
        for lbl in prop.labels:
            langs.add(lbl.lang)
    return langs


def _available_langs(taxonomy: Taxonomy) -> list[str]:
    """Return sorted list of all language codes present in the taxonomy."""
    langs: set[str] = set()
    scheme = taxonomy.primary_scheme()
    if scheme:
        langs |= _scheme_langs(scheme)
    langs |= _concept_langs(taxonomy)
    langs |= _owl_entity_langs(taxonomy)
    return sorted(langs)


def build_scheme_fields(
    taxonomy: Taxonomy,
    lang: str,
    scheme_uri: str | None = None,
) -> list[_fields.DetailField]:
    """Compat alias with old arg order: (taxonomy, lang, scheme_uri=None)."""
    if scheme_uri is None:
        scheme = taxonomy.primary_scheme()
        if not scheme:
            return []
        scheme_uri = scheme.uri
    return _concept.build_scheme_detail(taxonomy, scheme_uri, lang)


def _load_bearer_token() -> str:
    """Return the persisted bearer token, or a placeholder if not yet created."""
    from ...api_server import _TOKEN_FILE  # noqa: PLC0415

    if _TOKEN_FILE.exists():
        return _TOKEN_FILE.read_text().strip()
    return "(not yet created — launch ster view first)"


_HELP_HINTS: list[tuple[str, str]] = [
    ("↑ ↓  /  j k", "navigate tree"),
    ("Enter", "focus detail panel"),
    ("← / Esc", "back"),
    ("Space", "fold / unfold subtree"),
    ("+ / a / A", "add narrower / child / top concept"),
    ("/", "search"),
    ("m", "move concept"),
    ("b", "add broader link"),
    ("g / G", "jump to first / last"),
    ("?", "full help screen"),
    ("q", "quit"),
]


def _direct_class_individuals(
    taxonomy: Taxonomy,
    class_uri: str,
    lang: str,
    exclude_uri: str,
    added_ind_uris: set[str],
) -> list[tuple[str, OWLIndividual]]:
    return sorted(
        [
            (uri, ind)
            for uri, ind in taxonomy.owl_individuals.items()
            if uri != exclude_uri and uri not in added_ind_uris and class_uri in ind.types
        ],
        key=lambda kv: kv[1].label(lang),
    )


def _add_individual_candidate_group(
    taxonomy: Taxonomy,
    lang: str,
    exclude_uri: str,
    candidates: list[tuple[str, str]],
    added_ind_uris: set[str],
    seen_class_uris: set[str],
    class_uri: str,
    depth: int,
) -> None:
    """Recursively append a class's header row, its subclasses, then its direct individuals."""
    if class_uri in seen_class_uris:
        return
    seen_class_uris.add(class_uri)

    cls = taxonomy.owl_classes.get(class_uri)
    cls_lbl = cls.label(lang) if cls else class_uri
    indent = "  " * depth

    sub_uris = sorted(u for u, c in taxonomy.owl_classes.items() if class_uri in c.sub_class_of)
    direct_inds = _direct_class_individuals(taxonomy, class_uri, lang, exclude_uri, added_ind_uris)

    if not sub_uris and not direct_inds:
        return

    candidates.append((f"__HDR__:{class_uri}", f"{indent}▸ {cls_lbl}"))

    for sub_uri in sub_uris:
        _add_individual_candidate_group(
            taxonomy,
            lang,
            exclude_uri,
            candidates,
            added_ind_uris,
            seen_class_uris,
            sub_uri,
            depth + 1,
        )

    for i_uri, ind in direct_inds:
        if i_uri not in added_ind_uris:
            h = taxonomy.uri_to_handle(i_uri) or "?"
            lbl = ind.label(lang)
            candidates.append((i_uri, f"{indent}  [{h}]  {lbl}"))
            added_ind_uris.add(i_uri)


def build_individual_candidates_grouped(
    taxonomy: Taxonomy,
    lang: str,
    prop_ranges: list[str],
    exclude_uri: str,
) -> list[tuple[str, str]]:
    """Return grouped (uri, label) candidates for an individual-value picker.

    When *prop_ranges* is non-empty only individuals from those classes and
    their subclasses are included.  When empty every class is searched.
    Header rows have a ``__HDR__:<class_uri>`` sentinel URI and are not
    selectable.  *exclude_uri* is omitted from results (the source individual).
    """
    range_roots: list[str] = list(prop_ranges) if prop_ranges else sorted(taxonomy.owl_classes)

    candidates: list[tuple[str, str]] = []
    added_ind_uris: set[str] = set()
    seen_class_uris: set[str] = set()

    for root in range_roots:
        _add_individual_candidate_group(
            taxonomy, lang, exclude_uri, candidates, added_ind_uris, seen_class_uris, root, 0
        )

    return candidates


def _global_server_fields(
    lang: str,
    server_url: str,
    server_port: int,
    show_token: bool,
    pending_restart: bool,
    ontology_slug: str | None,
) -> list[_fields.DetailField]:
    fields = [_fields._sep("Local Server Configuration")]
    if pending_restart:
        fields.append(
            _fields.DetailField(
                "server:restart_warning",
                "⚠ restart required",
                "close browser tabs then relaunch ster",
                editable=False,
                meta={"type": "warning"},
            )
        )
    fields.extend(
        [
            _fields.DetailField(
                "server:url",
                "server URL",
                server_url,
                editable=False,
                meta={"type": _LIT_ACTION, _LIT_ACTION: "edit_server_url"},
            ),
            _fields.DetailField(
                "server:port",
                "port",
                str(server_port),
                editable=False,
                meta={"type": _LIT_ACTION, _LIT_ACTION: "edit_server_port"},
            ),
            _fields.DetailField(
                "server:token",
                "bearer token",
                _load_bearer_token() if show_token else "***",
                editable=False,
                meta={"type": _LIT_ACTION, _LIT_ACTION: "show_bearer_token"},
            ),
        ]
    )
    if ontology_slug is not None:
        host = server_url.rstrip("/")
        fields.extend(
            [
                _fields._stat(
                    "ontology:serving_url",
                    "ontology serving URL",
                    f"{host}:{server_port}/{ontology_slug}",
                ),
                _fields._stat("ontology:viz_url", "VoWL graph URL", f"{host}:{server_port}/viz"),
            ]
        )
    # The display-language picker is not an LLM concern; it outlived the
    # "LLM Setup" section that used to house it.
    fields.extend([_fields._sep("Display"), _display_lang_field(lang)])
    return fields


def _global_taxonomy_counts(all_taxes: list[Taxonomy]) -> tuple[int, int, int]:
    return (
        sum(len(t.schemes) for t in all_taxes),
        sum(len(t.concepts) for t in all_taxes),
        sum(len(t.owl_classes) for t in all_taxes),
    )


def _global_languages(all_taxes: list[Taxonomy]) -> str:
    languages = {
        label.lang
        for taxonomy in all_taxes
        for concept in taxonomy.concepts.values()
        for label in concept.labels
        if label.value
    }
    return ", ".join(sorted(languages)) if languages else "—"


def _global_overview_fields(
    workspace: TaxonomyWorkspace,
) -> tuple[list[_fields.DetailField], list[Taxonomy], int, int]:
    all_taxes = list(workspace.taxonomies.values())
    n_schemes, n_concepts, n_owl = _global_taxonomy_counts(all_taxes)
    fields = [
        _fields._sep("Overview"),
        _fields._stat("g:files", "taxonomy files", str(len(workspace.taxonomies))),
    ]
    optional_stats = (
        (n_schemes, "g:schemes", "concept schemes"),
        (n_concepts, "g:concepts", "total concepts"),
        (n_owl, "g:owl", "OWL classes"),
    )
    fields.extend(
        _fields._stat(key, label, str(count)) for count, key, label in optional_stats if count
    )
    fields.append(_fields._stat("g:langs", "languages", _global_languages(all_taxes)))
    return fields, all_taxes, n_schemes, n_owl


def _global_owl_missing_counts(all_taxes: list[Taxonomy]) -> tuple[int, int]:
    missing_lbl = sum(sum(1 for cls in t.owl_classes.values() if not cls.labels) for t in all_taxes)
    missing_cmt = sum(
        sum(1 for cls in t.owl_classes.values() if not cls.comments) for t in all_taxes
    )
    return missing_lbl, missing_cmt


def _global_owl_counts(all_taxes: list[Taxonomy]) -> tuple[int, int, int, int, int]:
    n_owl = sum(len(t.owl_classes) for t in all_taxes)
    n_promoted = sum(sum(uri in t.concepts for uri in t.owl_classes) for t in all_taxes)
    max_depth = max(
        (compute_owl_analysis(t).max_depth for t in all_taxes if t.owl_classes),
        default=0,
    )
    missing_lbl, missing_cmt = _global_owl_missing_counts(all_taxes)
    return n_owl, n_promoted, max_depth, missing_lbl, missing_cmt


def _global_owl_missing_fields(missing_lbl: int, missing_cmt: int) -> list[_fields.DetailField]:
    fields: list[_fields.DetailField] = []
    if missing_lbl:
        fields.append(_fields._stat("owl:miss_lbl", "missing rdfs:label", str(missing_lbl)))
    if missing_cmt:
        fields.append(_fields._stat("owl:miss_cmt", "missing rdfs:comment", str(missing_cmt)))
    return fields


def _global_owl_fields(all_taxes: list[Taxonomy], n_owl: int) -> list[_fields.DetailField]:
    if not n_owl:
        return []
    _, n_promoted, max_depth, missing_lbl, missing_cmt = _global_owl_counts(all_taxes)
    n_pure = n_owl - n_promoted
    fields = [_fields._sep("OWL Classes")]
    if n_promoted:
        fields.append(_fields._stat("owl:promoted", "promoted (concept+class)", str(n_promoted)))
    if n_pure:
        fields.append(_fields._stat("owl:pure", "pure classes", str(n_pure)))
    fields.append(_fields._stat("owl:depth", _tree._MAX_DEPTH, str(max_depth)))
    fields.extend(_global_owl_missing_fields(missing_lbl, missing_cmt))
    return fields


def _aggregate_completions(
    analysis: dict[str, SchemeAnalysis],
) -> dict[str, tuple[str, int, dict[str, int]]]:
    aggregate: dict[str, tuple[str, int, dict[str, int]]] = {}
    for scheme_analysis in analysis.values():
        for completion in scheme_analysis.completions:
            display, total, by_language = aggregate.get(
                completion.property_key, (completion.display_name, 0, {})
            )
            by_language = {**by_language}
            total += completion.total
            for language, count in completion.by_language.items():
                by_language[language] = by_language.get(language, 0) + count
            aggregate[completion.property_key] = (display, total, by_language)
    return aggregate


def _completion_field(
    prop_key: str, display: str, total: int, by_language: dict[str, int]
) -> _fields.DetailField | None:
    if not total:
        return None
    best_count = max(by_language.values(), default=0)
    best_pct = int(best_count * 100 / total)
    language_parts = [
        f"[{language}] {int(count * 100 / total)}%"
        for language, count in sorted(by_language.items())
    ]
    value = (
        f"{_pct_bar(best_pct)}  " + "  ".join(language_parts)
        if language_parts
        else _pct_bar(best_pct)
    )
    return _fields._stat(f"g:comp:{prop_key}", display, value)


def _global_completion_fields(
    analysis: dict[str, SchemeAnalysis],
) -> list[_fields.DetailField]:
    aggregate = _aggregate_completions(analysis)
    fields = [
        field
        for key, (display, total, by_language) in aggregate.items()
        if (field := _completion_field(key, display, total, by_language)) is not None
    ]
    return [_fields._sep("Completeness"), *fields] if fields else []


def _global_issue_fields(analysis: dict[str, SchemeAnalysis]) -> list[_fields.DetailField]:
    total_errors = sum(
        sum(issue.severity == "error" for issue in scheme_analysis.issues)
        for scheme_analysis in analysis.values()
    )
    total_warnings = sum(
        sum(issue.severity == "warning" for issue in scheme_analysis.issues)
        for scheme_analysis in analysis.values()
    )
    fields = [_fields._sep("Quality")]
    if not total_errors and not total_warnings:
        return [*fields, _fields._stat("g:issues:ok", "✓ no issues", "")]
    if total_errors:
        fields.append(_fields._stat("g:errors", "⊘ errors", str(total_errors)))
    if total_warnings:
        fields.append(_fields._stat("g:warnings", "⚠ warnings", str(total_warnings)))
    return fields


def _global_analysis_fields(
    n_schemes: int,
    analysis: dict[str, SchemeAnalysis] | None,
) -> list[_fields.DetailField]:
    if not n_schemes:
        return []
    if not analysis:
        return [
            _fields._sep("Completeness & Quality"),
            _fields._stat("g:pending", "analysis", "loading…"),
        ]
    return [*_global_completion_fields(analysis), *_global_issue_fields(analysis)]


def build_global_fields(
    workspace: TaxonomyWorkspace | None,
    analysis: dict[str, SchemeAnalysis] | None,
    lang: str,
    server_url: str = "http://127.0.0.1",  # NOSONAR - local-only address, not a network destination
    server_port: int = 8765,
    show_token: bool = False,
    pending_restart: bool = False,
    ontology_slug: str | None = None,
) -> list[_fields.DetailField]:
    """Build _fields.DetailField list for the global overview panel.

    When *workspace* is None only the Local Server Configuration and Display
    sections are included (used by the standalone config screen).
    """

    fields = _global_server_fields(
        lang, server_url, server_port, show_token, pending_restart, ontology_slug
    )
    if workspace is not None:
        fields.append(_fields._sep("Keyboard Shortcuts"))
        fields.extend(_fields._stat(f"help:{keys}", keys, desc) for keys, desc in _HELP_HINTS)
        overview, all_taxes, n_schemes, n_owl = _global_overview_fields(workspace)
        fields.extend(overview)
        fields.extend(_global_owl_fields(all_taxes, n_owl))
        fields.extend(_global_analysis_fields(n_schemes, analysis))
        fields.extend(
            [
                _fields._sep("Graph"),
                _fields._add_action_field(
                    "action:view_ontology_graph", "⊙ View graph in browser", "view_ontology_graph"
                ),
            ]
        )
    return fields
