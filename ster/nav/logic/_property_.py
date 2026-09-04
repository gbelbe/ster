"""OWL property detail panel (build_property_detail) and the properties-section listing."""

from __future__ import annotations

from ...analysis_base import pct as _pct
from ...metadata_coverage import MetaProp
from ...model import OWLProperty, Taxonomy
from . import _fields, _rdf_class, _tree


def _property_label_fields(
    prop: OWLProperty, configured_langs: list[str]
) -> list[_fields.DetailField]:
    fields = [_fields._sep("Labels")]
    for lbl in sorted(prop.labels, key=lambda l: l.lang):
        fields.append(
            _fields.DetailField(
                f"prop_label:{lbl.lang}",
                f"label [{lbl.lang}]",
                lbl.value,
                editable=True,
                meta={"type": "prop_label", "lang": lbl.lang},
            )
        )
    fields.extend(
        _fields.essential_label_affordances(
            "property", {lbl.lang for lbl in prop.labels}, configured_langs
        )
    )
    return fields


def _property_comment_fields(
    prop: OWLProperty, configured_langs: list[str]
) -> list[_fields.DetailField]:
    fields = [_fields._sep("Notes")]
    for cmt in sorted(prop.comments, key=lambda d: d.lang):
        fields.append(
            _fields.DetailField(
                f"prop_comment:{cmt.lang}",
                f"comment [{cmt.lang}]",
                cmt.value,
                editable=True,
                meta={"type": "prop_comment", "lang": cmt.lang},
            )
        )
    fields.extend(
        _fields._lang_add_actions(
            configured_langs,
            "action:add_prop_comment",
            _fields._ADD_RDFS_COMMENT,
            "add_prop_comment",
            present={cmt.lang for cmt in prop.comments},
        )
    )
    return fields


def _property_class_rel_fields(
    taxonomy: Taxonomy, uris: list[str], key_prefix: str, display: str, lang: str
) -> list[_fields.DetailField]:
    fields: list[_fields.DetailField] = []
    for rel_uri in uris:
        cls = taxonomy.owl_classes.get(rel_uri)
        fields.append(
            _fields.DetailField(
                f"{key_prefix}:{rel_uri}",
                display,
                cls.label(lang) if cls else rel_uri,
                editable=False,
                meta={"type": "rdf_relation", "uri": rel_uri, "nav": bool(cls)},
            )
        )
    return fields


def _property_nav_rel_fields(
    taxonomy: Taxonomy, uris: list[str], key_prefix: str, display: str, lang: str
) -> list[_fields.DetailField]:
    fields: list[_fields.DetailField] = []
    for rel_uri in uris:
        rel_prop = taxonomy.owl_properties.get(rel_uri)
        fields.append(
            _fields.DetailField(
                f"{key_prefix}:{rel_uri}",
                display,
                rel_prop.label(lang) if rel_prop else rel_uri,
                editable=False,
                meta={"type": "prop_nav", "uri": rel_uri, "nav": bool(rel_prop)},
            )
        )
    return fields


def _property_signature_fields(
    taxonomy: Taxonomy, prop: OWLProperty, lang: str
) -> list[_fields.DetailField]:
    if not (prop.domains or prop.ranges or prop.sub_property_of or prop.inverse_of):
        return []
    fields = [_fields._sep("Signature")]
    fields.extend(_property_class_rel_fields(taxonomy, prop.domains, "prop_domain", "domain", lang))
    fields.extend(_property_class_rel_fields(taxonomy, prop.ranges, "prop_range", "range", lang))
    fields.extend(
        _property_nav_rel_fields(
            taxonomy, prop.sub_property_of, "prop_sub", "↑ subPropertyOf", lang
        )
    )
    fields.extend(
        _property_nav_rel_fields(taxonomy, prop.inverse_of, "prop_inv", "⟺ inverseOf", lang)
    )
    return fields


def _property_actions_fields(
    taxonomy: Taxonomy, prop: OWLProperty, lang: str
) -> list[_fields.DetailField]:
    fields = [_fields._sep("Actions")]
    fields.append(
        _fields._add_action_field("action:add_prop_domain", "→ Add domain class", "add_prop_domain")
    )
    fields.append(
        _fields._add_action_field("action:add_prop_range", "→ Add range class", "add_prop_range")
    )
    for d_uri in prop.domains:
        cls = taxonomy.owl_classes.get(d_uri)
        d_lbl = cls.label(lang) if cls else d_uri
        fields.append(
            _fields._add_action_field(
                f"action:rm_prop_domain:{d_uri}",
                f"✗ Remove domain {d_lbl}",
                "remove_prop_domain",
                domain_uri=d_uri,
            )
        )
    for r_uri in prop.ranges:
        cls = taxonomy.owl_classes.get(r_uri)
        r_lbl = cls.label(lang) if cls else r_uri
        fields.append(
            _fields._add_action_field(
                f"action:rm_prop_range:{r_uri}",
                f"✗ Remove range {r_lbl}",
                "remove_prop_range",
                range_uri=r_uri,
            )
        )
    fields.append(
        _fields._add_action_field(
            "action:delete_property", "⊘ Delete this property", "delete_property"
        )
    )
    return fields


def build_property_detail(
    taxonomy: Taxonomy,
    uri: str,
    lang: str,
    configured_langs: list[str] | None = None,
    entity_metadata_props: list[MetaProp] | None = None,
) -> list[_fields.DetailField]:
    """Detail panel for an owl:ObjectProperty / DatatypeProperty / etc."""
    prop = taxonomy.owl_properties.get(uri)
    if not prop:
        return []

    clangs = configured_langs or [lang]
    fields = [
        _fields._sep("Identity"),
        _fields.DetailField("uri", "URI", uri, editable=True, meta={"type": "uri"}),
        _rdf_class._type_field(taxonomy, uri, display=f"owl:{prop.prop_type}"),
    ]
    fields.extend(_property_label_fields(prop, clangs))
    fields.extend(_property_comment_fields(prop, clangs))
    fields.extend(_property_signature_fields(taxonomy, prop, lang))
    fields.extend(_fields._note_display_fields(prop.note, "prop:"))
    fields.extend(_fields.entity_metadata_section(prop, entity_metadata_props))
    fields.extend(_property_actions_fields(taxonomy, prop, lang))
    return fields


def _properties_overview_fields(props: list[OWLProperty], n: int) -> list[_fields.DetailField]:
    """Section header plus per-type counts (data/object/annotation properties)."""
    fields = [_fields._sep("Properties"), _fields._stat("props:total", "total", str(n))]
    counts = (
        ("props:data", "data properties", "DatatypeProperty"),
        ("props:obj", "object properties", "ObjectProperty"),
        ("props:ann", "annotation properties", "AnnotationProperty"),
    )
    for key, label, prop_type in counts:
        count = sum(1 for p in props if p.prop_type == prop_type)
        if count:
            fields.append(_fields._stat(key, label, str(count)))
    return fields


def _properties_completeness_fields(props: list[OWLProperty], n: int) -> list[_fields.DetailField]:
    """Label / domain / range coverage, as a percentage of all properties."""
    if not n:
        return []
    lbl_pct = _pct(sum(1 for p in props if p.labels), n)
    dom_pct = _pct(sum(1 for p in props if p.domains), n)
    rng_pct = _pct(sum(1 for p in props if p.ranges), n)
    return [
        _fields._sep("Completeness"),
        _fields._pct_stat("props:cov:label", _tree._RDFS_LABEL, lbl_pct),
        _fields._pct_stat("props:cov:domain", "rdfs:domain", dom_pct),
        _fields._pct_stat("props:cov:range", "rdfs:range", rng_pct),
    ]


def _properties_list_fields(props: list[OWLProperty], lang: str) -> list[_fields.DetailField]:
    """Alphabetically-sorted, selectable list of every OWL property."""
    if not props:
        return []
    fields: list[_fields.DetailField] = [_fields._sep("All properties")]
    for prop in sorted(props, key=lambda p: p.label(lang).lower()):
        display = prop.label(lang)
        tag = f"  [{prop.prop_type[:3]}]" if prop.prop_type else ""
        fields.append(
            _fields.DetailField(
                f"prop_nav:{prop.uri}",
                display,
                prop.uri + tag,
                editable=False,
                meta={"type": "navigate_property", "uri": prop.uri, "nav": True},
            )
        )
    return fields


def build_properties_section_fields(taxonomy: Taxonomy, lang: str) -> list[_fields.DetailField]:
    """Detail panel for the Properties section header node.

    Shows completeness stats (label / domain / range coverage) and a
    selectable, alphabetically-sorted list of every OWL property.  Selecting
    an item navigates the left tree to that property.
    """
    props: list[OWLProperty] = list(taxonomy.owl_properties.values())
    n = len(props)

    fields: list[_fields.DetailField] = []
    fields.extend(_properties_overview_fields(props, n))
    fields.extend(_properties_completeness_fields(props, n))

    # ── Action (before list so it stays visible) ─────────────────────────────
    fields.append(_fields._sep("Actions"))
    fields.append(
        _fields._add_action_add_field(
            "action:create_owl_property", "+ New OWL property", "create_owl_property"
        )
    )

    fields.extend(_properties_list_fields(props, lang))
    return fields
