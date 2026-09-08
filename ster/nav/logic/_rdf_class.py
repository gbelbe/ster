"""RDF/OWL class detail panel (build_rdf_class_detail) and the promoted-node detail panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from ...metadata_coverage import MetaProp
from ...model import OWLProperty, Taxonomy
from . import _concept, _fields

_LIT_ANNOTATIONPROPERTY: Final = "AnnotationProperty"
_LIT_DATATYPEPROPERTY: Final = "DatatypeProperty"
_LIT_OBJECTPROPERTY: Final = "ObjectProperty"
_LIT_CLASS: Final = "class"
_LIT_RDF_RELATION: Final = "rdf_relation"


_NODE_TYPE_DISPLAY = {
    "promoted": "pun (owl:Class + skos:Concept)",
    "linked": "skos:Concept → owl:Class (foaf:focus)",
    _LIT_CLASS: "owl:Class",
    "concept": "skos:Concept",
    "individual": "owl:NamedIndividual",
    "property": "owl:Property",
    "scheme": "skos:ConceptScheme",
}

# A glyph per node kind for the Identity 'type' row, mirroring the tree glyphs so an
# entity's kind reads at a glance. (Kept here — the nav layer must not import the tui layer.)
_TYPE_ICON = {
    _LIT_CLASS: "●",
    "concept": "○",
    "promoted": "◉",
    "linked": "◎",
    "individual": "◆",
    "property": "■",
    "scheme": "⬢",
}


def _type_field(taxonomy: Taxonomy, uri: str, display: str | None = None) -> _fields.DetailField:
    """The Identity 'type' row: a kind glyph + a plain RDF type (e.g. '◉ pun (owl:Class +
    skos:Concept)'), so every entity clearly states what it is. *display* overrides the type
    text (used for properties, which name their specific owl:*Property kind)."""
    nt = taxonomy.node_type(uri)
    icon = _TYPE_ICON.get(nt, "")
    text = display or _NODE_TYPE_DISPLAY.get(nt, nt)
    return _fields.DetailField(
        "node_type", "type", f"{icon} {text}".strip(), editable=False, meta={"type": "stat"}
    )


def _curie(taxonomy: Taxonomy, uri: str) -> str:
    """A prefixed name for *uri* (e.g. 'dcterms:subject') using the file's namespace
    bindings — the longest matching prefix wins. Falls back to the local name when no
    prefix is bound."""
    best: tuple[str, str] | None = None
    for prefix, ns in taxonomy.namespace_bindings.items():
        if uri.startswith(ns) and (best is None or len(ns) > len(best[1])):
            best = (prefix, ns)
    if best is not None:
        prefix, ns = best
        local = uri[len(ns) :]
        if local and prefix:
            return f"{prefix}:{local}"
    return uri.rstrip("/#").rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def _direct_properties(taxonomy: Taxonomy, class_uri: str) -> list:
    """Return OWLProperty objects whose domain includes *class_uri*."""
    from ...model import OWLProperty

    return [
        prop
        for prop in taxonomy.owl_properties.values()
        if class_uri in prop.domains
        if isinstance(prop, OWLProperty)
    ]


def _inherited_properties(taxonomy: Taxonomy, class_uri: str) -> list[tuple]:
    """Walk rdfs:subClassOf upward, collecting (OWLProperty, ancestor_uri) pairs.

    Direct properties are excluded. Each property appears at most once
    (diamond inheritance is de-duplicated).
    """
    direct_uris = {p.uri for p in _direct_properties(taxonomy, class_uri)}
    seen_prop_uris: set[str] = set(direct_uris)
    result: list[tuple] = []
    visited_classes: set[str] = set()

    def _walk(uri: str) -> None:
        if uri in visited_classes:
            return
        visited_classes.add(uri)
        cls = taxonomy.owl_classes.get(uri)
        if not cls:
            return
        for parent_uri in cls.sub_class_of:
            for prop in taxonomy.owl_properties.values():
                if parent_uri in prop.domains and prop.uri not in seen_prop_uris:
                    seen_prop_uris.add(prop.uri)
                    result.append((prop, parent_uri))
            _walk(parent_uri)

    _walk(class_uri)
    return result


@dataclass(frozen=True)
class SuggestedProperty:
    """One property applicable to instances of a class — surfaced in the
    add-individual modal. ``inherited_from`` is ``None`` for a property whose
    domain is the class itself, else the ancestor class the domain was declared on."""

    prop_uri: str
    label: str
    kind: str  # "object" | "datatype" | "other"
    range_uri: str | None
    inherited_from: str | None


_PROP_KIND = {_LIT_OBJECTPROPERTY: "object", _LIT_DATATYPEPROPERTY: "datatype"}


def suggested_properties(taxonomy: Taxonomy, class_uri: str, lang: str = "en") -> list:
    """Properties an instance of *class_uri* may carry — direct then inherited.

    Direct properties (domain is the class) come first, then properties inherited
    from any ``rdfs:subClassOf`` ancestor (de-duplicated, each tagged with the
    ancestor it came from). Returns ``[]`` for an unknown class.
    """
    if class_uri not in taxonomy.owl_classes:
        return []

    def _make(prop, source: str | None) -> SuggestedProperty:  # type: ignore[no-untyped-def]
        return SuggestedProperty(
            prop_uri=prop.uri,
            label=prop.label(lang),
            kind=_PROP_KIND.get(prop.prop_type, "other"),
            range_uri=prop.ranges[0] if prop.ranges else None,
            inherited_from=source,
        )

    direct = [_make(p, None) for p in _direct_properties(taxonomy, class_uri)]
    inherited = [_make(p, src) for p, src in _inherited_properties(taxonomy, class_uri)]
    return direct + inherited


def _add_class_property_actions(class_uri: str) -> list[_fields.DetailField]:
    """Action rows to define a new property on a class: a relationship, or an
    attribute of each supported datatype. Each row carries the prop_type and
    (for attributes) the datatype range in its meta."""
    from ...operations import SUPPORTED_DATATYPES

    rows = [
        _fields._add_action_add_field(
            "action:add_class_property:rel",
            "+ Add relationship (object property)",
            "add_class_property",
            class_uri=class_uri,
            prop_type=_LIT_OBJECTPROPERTY,
        )
    ]
    for label, range_uri in SUPPORTED_DATATYPES:
        rows.append(
            _fields._add_action_add_field(
                f"action:add_class_property:dt:{range_uri}",
                f"+ Add attribute · {label}",
                "add_class_property",
                class_uri=class_uri,
                prop_type=_LIT_DATATYPEPROPERTY,
                range_uri=range_uri,
            )
        )
    return rows


# Short, human-friendly value labels for a property's OWL type, shown in class
# detail property lists (e.g. "(Object Prop.)" instead of "owl:ObjectProperty").
_PROP_TYPE_DISPLAY = {
    _LIT_OBJECTPROPERTY: "(Object Prop.)",
    _LIT_DATATYPEPROPERTY: "(Datatype)",
    _LIT_ANNOTATIONPROPERTY: "(Annotation)",
}


def _prop_type_display(prop_type: str) -> str:
    return _PROP_TYPE_DISPLAY.get(prop_type, f"({prop_type})")


def prop_comment(prop: OWLProperty, lang: str) -> str:
    """The property's rdfs:comment for *lang* (else any, else ''), used as its hover tooltip."""
    for c in prop.comments:
        if c.lang == lang:
            return c.value
    return prop.comments[0].value if prop.comments else ""


def _prop_row_meta(prop: OWLProperty, lang: str, base: dict) -> dict:
    """*base* meta for a property row: renders the short type with a space (not ': ') and
    carries the rdfs:comment as a hover tooltip when present."""
    base = {**base, "plain_value": True}
    cmt = prop_comment(prop, lang)
    return {**base, "tooltip": cmt} if cmt else base


def _inherited_property_fields(
    taxonomy: Taxonomy, uri: str, lang: str
) -> list[_fields.DetailField]:
    """The collapsed 'N inherited properties' disclosure — properties inherited from
    ancestor classes, grouped under an 'inherited from <ancestor>:' sub-header. Empty
    when the class inherits none."""
    inherited = _inherited_properties(taxonomy, uri)
    if not inherited:
        return []
    grouped: dict[str, list] = {}
    for prop, parent_uri in inherited:
        grouped.setdefault(parent_uri, []).append(prop)
    n = len(inherited)
    fields: list[_fields.DetailField] = [
        _fields._sep_collapsible(f"{n} inherited propert{'y' if n == 1 else 'ies'}")
    ]
    # Highest-level ancestor first: the walk collects nearest-parent first, so reverse.
    for parent_uri, props in reversed(list(grouped.items())):
        parent_cls = taxonomy.owl_classes.get(parent_uri)
        parent_lbl = (parent_cls.label(lang) or parent_cls.local_name) if parent_cls else parent_uri
        fields.append(_fields._sep(f"inherited from {parent_lbl}:"))
        fields.extend(
            _fields.DetailField(
                f"inherited_prop:{prop.uri}:{parent_uri}",
                prop.local_name,
                _prop_type_display(prop.prop_type),
                editable=False,
                meta=_prop_row_meta(
                    prop,
                    lang,
                    {"type": "inherited_prop", "uri": prop.uri, "parent_uri": parent_uri},
                ),
            )
            for prop in props
        )
    fields.append(_fields._sep_group_end())
    return fields


# Detail property groups, in display order: annotation, then object, then datatype.
_PROP_TYPE_GROUPS: tuple[tuple[str, str], ...] = (
    (_LIT_ANNOTATIONPROPERTY, "Annotation properties"),
    (_LIT_OBJECTPROPERTY, "Object properties"),
    (_LIT_DATATYPEPROPERTY, "Datatype properties"),
)


def _prop_group_key(prop_type: str) -> str:
    """Bucket a property's rdf type into one of the three display groups: annotation and
    datatype map straight across; everything else (ObjectProperty, bare Property, unknown)
    falls into the object group so nothing is ever dropped from the list."""
    if prop_type in (_LIT_ANNOTATIONPROPERTY, _LIT_DATATYPEPROPERTY):
        return prop_type
    return _LIT_OBJECTPROPERTY


def _grouped_property_sections(
    grouped: dict[str, list[_fields.DetailField]],
) -> list[_fields.DetailField]:
    """Emit the typed property groups in order (annotation → object → datatype) — each a
    title sub-header followed by its rows. Groups with no members are omitted entirely."""
    fields: list[_fields.DetailField] = []
    for ptype, title in _PROP_TYPE_GROUPS:
        rows = grouped.get(ptype) or []
        if rows:
            fields.append(_fields._sep_sub(title))  # indented sub-header under the section
            fields.extend(rows)
    return fields


def _class_prop_field(prop: OWLProperty, lang: str) -> _fields.DetailField:
    """A direct-property row: local name + short type, editable via ✎ → the property edit
    modal (the uri names the property)."""
    return _fields.DetailField(
        f"classprop:{prop.uri}",
        prop.local_name,
        _prop_type_display(prop.prop_type),
        editable=False,
        meta=_prop_row_meta(
            prop, lang, {"type": "class_prop_nav", "uri": prop.uri, "action": "edit_property"}
        ),
    )


def _class_properties_section(taxonomy: Taxonomy, uri: str, lang: str) -> list[_fields.DetailField]:
    """The class 'Properties' section: direct properties grouped by type (annotation →
    object → datatype), the collapsed inherited-properties disclosure, then the
    add-property action rows."""
    grouped: dict[str, list[_fields.DetailField]] = {}
    for prop in sorted(_direct_properties(taxonomy, uri), key=lambda p: p.local_name):
        grouped.setdefault(_prop_group_key(prop.prop_type), []).append(
            _class_prop_field(prop, lang)
        )
    fields: list[_fields.DetailField] = [_fields._sep("Properties")]
    fields.extend(_grouped_property_sections(grouped))
    fields.extend(_inherited_property_fields(taxonomy, uri, lang))
    fields.extend(_add_class_property_actions(uri))
    return fields


def _class_label_fields(rdf_class, clangs: list[str]) -> list[_fields.DetailField]:
    fields: list[_fields.DetailField] = [_fields._sep("Labels")]
    for lbl in sorted(rdf_class.labels, key=lambda l: l.lang):
        fields.append(
            _fields.DetailField(
                f"rdflabel:{lbl.lang}",
                f"label [{lbl.lang}]",
                lbl.value,
                editable=True,
                meta={"type": "rdf_label", "lang": lbl.lang},
            )
        )
    fields.extend(
        _fields.essential_label_affordances(
            _LIT_CLASS, {lbl.lang for lbl in rdf_class.labels}, clangs
        )
    )
    return fields


def _class_comment_fields(rdf_class, clangs: list[str]) -> list[_fields.DetailField]:
    fields: list[_fields.DetailField] = [_fields._sep("Notes")]
    for comment in sorted(rdf_class.comments, key=lambda d: d.lang):
        fields.append(
            _fields.DetailField(
                f"rdfcomment:{comment.lang}",
                f"comment [{comment.lang}]",
                comment.value,
                editable=True,
                meta={"type": "rdf_comment", "lang": comment.lang},
            )
        )
    fields.extend(
        _fields._lang_add_actions(
            clangs,
            "action:add_rdf_comment",
            _fields._ADD_RDFS_COMMENT,
            "add_rdf_comment",
            present={cmt.lang for cmt in rdf_class.comments},
        )
    )
    return fields


def _class_superclass_fields(taxonomy: Taxonomy, rdf_class, lang: str) -> list[_fields.DetailField]:
    fields: list[_fields.DetailField] = []
    for parent_uri in rdf_class.sub_class_of:
        parent_cls = taxonomy.owl_classes.get(parent_uri)
        label_str = parent_cls.label(lang) if parent_cls else parent_uri
        fields.append(
            _fields.DetailField(
                f"subclassof:{parent_uri}",
                "↑ subClassOf",
                label_str,
                editable=False,
                meta={"type": _LIT_RDF_RELATION, "uri": parent_uri, "nav": bool(parent_cls)},
            )
        )
        parent_lbl = parent_cls.label(lang) if parent_cls else parent_uri
        fields.append(
            _fields._add_action_del_field(
                f"action:rm_super:{parent_uri}",
                f"  ✗ Remove subClassOf {parent_lbl}",
                "remove_superclass",
                parent_uri=parent_uri,
            )
        )
    return fields


def _class_equivalent_fields(taxonomy: Taxonomy, rdf_class, lang: str) -> list[_fields.DetailField]:
    fields: list[_fields.DetailField] = []
    for eq_uri in rdf_class.equivalent_class:
        eq_cls = taxonomy.owl_classes.get(eq_uri)
        label_str = eq_cls.label(lang) if eq_cls else eq_uri
        fields.append(
            _fields.DetailField(
                f"equivclass:{eq_uri}",
                "⟺ equivalentClass",
                label_str,
                editable=False,
                meta={"type": _LIT_RDF_RELATION, "uri": eq_uri, "nav": bool(eq_cls)},
            )
        )
    return fields


def _class_disjoint_fields(taxonomy: Taxonomy, rdf_class, lang: str) -> list[_fields.DetailField]:
    fields: list[_fields.DetailField] = []
    for dj_uri in rdf_class.disjoint_with:
        dj_cls = taxonomy.owl_classes.get(dj_uri)
        label_str = dj_cls.label(lang) if dj_cls else dj_uri
        fields.append(
            _fields.DetailField(
                f"disjoint:{dj_uri}",
                "⊥ disjointWith",
                label_str,
                editable=False,
                meta={"type": _LIT_RDF_RELATION, "uri": dj_uri, "nav": bool(dj_cls)},
            )
        )
    return fields


def _class_hierarchy_actions(rdf_class) -> list[_fields.DetailField]:
    fields: list[_fields.DetailField] = [
        _fields._add_action_add_field(
            "action:link_super", "↑ Add superclass (subClassOf)", "link_superclass"
        )
    ]
    if rdf_class.sub_class_of:
        fields.append(
            _fields._add_action_field(
                "action:move_class", "↷ Move under different superclass", "move_class"
            )
        )
    # The subclass list + instance count are not repeated here (they are navigable in the
    # tree); only the create actions remain, alongside the other hierarchy actions.
    fields.append(
        _fields._add_action_add_field("action:new_subclass", "↓ New subclass", "new_subclass")
    )
    fields.append(
        _fields._add_action_add_field(
            "action:add_individual", "+ New individual of this class", "add_individual"
        )
    )
    return fields


_OWL = "http://www.w3.org/2002/07/owl#"  # NOSONAR - RDF namespace IRI
_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"  # NOSONAR - RDF predicate IRI
# owl restriction predicate → how an OWL reader says it aloud (Manchester syntax).
_RESTRICTION_WORDS = {
    f"{_OWL}someValuesFrom": "some",
    f"{_OWL}allValuesFrom": "only",
    f"{_OWL}hasValue": "value",
    f"{_OWL}minCardinality": "min",
    f"{_OWL}maxCardinality": "max",
    f"{_OWL}cardinality": "exactly",
    f"{_OWL}minQualifiedCardinality": "min",
    f"{_OWL}maxQualifiedCardinality": "max",
    f"{_OWL}qualifiedCardinality": "exactly",
}


def _short(taxonomy: Taxonomy, term: object, lang: str) -> str:
    """A term as a reader would want it: its label, else its local name."""
    text = str(term)
    entity = taxonomy.owl_classes.get(text) or taxonomy.owl_properties.get(text)
    if entity is not None:
        return entity.label(lang) or text.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
    for sep in ("#", "/"):
        if sep in text:
            return text.rsplit(sep, 1)[-1]
    return text


def _restriction_phrase(taxonomy: Taxonomy, parts: dict[str, object], lang: str) -> str:
    """ "sells some Paint" — a restriction as an OWL reader would read it.

    Manchester syntax rather than three raw triples, because the point of showing
    an expression ster cannot edit is that someone can still *read* it.
    """
    prop = parts.get(f"{_OWL}onProperty")
    for predicate, word in _RESTRICTION_WORDS.items():
        if predicate in parts:
            filler = _short(taxonomy, parts[predicate], lang)
            return f"{_short(taxonomy, prop, lang)} {word} {filler}" if prop else f"{word} {filler}"
    return _short(taxonomy, prop, lang) if prop else ""


def _blank_subgraphs(taxonomy: Taxonomy) -> dict[object, dict[str, object]]:
    """Every blank node in the residue, as predicate → object."""
    from rdflib import BNode  # noqa: PLC0415

    # isinstance against BNode, not against str: rdflib's BNode *is* a str
    # subclass, so a str check collects everything or nothing.
    parts: dict[object, dict[str, object]] = {}
    for subject, predicate, obj in taxonomy.residue:
        if isinstance(subject, BNode):
            parts.setdefault(subject, {})[str(predicate)] = obj
    return parts


def _class_expression_fields(taxonomy: Taxonomy, uri: str, lang: str) -> list[_fields.DetailField]:
    """Anonymous class expressions on this class — shown, not editable.

    ster models a superclass as a named URI, so ``Shop subClassOf [ … ]`` has no
    row of its own. The statement is kept verbatim in the residue and read back
    unchanged; this puts it where its class is, so it is visible rather than
    merely safe.
    """
    parts = _blank_subgraphs(taxonomy)
    fields: list[_fields.DetailField] = []
    for subject, predicate, obj in taxonomy.residue:
        if str(subject) != uri or obj not in parts:
            continue
        phrase = _restriction_phrase(taxonomy, parts[obj], lang)
        if not phrase:
            continue
        fields.append(
            _fields.DetailField(
                f"expr:{uri}:{obj}",
                f"↑ {_short(taxonomy, predicate, lang)}",
                phrase,
                editable=False,
                meta={"type": "class_expression", "read_only": True},
            )
        )
    return fields


def _class_hierarchy_fields(taxonomy: Taxonomy, rdf_class, lang: str) -> list[_fields.DetailField]:
    fields: list[_fields.DetailField] = [_fields._sep("Hierarchy")]
    fields.extend(_class_superclass_fields(taxonomy, rdf_class, lang))
    fields.extend(_class_equivalent_fields(taxonomy, rdf_class, lang))
    fields.extend(_class_disjoint_fields(taxonomy, rdf_class, lang))
    fields.extend(_class_expression_fields(taxonomy, rdf_class.uri, lang))
    fields.extend(_class_hierarchy_actions(rdf_class))
    return fields


def build_rdf_class_detail(
    taxonomy: Taxonomy,
    uri: str,
    lang: str,
    configured_langs: list[str] | None = None,
    entity_metadata_props: list[MetaProp] | None = None,
) -> list[_fields.DetailField]:
    """Detail panel for an owl:Class / rdfs:Class node."""
    rdf_class = taxonomy.owl_classes.get(uri)
    if not rdf_class:
        return []

    clangs = configured_langs or [lang]
    fields: list[_fields.DetailField] = []

    # ── Identity ────────────────────────────────────────────────────────────
    fields.append(_fields._sep("Identity"))
    fields.append(_fields.DetailField("uri", "URI", uri, editable=True, meta={"type": "uri"}))
    fields.append(_type_field(taxonomy, uri))

    # ── Labels (rdfs:label) — always shown ──────────────────────────────────
    fields.extend(_class_label_fields(rdf_class, clangs))

    # ── Notes (rdfs:comment) — always shown ─────────────────────────────────
    fields.extend(_class_comment_fields(rdf_class, clangs))

    # ── Hierarchy — always shown with inline mutations ───────────────────────
    fields.extend(_class_hierarchy_fields(taxonomy, rdf_class, lang))

    # ── Properties ───────────────────────────────────────────────────────────
    fields.extend(_class_properties_section(taxonomy, uri, lang))

    # ── Subtree quality stats ────────────────────────────────────────────────
    fields.extend(_concept._class_quality_fields(taxonomy, uri, lang))

    # ── Note (ns1:note markdown) ──────────────────────────────────────────────
    fields.extend(_fields._note_display_fields(rdf_class.note, "cls:"))

    # ── Rich Content (schema.org) ─────────────────────────────────────────────
    fields.extend(_fields._schema_media_display_fields(rdf_class, "cls:"))
    fields.extend(_fields._schema_media_action_fields(rdf_class, "cls:"))

    # ── Metadata (configured annotation catalog) ─────────────────────────────
    fields.extend(_fields.entity_metadata_section(rdf_class, entity_metadata_props))

    # ── Danger Zone ──────────────────────────────────────────────────────────
    fields.append(_fields._sep_danger("Danger Zone"))
    fields.append(
        _fields._add_action_field(
            "action:class_to_individual",
            "⇢ Change to individual",
            "class_to_individual",
        )
    )
    fields.append(
        _fields._add_action_del_field("action:delete_class", "⊘ Delete this class", "delete_class")
    )

    return fields


def _promoted_skos_section(taxonomy: Taxonomy, concept, lang: str) -> list[_fields.DetailField]:
    fields: list[_fields.DetailField] = [_fields._sep("SKOS — Concept")]
    fields.extend(
        _fields._section_labels_grouped(concept.labels, "pref", "alt", "prefLabel", "pref", "alt")
    )
    if concept.definitions or concept.scope_notes:
        fields.append(_fields._sep("Notes"))
        fields.extend(_fields._section_text_list(concept.definitions, "def", "definition", "def"))
        fields.extend(
            _fields._section_text_list(concept.scope_notes, "scope", "scopeNote", "scope_note")
        )
    if concept.narrower or concept.broader or concept.related:
        fields.append(_fields._sep("SKOS Hierarchy"))
        fields.extend(_concept._concept_hierarchy_fields(taxonomy, concept, lang))
    return fields


def _promoted_owl_label_comment_fields(rdf_class) -> list[_fields.DetailField]:
    fields: list[_fields.DetailField] = []
    for lbl in sorted(rdf_class.labels, key=lambda l: l.lang):
        fields.append(
            _fields.DetailField(
                f"rdflabel:{lbl.lang}",
                f"rdfs:label [{lbl.lang}]",
                lbl.value,
                editable=True,
                meta={"type": "rdf_label", "lang": lbl.lang},
            )
        )
    for comment in sorted(rdf_class.comments, key=lambda d: d.lang):
        fields.append(
            _fields.DetailField(
                f"rdfcomment:{comment.lang}",
                f"rdfs:comment [{comment.lang}]",
                comment.value,
                editable=True,
                meta={"type": "rdf_comment", "lang": comment.lang},
            )
        )
    return fields


def _promoted_superclass_fields(
    taxonomy: Taxonomy, rdf_class, lang: str
) -> list[_fields.DetailField]:
    fields: list[_fields.DetailField] = []
    for parent_uri in rdf_class.sub_class_of:
        parent_cls = taxonomy.owl_classes.get(parent_uri)
        label_str = parent_cls.label(lang) if parent_cls else parent_uri
        fields.append(
            _fields.DetailField(
                f"subclassof:{parent_uri}",
                "↑ subClassOf",
                label_str,
                editable=False,
                meta={"type": _LIT_RDF_RELATION, "uri": parent_uri, "nav": bool(parent_cls)},
            )
        )
    return fields


def _promoted_owl_hierarchy_fields(
    taxonomy: Taxonomy, rdf_class, lang: str
) -> list[_fields.DetailField]:
    has_owl_hierarchy = bool(
        rdf_class.sub_class_of or rdf_class.equivalent_class or rdf_class.disjoint_with
    )
    if not has_owl_hierarchy:
        return []
    fields: list[_fields.DetailField] = [_fields._sep("OWL Hierarchy")]
    fields.extend(_promoted_superclass_fields(taxonomy, rdf_class, lang))
    fields.extend(_class_equivalent_fields(taxonomy, rdf_class, lang))
    fields.extend(_class_disjoint_fields(taxonomy, rdf_class, lang))
    return fields


def _promoted_owl_section(taxonomy: Taxonomy, rdf_class, lang: str) -> list[_fields.DetailField]:
    fields: list[_fields.DetailField] = [_fields._sep("OWL — Class")]
    fields.extend(_promoted_owl_label_comment_fields(rdf_class))
    fields.extend(_promoted_owl_hierarchy_fields(taxonomy, rdf_class, lang))
    return fields


def build_promoted_detail(
    taxonomy: Taxonomy,
    uri: str,
    lang: str,
    show_mappings: bool = False,
    configured_langs: list[str] | None = None,
) -> list[_fields.DetailField]:
    """Detail panel for a node that is both skos:Concept and owl:Class."""
    concept = taxonomy.concepts.get(uri)
    rdf_class = taxonomy.owl_classes.get(uri)
    if not concept:
        return build_rdf_class_detail(taxonomy, uri, lang, configured_langs)
    if not rdf_class:
        return _concept.build_concept_detail(taxonomy, uri, lang, configured_langs)

    fields: list[_fields.DetailField] = []

    # ── Identity ────────────────────────────────────────────────────────────
    fields.append(_fields._sep("Identity"))
    fields.append(_fields.DetailField("uri", "URI", uri, editable=True, meta={"type": "uri"}))
    fields.append(
        _fields.DetailField(
            "node_type",
            "type",
            "skos:Concept + owl:Class",
            editable=False,
            meta={"type": "stat"},
        )
    )

    # ── SKOS section ─────────────────────────────────────────────────────────
    fields.extend(_promoted_skos_section(taxonomy, concept, lang))

    # ── OWL section ──────────────────────────────────────────────────────────
    fields.extend(_promoted_owl_section(taxonomy, rdf_class, lang))

    # ── Actions ──────────────────────────────────────────────────────────────
    fields.append(_fields._sep("Actions"))
    fields.extend(_concept._concept_action_fields(lang, concept, show_mappings, configured_langs))

    return fields
