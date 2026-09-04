"""Ontology/taxonomy overview panels, the annotation catalog, and summary stats fields."""

from __future__ import annotations

from typing import Final

from ...analysis_base import pct as _pct
from ...metadata_coverage import MetaProp
from ...metadata_coverage import is_labelled as _is_labelled
from ...model import OntologyAnnotation, Taxonomy
from ...owl_analysis import (
    ONTOLOGY_ISSUE_DISPLAY_NAMES,
    OntologyAnalysis,
    compute_ontology_analysis,
)
from . import _fields, _global_, _tree

_LIT_ACTION: Final = "action"
_LIT_TOTAL: Final = "total"


def _ontology_quality_fields(
    taxonomy: Taxonomy,
    analysis: OntologyAnalysis,
    lang: str,
) -> list[_fields.DetailField]:
    """Quality stat sections for the ontology overview panel.

    Rendered by the shared _coverage_fields / _fields._issue_nav_fields helpers, so
    any layout or color change there applies here and to the SKOS dashboard.
    """
    fields: list[_fields.DetailField] = []
    st = analysis.stats

    # ── Classes ───────────────────────────────────────────────────────────────
    fields.append(_fields._sep("Class Quality"))
    fields.append(_fields._stat("ont:q:classes", "total classes", str(st.total_classes)))
    fields.append(_fields._stat("ont:q:roots", "root classes", str(st.root_classes)))
    fields.append(_fields._stat("ont:q:depth", _tree._MAX_DEPTH, str(st.max_depth)))
    if st.total_classes:
        fields.append(_fields._pct_stat("ont:q:lbl", _tree._RDFS_LABEL, st.label_pct))
        fields.append(_fields._pct_stat("ont:q:cmt", "rdfs:comment", st.comment_pct))

    # ── By level ──────────────────────────────────────────────────────────────
    if analysis.level_summaries:
        fields.append(_fields._sep("By Level"))
        for ls in analysis.level_summaries:
            n = ls.n_classes
            plural = "classes" if n != 1 else "class"
            fields.append(
                _fields._pct_stat(
                    f"ont:q:lvl:{ls.depth}",
                    f"depth {ls.depth}",
                    ls.label_pct,
                    prefix=f"{n} {plural}  ·  ",
                    suffix=" labeled",
                )
            )

    # ── Individuals ───────────────────────────────────────────────────────────
    if st.total_individuals:
        fields.append(_fields._sep("Individual Quality"))
        fields.append(_fields._stat("ont:q:inds", _LIT_TOTAL, str(st.total_individuals)))
        fields.append(_fields._pct_stat("ont:q:ind_lbl", "labeled", st.individual_label_pct))
        fields.append(_fields._pct_stat("ont:q:ind_typed", "typed", st.individual_typed_pct))

    # ── Properties ────────────────────────────────────────────────────────────
    if st.total_properties:
        fields.append(_fields._sep("Property Quality"))
        fields.append(_fields._stat("ont:q:props", _LIT_TOTAL, str(st.total_properties)))
        fields.append(_fields._pct_stat("ont:q:prop_lbl", "labeled", st.property_label_pct))
        fields.append(
            _fields._pct_stat("ont:q:prop_dom", "has domain", st.property_with_domain_pct)
        )
        fields.append(_fields._pct_stat("ont:q:prop_rng", "has range", st.property_with_range_pct))

    # ── Property fill rates ────────────────────────────────────────────────────
    if analysis.property_fill_global:
        fields.append(_fields._sep("Property Fill Rate"))
        for p_uri, fill in sorted(analysis.property_fill_global.items(), key=lambda kv: kv[1]):
            prop = taxonomy.owl_properties.get(p_uri)
            lbl = prop.label(lang) if prop else p_uri
            fill_pct = int(fill * 100)
            fields.append(_fields._pct_stat(f"ont:q:fill:{p_uri}", lbl, fill_pct))

    # ── Issues ────────────────────────────────────────────────────────────────
    fields.append(_fields._sep("Issues"))
    fields.extend(
        _fields._issue_nav_fields(
            analysis.issues, ONTOLOGY_ISSUE_DISPLAY_NAMES, key_prefix="owl_issue"
        )
    )

    return fields


def _ontology_identity_action_fields(taxonomy: Taxonomy) -> list[_fields.DetailField]:
    """Edit-base-URI plus, for http(s) ontologies, edit-domain / edit-prefix actions."""
    actions = [
        _fields._add_action_field(
            "action:edit_ontology_uri", "✎ Edit base URI", "edit_ontology_uri"
        )
    ]
    if (taxonomy.ontology_uri or "").startswith(
        (
            "http://",  # NOSONAR - scheme prefix, not a URL
            "https://",
        )
    ):
        actions.append(
            _fields._add_action_field(
                "action:edit_ontology_domain", "✎ Edit domain", "edit_ontology_domain"
            )
        )
        actions.append(
            _fields._add_action_field(
                "action:edit_ontology_prefix", "✎ Edit prefix", "edit_ontology_prefix"
            )
        )
    return actions


def _tui_ontology_separator(taxonomy: Taxonomy, root: str) -> str:
    """The base-URI separator: the raw trailing #/ if any, else detected from
    existing entity URIs, else ``#``."""
    raw = taxonomy.ontology_uri or ""
    if raw[-1:] in ("#", "/"):
        return raw[-1]
    for u in list(taxonomy.owl_classes) + list(taxonomy.owl_individuals):
        if len(u) > len(root) and u.startswith(root) and u[len(root)] in ("#", "/"):
            return u[len(root)]
    return "#"


def _tui_identity_rows(taxonomy: Taxonomy) -> list[_fields.DetailField]:
    """New-TUI overview identity: one line showing the full base URI (with its
    ``#`` / ``/`` separator) and the prefix. Activating it opens the identity
    modal, which edits the domain / path / separator / prefix as independent fields.
    """
    raw = taxonomy.ontology_uri
    if not raw:
        return []
    if not raw.startswith(("http://", "https://")):  # NOSONAR - scheme prefix, not a URL
        value = raw  # non-http: show as-is, no separator/prefix decomposition
    else:
        from ster.domain.onto import ontology_prefix

        root = raw.rstrip("#/")
        full = root + _tui_ontology_separator(taxonomy, root)
        prefix = ontology_prefix(taxonomy) or ""
        value = f"{full}   ·   prefix: {prefix or 'none'}"
    return [
        _fields.DetailField(
            "ont:uri",
            "URI",
            value,
            editable=False,
            meta={"type": "uri", _LIT_ACTION: "edit_ontology_uri"},
        )
    ]


def _overview_metadata_fields(taxonomy: Taxonomy, lang: str) -> list[_fields.DetailField]:
    """Setup + ontology-metadata rows (URI, identity actions, version, title…)."""
    fields = [_fields._sep("Setup"), _global_._display_lang_field(lang), _fields._sep("Ontology")]
    if taxonomy.ontology_uri:
        fields.append(
            _fields.DetailField(
                "ont:uri", "URI", taxonomy.ontology_uri, editable=False, meta={"type": "uri"}
            )
        )
        fields.extend(_ontology_identity_action_fields(taxonomy))
    if taxonomy.version_info:
        fields.append(
            _fields.DetailField(
                "ont:version_info",
                "version",
                taxonomy.version_info,
                editable=False,
                meta={"type": "stat"},
            )
        )
    if taxonomy.ontology_label:
        fields.append(
            _fields.DetailField(
                "ont:label",
                "label",
                taxonomy.ontology_label,
                editable=True,
                meta={"type": "ont_label"},
            )
        )
    fields.append(
        _fields.DetailField(
            "ont:title",
            "dcterms:title",
            taxonomy.ontology_title or "",
            editable=True,
            meta={"type": "ont_title"},
        )
    )
    fields.append(
        _fields.DetailField(
            "ont:description",
            "dcterms:description",
            taxonomy.ontology_description or "",
            editable=True,
            meta={"type": "ont_description"},
        )
    )
    return fields


def _overview_action_fields() -> list[_fields.DetailField]:
    """Creation / view actions shown on the ontology overview."""
    return [
        _fields._sep("Actions"),
        _fields._add_action_field(
            "action:view_ontology_graph", "⊙ View graph in browser", "view_ontology_graph"
        ),
        _fields._add_action_field("action:create_owl_class", "+ New OWL class", "create_owl_class"),
        _fields._add_action_field(
            "action:create_owl_property", "+ New OWL property", "create_owl_property"
        ),
        _fields._add_action_field("action:add_scheme", "➕ Add concept scheme", "add_scheme"),
    ]


def _overview_domain_prop_rows(
    taxonomy: Taxonomy, lang: str, cls_uri: str, props_by_domain: dict[str, list[str]], depth: int
) -> list[_fields.DetailField]:
    """The ``→ property (ranges)`` rows for properties whose domain is *cls_uri*."""
    prop_indent = "  " * (depth + 1)
    rows: list[_fields.DetailField] = []
    for p_uri in sorted(props_by_domain.get(cls_uri, [])):
        prop = taxonomy.owl_properties[p_uri]
        ranges = [
            taxonomy.owl_classes[r].label(lang) if r in taxonomy.owl_classes else r
            for r in prop.ranges
        ]
        range_str = f"  ({', '.join(ranges)})" if ranges else ""
        rows.append(
            _fields.DetailField(
                f"ovw:prop:{cls_uri}:{p_uri}",
                f"{prop_indent}→ {prop.label(lang)}{range_str}",
                "",
                editable=False,
                meta={"type": "prop_nav", "uri": p_uri, "nav": True},
            )
        )
    return rows


def _overview_class_rows(
    taxonomy: Taxonomy,
    lang: str,
    cls_uri: str,
    depth: int,
    children_map: dict[str, list[str]],
    props_by_domain: dict[str, list[str]],
    folded: set[str],
) -> list[_fields.DetailField]:
    """A class row + its domain-property rows, recursing into (unfolded) children."""
    cls = taxonomy.owl_classes[cls_uri]
    children = sorted(children_map.get(cls_uri, []))
    indent = "  " * depth
    if not children:  # leaf class — a plain navigable row
        rows = [
            _fields.DetailField(
                f"ovw:cls:{cls_uri}",
                f"{indent}◈ {cls.label(lang)}",
                "",
                editable=False,
                meta={"type": "rdf_relation", "uri": cls_uri, "nav": True},
            )
        ]
        rows.extend(_overview_domain_prop_rows(taxonomy, lang, cls_uri, props_by_domain, depth))
        return rows
    is_folded_cls = cls_uri in folded
    rows = [
        _fields.DetailField(
            f"ovw:cls:{cls_uri}",
            f"{indent}{'▶' if is_folded_cls else '▼'} {cls.label(lang)}",
            "",
            editable=False,
            meta={"type": _LIT_ACTION, _LIT_ACTION: "toggle_class_fold", "uri": cls_uri},
        )
    ]
    if is_folded_cls:
        return rows
    rows.extend(_overview_domain_prop_rows(taxonomy, lang, cls_uri, props_by_domain, depth))
    for child_uri in children:
        rows.extend(
            _overview_class_rows(
                taxonomy, lang, child_uri, depth + 1, children_map, props_by_domain, folded
            )
        )
    return rows


def _overview_class_maps(
    taxonomy: Taxonomy,
) -> tuple[dict[str, list[str]], list[str], dict[str, list[str]]]:
    """(children_map, sorted root classes, props-by-domain) for the overview tree."""
    children_map: dict[str, list[str]] = {uri: [] for uri in taxonomy.owl_classes}
    for cls_uri, cls in taxonomy.owl_classes.items():
        for parent_uri in cls.sub_class_of:
            if parent_uri in taxonomy.owl_classes:
                children_map[parent_uri].append(cls_uri)
    root_classes = sorted(
        uri
        for uri, cls in taxonomy.owl_classes.items()
        if not any(p in taxonomy.owl_classes for p in cls.sub_class_of)
    )
    props_by_domain: dict[str, list[str]] = {}
    for p_uri, prop in taxonomy.owl_properties.items():
        for domain_uri in prop.domains:
            props_by_domain.setdefault(domain_uri, []).append(p_uri)
    return children_map, root_classes, props_by_domain


def _overview_class_hierarchy_fields(
    taxonomy: Taxonomy, lang: str, folded: set[str]
) -> list[_fields.DetailField]:
    """The folding class tree with each class's domain properties nested under it."""
    if not taxonomy.owl_classes:
        return []
    children_map, root_classes, props_by_domain = _overview_class_maps(taxonomy)
    fields = [_fields._sep("Classes & Properties")]
    for root_uri in root_classes:
        fields.extend(
            _overview_class_rows(taxonomy, lang, root_uri, 0, children_map, props_by_domain, folded)
        )
    return fields


def _overview_all_property_fields(taxonomy: Taxonomy, lang: str) -> list[_fields.DetailField]:
    """A flat list of every property with its domain → range summary."""
    if not taxonomy.owl_properties:
        return []
    fields = [_fields._sep("Properties")]
    for p_uri in sorted(
        taxonomy.owl_properties, key=lambda u: taxonomy.owl_properties[u].label(lang)
    ):
        prop = taxonomy.owl_properties[p_uri]
        domains = [
            taxonomy.owl_classes[d].label(lang) if d in taxonomy.owl_classes else d
            for d in prop.domains
        ]
        ranges = [
            taxonomy.owl_classes[r].label(lang) if r in taxonomy.owl_classes else r
            for r in prop.ranges
        ]
        domain_str = ", ".join(domains) if domains else "—"
        range_str = ", ".join(ranges) if ranges else "—"
        fields.append(
            _fields.DetailField(
                f"ovw:allprop:{p_uri}",
                prop.label(lang) or p_uri,
                f"owl:{prop.prop_type}  {domain_str} → {range_str}",
                editable=False,
                meta={"type": "prop_nav", "uri": p_uri, "nav": True},
            )
        )
    return fields


def build_ontology_overview_fields(
    taxonomy: Taxonomy,
    lang: str,
    folded: set[str] | None = None,
) -> list[_fields.DetailField]:
    """Detail panel for the ontology root node — assembled from section helpers.

    Shows ontology metadata, creation actions, a class hierarchy with
    fold/unfold, all properties, and subtree quality stats.
    """
    folded = folded if folded is not None else set()
    fields = _overview_metadata_fields(taxonomy, lang)
    fields.extend(_overview_action_fields())
    fields.extend(_overview_class_hierarchy_fields(taxonomy, lang, folded))
    fields.extend(_overview_all_property_fields(taxonomy, lang))
    if taxonomy.owl_classes or taxonomy.owl_individuals or taxonomy.owl_properties:
        analysis = compute_ontology_analysis(taxonomy)
        fields.extend(_ontology_quality_fields(taxonomy, analysis, lang))
    return fields


_ANNOTATION_CATALOG: tuple[tuple[str, str], ...] = (
    # dcterms:creator / contributor / created / modified are intentionally omitted:
    # change-tracking provenance (who/what/when of edits) is deferred to a future PROV-O
    # layer that auto-annotates each change, rather than being added by hand here.
    (
        "http://purl.org/dc/terms/publisher",  # NOSONAR - RDF predicate/property IRI
        "dcterms:publisher",
    ),
    (
        "http://purl.org/dc/terms/license",  # NOSONAR - RDF predicate/property IRI
        "dcterms:license  (IRI)",
    ),
    (
        "http://purl.org/dc/terms/language",  # NOSONAR - RDF predicate/property IRI
        "dcterms:language",
    ),
    (
        "http://www.w3.org/2002/07/owl#imports",  # NOSONAR - RDF predicate/property IRI
        "owl:imports  (IRI)",
    ),
    (
        "http://purl.org/vocab/vann/preferredNamespacePrefix",  # NOSONAR - RDF predicate/property IRI
        "vann:preferredNamespacePrefix",
    ),
    (
        "http://purl.org/vocab/vann/preferredNamespaceUri",  # NOSONAR - RDF predicate/property IRI
        "vann:preferredNamespaceUri  (IRI)",
    ),
    (
        "http://www.w3.org/2000/01/rdf-schema#seeAlso",  # NOSONAR - RDF predicate/property IRI
        "rdfs:seeAlso  (IRI)",
    ),
    (
        "http://xmlns.com/foaf/0.1/homepage",  # NOSONAR - RDF predicate/property IRI
        "foaf:homepage  (IRI)",
    ),
    (
        "http://www.w3.org/2002/07/owl#versionInfo",  # NOSONAR - RDF predicate/property IRI
        "owl:versionInfo",
    ),
    (
        "http://www.w3.org/2002/07/owl#versionIRI",  # NOSONAR - RDF predicate/property IRI
        "owl:versionIRI  (IRI)",
    ),
    (
        "http://www.w3.org/2002/07/owl#priorVersion",  # NOSONAR - RDF predicate/property IRI
        "owl:priorVersion  (IRI)",
    ),
    ("http://purl.org/dc/terms/title", "dcterms:title"),  # NOSONAR - RDF predicate/property IRI
    (
        "http://purl.org/dc/terms/description",  # NOSONAR - RDF predicate/property IRI
        "dcterms:description",
    ),
    (
        "http://www.w3.org/2000/01/rdf-schema#label",  # NOSONAR - RDF predicate/property IRI
        "rdfs:label",
    ),
)

# Predicates whose display label is used in the overview panel header. Includes the
# change-tracking provenance predicates that are no longer offered for manual *add*
# (above), so existing annotations still render with a friendly prefixed label.
_PREDICATE_DISPLAY: dict[str, str] = {
    **dict(_ANNOTATION_CATALOG),
    "http://purl.org/dc/terms/creator": "dcterms:creator",  # NOSONAR - RDF predicate/property IRI
    "http://purl.org/dc/terms/contributor":  # NOSONAR - RDF predicate/property IRI
    "dcterms:contributor",
    "http://purl.org/dc/terms/created": "dcterms:created",  # NOSONAR - RDF predicate/property IRI
    "http://purl.org/dc/terms/modified": "dcterms:modified",  # NOSONAR - RDF predicate/property IRI
}


def _annotation_display(predicate: str) -> str:
    """Short display name for a predicate — prefixed if known, else local name."""
    if predicate in _PREDICATE_DISPLAY:
        label = _PREDICATE_DISPLAY[predicate]
        return label.split("  ")[0]  # strip the parenthetical hint
    # Fall back to local name heuristic
    return predicate.rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def default_annotation_catalog() -> list[MetaProp]:
    """The built-in ontology-metadata predicate catalog. Used as the default when no
    user catalog is configured."""
    return [MetaProp(pred, label) for pred, label in _ANNOTATION_CATALOG]


_ENTITY_ANNOTATION_CATALOG: tuple[tuple[str, str], ...] = (
    (
        "http://www.w3.org/2000/01/rdf-schema#seeAlso",  # NOSONAR - RDF predicate/property IRI
        "rdfs:seeAlso  (IRI)",
    ),
    (
        "http://www.w3.org/2000/01/rdf-schema#isDefinedBy",  # NOSONAR - RDF predicate/property IRI
        "rdfs:isDefinedBy  (IRI)",
    ),
    (
        "http://www.w3.org/2004/02/skos/core#note",  # NOSONAR - RDF predicate/property IRI
        "skos:note",
    ),
    (
        "http://www.w3.org/2004/02/skos/core#example",  # NOSONAR - RDF predicate/property IRI
        "skos:example",
    ),
    ("http://purl.org/dc/terms/source", "dcterms:source"),  # NOSONAR - RDF predicate/property IRI
)


def default_entity_annotation_catalog() -> list[MetaProp]:
    """The built-in entity-metadata predicate catalog offered on classes / properties /
    individuals when none is configured (none is configured)."""
    return [MetaProp(pred, label) for pred, label in _ENTITY_ANNOTATION_CATALOG]


def annotation_catalog_options(
    taxonomy: Taxonomy, catalog: list[MetaProp] | None = None
) -> list[tuple[str, str]]:
    """Return ``(predicate_uri, display_label)`` pairs available for "Add metadata".

    *catalog* is the configured predicate catalog (built-in default when ``None``);
    predicates already present in ``taxonomy.ontology_annotations`` are filtered out
    so the picker only shows what can still be added.
    """
    cat = catalog if catalog is not None else default_annotation_catalog()
    present = {a.predicate for a in taxonomy.ontology_annotations}
    return [(mp.predicate, mp.label) for mp in cat if mp.predicate not in present]


def _annotation_rows(annotation: OntologyAnnotation) -> list[_fields.DetailField]:
    """One editable value row + one remove-action row for a single annotation."""
    display = _annotation_display(annotation.predicate)
    value_row = _fields.DetailField(
        key=f"ann:{annotation.predicate}:{annotation.value}",
        display=display,
        value=annotation.value,
        editable=True,
        meta={
            "type": "ont_annotation",
            "predicate": annotation.predicate,
            "old_value": annotation.value,
            "is_iri": annotation.is_iri,
            "lang": annotation.lang,
        },
    )
    remove_row = _fields.DetailField(
        key=f"ann:remove:{annotation.predicate}:{annotation.value}",
        display=f"  ✕ remove {display}",
        value="",
        editable=False,
        meta={
            "type": "action_del",
            _LIT_ACTION: "remove_ont_annotation",
            "predicate": annotation.predicate,
            "value": annotation.value,
        },
    )
    return [value_row, remove_row]


def _class_depths(taxonomy: Taxonomy) -> dict[str, int]:
    """Depth of each OWL class = its longest local subClassOf chain (roots = 0)."""
    classes = taxonomy.owl_classes
    cache: dict[str, int] = {}

    def depth(uri: str, seen: frozenset[str]) -> int:
        if uri in cache:
            return cache[uri]
        if uri in seen:  # cycle guard
            return 0
        cls = classes.get(uri)
        parents = [p for p in cls.sub_class_of if p in classes] if cls else []
        cache[uri] = 1 + max((depth(p, seen | {uri}) for p in parents), default=-1)
        return cache[uri]

    return {uri: depth(uri, frozenset()) for uri in classes}


def _bar_stat(key: str, label: str, count: int, total: int) -> _fields.DetailField:
    """A coverage row rendered as a block bar + percentage, e.g. '████░░░░  50%'."""
    percent = _pct(count, total)
    return _fields._pct_stat(key, label, percent)


def _stats_classes(taxonomy: Taxonomy) -> list[_fields.DetailField]:
    classes = taxonomy.owl_classes
    roots = sum(1 for c in classes.values() if not any(p in classes for p in c.sub_class_of))
    parents = {p for c in classes.values() for p in c.sub_class_of if p in classes}
    leaves = sum(1 for uri in classes if uri not in parents)
    fields = [
        _fields._sep("Classes"),
        _fields._stat("st:classes", _LIT_TOTAL, str(len(classes))),
        _fields._stat("st:roots", "root classes", str(roots)),
        _fields._stat("st:leaves", "leaf classes", str(leaves)),
    ]
    depths = _class_depths(taxonomy)
    if depths:
        avg = sum(depths.values()) / len(depths)
        fields.append(_fields._stat("st:avg_depth", "avg depth", f"{avg:.1f}"))
        fields.append(_fields._stat("st:max_depth", _tree._MAX_DEPTH, str(max(depths.values()))))
    return fields


def _stats_properties(taxonomy: Taxonomy) -> list[_fields.DetailField]:
    props = taxonomy.owl_properties
    obj = sum(1 for p in props.values() if p.prop_type == "ObjectProperty")
    datatype = sum(1 for p in props.values() if p.prop_type == "DatatypeProperty")
    incomplete = sum(1 for p in props.values() if not p.domains or not p.ranges)
    return [
        _fields._sep("Properties"),
        _fields._stat("st:props", _LIT_TOTAL, str(len(props))),
        _fields._stat("st:obj_props", "object", str(obj)),
        _fields._stat("st:dt_props", "datatype", str(datatype)),
        _fields._stat("st:incomplete_props", "missing domain/range", str(incomplete)),
    ]


def _stats_individuals(taxonomy: Taxonomy) -> list[_fields.DetailField]:
    classes = taxonomy.owl_classes
    typed = {t for ind in taxonomy.owl_individuals.values() for t in ind.types}
    unused = sum(1 for uri in classes if uri not in typed)
    return [
        _fields._sep("Individuals"),
        _fields._stat("st:individuals", _LIT_TOTAL, str(len(taxonomy.owl_individuals))),
        _fields._stat("st:unused", "classes with no individuals", str(unused)),
    ]


def _class_languages(classes: dict) -> list[str]:
    """Sorted list of every language tag appearing on a class label."""
    return sorted({lbl.lang for c in classes.values() for lbl in c.labels if lbl.lang})


def _lang_coverage_rows(classes: dict, langs: list[str], total: int) -> list[_fields.DetailField]:
    """One coverage bar per language: how many classes carry a label in it."""
    rows: list[_fields.DetailField] = []
    for code in langs:
        covered = sum(1 for c in classes.values() if any(lbl.lang == code for lbl in c.labels))
        rows.append(_bar_stat(f"st:lang_cov:{code}", f"labels · {code}", covered, total))
    return rows


def _stats_quality(
    taxonomy: Taxonomy, configured_langs: list[str] | None = None
) -> list[_fields.DetailField]:
    classes = taxonomy.owl_classes
    total = len(classes)
    # Heading + class label/documentation coverage. "labelled" accepts rdfs:label or
    # skos:prefLabel; "documented" is rdfs:comment — each row names its predicate(s).
    fields: list[_fields.DetailField] = [_fields._sep("Quality & Coverage")]
    if total:
        labelled = sum(1 for c in classes.values() if _is_labelled(c))
        commented = sum(1 for c in classes.values() if c.comments)
        fields.append(
            _bar_stat("st:label_cov", "labelled (rdfs:label / skos:prefLabel)", labelled, total)
        )
        fields.append(_bar_stat("st:comment_cov", "documented (rdfs:comment)", commented, total))
    # Language coverage — reported over the configured languages when known, else over
    # the languages detected in the data.
    langs = configured_langs if configured_langs is not None else _class_languages(classes)
    summary = str(len(langs)) + (f" ({', '.join(langs)})" if langs else "")
    fields.append(_fields._sep("Languages"))
    fields.append(_fields._stat("st:langs", "languages", summary))
    if total:
        fields.extend(_lang_coverage_rows(classes, langs, total))
    return fields


def _stats_metadata(metadata: dict | None) -> list[_fields.DetailField]:
    """The "Metadata coverage" subsection: how completely the configured annotation
    properties are populated (ontology header + entities). Omitted when neither
    percentage is computable (no catalogs configured)."""
    if not metadata:
        return []
    ont, ent = metadata.get("ontology_pct"), metadata.get("entity_pct")
    if ont is None and ent is None:
        return []
    fields: list[_fields.DetailField] = [_fields._sep("Metadata coverage")]
    if ont is not None:
        fields.append(_fields._pct_stat("st:meta_ont", "Ontology Metadata", ont))
    if ent is not None:
        fields.append(_fields._pct_stat("st:meta_entity", "Entity Metadata", ent))
    return fields


def _ontology_stats_fields(
    taxonomy: Taxonomy,
    configured_langs: list[str] | None = None,
    metadata: dict | None = None,
) -> list[_fields.DetailField]:
    """Global ontology statistics, grouped into visual subject sections."""
    return [
        *_stats_classes(taxonomy),
        *_stats_properties(taxonomy),
        *_stats_individuals(taxonomy),
        *_stats_quality(taxonomy, configured_langs),
        *_stats_metadata(metadata),
    ]


def _errors_color(count: int) -> str:
    """Errors: red when there are any, green when clean."""
    return "red" if count else "green"


def _warnings_color(count: int) -> str:
    """Warnings: < 10 green, 10–49 orange, ≥ 50 red."""
    if count >= 50:
        return "red"
    if count >= 10:
        return "orange"
    return "green"


def _lint_count_field(severity: str, label: str, count: int) -> _fields.DetailField:
    """A severity count row, coloured by its own rule (errors / warnings). When
    ``count`` > 0 the row links to a modal listing only that severity's issues
    (``action=view_lint`` + ``lint_severity``); when 0 it is a plain info row."""
    meta: dict = (
        {_LIT_ACTION: "view_lint", "lint_severity": severity} if count else {"type": "stat"}
    )
    meta["color"] = (_errors_color if severity == "error" else _warnings_color)(count)
    return _fields.DetailField(f"st:lint_{severity}", label, str(count), editable=False, meta=meta)


def _ontology_activity_fields(activity: dict | None) -> list[_fields.DetailField]:
    """Git edit-activity rows (from ``git.manager.file_activity``), if available."""
    if not activity:
        return []
    return [
        _fields._sep("Activity"),
        _fields._stat("st:last_edit", "last edited", str(activity["last"])),
        _fields._stat("st:total_edits", "total edits", str(activity[_LIT_TOTAL])),
        _fields._stat("st:edits_month", "edits (last 30 days)", str(activity["last_month"])),
    ]


def build_tui_ontology_overview_fields(
    taxonomy: Taxonomy,
    lang: str,
    activity: dict | None = None,
    lint: dict | None = None,
    configured_langs: list[str] | None = None,
    metadata: dict | None = None,
) -> list[_fields.DetailField]:
    """The ontology overview's detail fields.

    Thin wrapper over :class:`OntologyOverviewPresenter` (the live render path);
    kept so existing callers/tests reach the same presenter-produced fields.
    Imported lazily to avoid a tui→logic import cycle.
    """
    from ster.tui.presenters.context import PresenterContext
    from ster.tui.presenters.overview import OntologyOverviewPresenter

    ctx = PresenterContext(taxonomy, lang, configured_langs, activity, lint, metadata)
    return OntologyOverviewPresenter(ctx, "").render()


def build_tui_taxonomy_overview_fields(taxonomy: Taxonomy, lang: str) -> list[_fields.DetailField]:
    """Detail panel for the Taxonomy (SKOS) overview node — New-TUI only.

    Mirrors the ontology overview but with the *taxonomy's* identity and metadata:
    the concept-scheme namespace + prefix, and the scheme's SKOS metadata (title,
    creator, created, languages, descriptions, other annotations).
    """
    scheme = taxonomy.primary_scheme()
    if scheme is None:
        return [_fields._stat("tax:none", "", "No concept scheme in this taxonomy yet.")]

    target = scheme.uri  # scheme-keyed edits route here via meta["target_uri"]

    def _scheme_field(key: str, label: str, value: str, ftype: str) -> _fields.DetailField:
        return _fields.DetailField(
            key, label, value, editable=True, meta={"type": ftype, "target_uri": target}
        )

    fields: list[_fields.DetailField] = [_fields._sep("Metadata")]
    fields.append(_scheme_field("tax:title", "title", scheme.title(lang), "scheme_title"))
    fields.append(_scheme_field("tax:creator", "creator", scheme.creator, "scheme_creator"))
    fields.append(_scheme_field("tax:created", "created", scheme.created, "scheme_created"))
    fields.append(
        _scheme_field("tax:langs", "languages", ", ".join(scheme.languages), "scheme_languages")
    )
    for i, desc in enumerate(scheme.descriptions):
        fields.append(_fields._stat(f"tax:desc:{i}", "description", desc.value))
    for annotation in scheme.annotations:
        fields.append(
            _fields._stat(
                f"tax:ann:{annotation.predicate}",
                _annotation_display(annotation.predicate),
                annotation.value,
            )
        )
    return fields
