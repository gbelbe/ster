"""OWL individual detail panel (build_individual_detail)."""

from __future__ import annotations

from typing import Final

from ...metadata_coverage import MetaProp
from ...model import Taxonomy
from . import _fields, _rdf_class

_LIT_ACTION: Final = "action"
_LIT_IND_LIT_VAL: Final = "ind_lit_val"
_LIT_PROP_URI: Final = "prop_uri"


def _individual_membership_fields(
    taxonomy: Taxonomy, individual, lang: str
) -> list[_fields.DetailField]:  # type: ignore[no-untyped-def]
    """Each ``instanceOf`` as an editable row: ✎ re-picks the class (change_ind_type),
    Delete removes it. Adding a membership lives on the right-click context menu."""
    fields: list[_fields.DetailField] = []
    for type_uri in sorted(individual.types):
        cls = taxonomy.owl_classes.get(type_uri)
        label_str = cls.label(lang) if cls else type_uri
        h = taxonomy.uri_to_handle(type_uri) or "?"
        fields.append(
            _fields.DetailField(
                f"ind_type:{type_uri}",
                "◈ instanceOf",
                f"{label_str}  [{h}]",
                editable=True,  # ✎ → change_ind_type picker; the paired remove folds into Delete
                meta={
                    "type": "ind_type",
                    _LIT_ACTION: "change_ind_type",
                    "uri": type_uri,
                    "type_uri": type_uri,
                    "nav": bool(cls),
                },
            )
        )
        fields.append(
            _fields._add_action_del_field(
                f"action:rm_ind_type:{type_uri}",
                "✗ Remove instanceOf",
                "remove_ind_type",
                type_uri=type_uri,
            )
        )
    return fields


def _value_target_label(taxonomy: Taxonomy, uri: str, lang: str) -> tuple[str, bool]:
    """The display label for an object-value target and whether it is navigable — resolved
    across individuals, concepts and classes (so a ``dct:subject`` → concept tag shows the
    concept's label, not a raw URI). Falls back to the URI itself when unknown."""
    ind = taxonomy.owl_individuals.get(uri)
    if ind is not None:
        return ind.label(lang) or uri, True
    concept = taxonomy.concepts.get(uri)
    if concept is not None:
        return concept.pref_label(lang) or uri, True
    cls = taxonomy.owl_classes.get(uri)
    if cls is not None:
        return cls.label(lang) or cls.local_name, True
    return uri, False


def _individual_object_value_fields(
    taxonomy: Taxonomy, individual, lang: str
) -> list[_fields.DetailField]:  # type: ignore[no-untyped-def]
    """Asserted object-property values, each editable via ✎ (pick a new target) with a
    folded Delete. Grouped by predicate so multi-valued properties sit together."""
    from ster.operations import DCT_SUBJECT  # noqa: PLC0415

    fields: list[_fields.DetailField] = []
    seen: list[str] = []
    for prop_uri, _ in individual.property_values:
        if prop_uri not in seen:
            seen.append(prop_uri)
    for p_uri in seen:
        prop = taxonomy.owl_properties.get(p_uri)
        # Show the property's label, else its prefixed name (e.g. dcterms:subject) so the
        # exact predicate is clear — not just its bare local name.
        prop_lbl = prop.label(lang) if prop else _rdf_class._curie(taxonomy, p_uri)
        icon = "🏷" if p_uri == DCT_SUBJECT else "→"  # a dct:subject value is a concept tag
        for val_uri in [vu for pu, vu in individual.property_values if pu == p_uri]:
            val_lbl, navigable = _value_target_label(taxonomy, val_uri, lang)
            fields.append(
                _fields.DetailField(
                    f"ind_propval:{p_uri}::{val_uri}",
                    f"{icon} {prop_lbl}",
                    val_lbl,
                    editable=True,  # ✎ → edit_prop_value picker; paired remove folds into Delete
                    meta={
                        "type": "ind_prop_val",
                        _LIT_ACTION: "edit_prop_value",
                        _LIT_PROP_URI: p_uri,
                        "val_uri": val_uri,
                        "nav": navigable,
                    },
                )
            )
            fields.append(
                _fields._add_action_del_field(
                    f"action:rm_prop_value:{p_uri}::{val_uri}",
                    f"✗ Remove → {prop_lbl}: {val_lbl}",
                    "remove_prop_value",
                    prop_uri=p_uri,
                    val_uri=val_uri,
                )
            )
    return fields


def _individual_literal_value_fields(
    taxonomy: Taxonomy, individual, lang: str
) -> list[_fields.DetailField]:  # type: ignore[no-untyped-def]
    """Asserted literal-property values, each editable via ✎ (a text modal) with a folded
    Delete. The language / datatype tag rides on the label so the value stays raw-editable."""
    fields: list[_fields.DetailField] = []
    seen: list[str] = []
    for prop_uri, _, _ in individual.literal_values:
        if prop_uri not in seen:
            seen.append(prop_uri)
    for p_uri in seen:
        prop = taxonomy.owl_properties.get(p_uri)
        prop_lbl = prop.label(lang) if prop else p_uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        for val_str, lang_or_dt in [
            (vs, ld) for pu, vs, ld in individual.literal_values if pu == p_uri
        ]:
            tag = f"  [{lang_or_dt[1:]}]" if lang_or_dt.startswith("@") and lang_or_dt[1:] else ""
            fields.append(
                _fields.DetailField(
                    f"ind_litval:{p_uri}::{val_str}",
                    f"→ {prop_lbl}{tag}",
                    val_str,
                    editable=True,  # ✎ → edit_literal_value text modal; paired remove → Delete
                    meta={
                        "type": _LIT_IND_LIT_VAL,
                        _LIT_ACTION: "edit_literal_value",
                        _LIT_PROP_URI: p_uri,
                        "val_str": val_str,
                        "lang_or_dt": lang_or_dt,
                    },
                )
            )
            fields.append(
                _fields._add_action_del_field(
                    f"action:rm_lit_value:{p_uri}::{val_str}",
                    f"✗ Remove → {prop_lbl}: {val_str}",
                    "remove_literal_value",
                    prop_uri=p_uri,
                    val_str=val_str,
                    lang_or_dt=lang_or_dt,
                )
            )
    return fields


def _value_group_key(taxonomy: Taxonomy, prop_uri: str, is_literal: bool) -> str:
    """The display group for an asserted value, by its property's declared type. Falls back
    to datatype for a literal value / object for a relation when the property is undeclared."""
    prop = taxonomy.owl_properties.get(prop_uri)
    if prop is not None:
        return _rdf_class._prop_group_key(prop.prop_type)
    return "DatatypeProperty" if is_literal else "ObjectProperty"


def _individual_property_value_fields(
    taxonomy: Taxonomy, individual, lang: str
) -> list[_fields.DetailField]:  # type: ignore[no-untyped-def]
    """Every asserted property value grouped by its property's type (annotation → object →
    datatype); each value an editable ✎ row with its Delete folded in, all three titles shown."""
    flat = [
        *_individual_object_value_fields(taxonomy, individual, lang),
        *_individual_literal_value_fields(taxonomy, individual, lang),
    ]
    grouped: dict[str, list[_fields.DetailField]] = {}
    current: str | None = None
    for f in flat:
        ftype = f.meta.get("type")
        if ftype in ("ind_prop_val", _LIT_IND_LIT_VAL):
            current = _value_group_key(taxonomy, f.meta[_LIT_PROP_URI], ftype == _LIT_IND_LIT_VAL)
            grouped.setdefault(current, []).append(f)
        elif current is not None:  # the paired '✗ Remove' row rides with its value's group
            grouped[current].append(f)
    return _rdf_class._grouped_property_sections(grouped)


def build_individual_detail(
    taxonomy: Taxonomy,
    uri: str,
    lang: str,
    configured_langs: list[str] | None = None,
    entity_metadata_props: list[MetaProp] | None = None,
) -> list[_fields.DetailField]:
    """Detail panel for an owl:NamedIndividual."""
    individual = taxonomy.owl_individuals.get(uri)
    if not individual:
        return []

    clangs = configured_langs or [lang]
    fields: list[_fields.DetailField] = []

    # ── Identity ────────────────────────────────────────────────────────────
    fields.append(_fields._sep("Identity"))
    fields.append(_fields.DetailField("uri", "URI", uri, editable=True, meta={"type": "uri"}))
    fields.append(_rdf_class._type_field(taxonomy, uri))

    # ── Labels (rdfs:label) — always shown ──────────────────────────────────
    fields.append(_fields._sep("Labels"))
    for lbl in sorted(individual.labels, key=lambda l: l.lang):
        fields.append(
            _fields.DetailField(
                f"ind_label:{lbl.lang}",
                f"label [{lbl.lang}]",
                lbl.value,
                editable=True,
                meta={"type": "ind_label", "lang": lbl.lang},
            )
        )
    fields.extend(
        _fields.essential_label_affordances(
            "individual", {lbl.lang for lbl in individual.labels}, clangs
        )
    )

    # ── Notes (rdfs:comment) — always shown ─────────────────────────────────
    fields.append(_fields._sep("Notes"))
    for comment in sorted(individual.comments, key=lambda d: d.lang):
        fields.append(
            _fields.DetailField(
                f"ind_comment:{comment.lang}",
                f"comment [{comment.lang}]",
                comment.value,
                editable=True,
                meta={"type": "ind_comment", "lang": comment.lang},
            )
        )
    fields.extend(
        _fields._lang_add_actions(
            clangs,
            "action:add_ind_comment",
            _fields._ADD_RDFS_COMMENT,
            "add_ind_comment",
            present={cmt.lang for cmt in individual.comments},
        )
    )

    # ── Class Membership — editable instanceOf rows (✎ change class / Delete) ─
    fields.append(_fields._sep("Class Membership"))
    fields.extend(_individual_membership_fields(taxonomy, individual, lang))

    # ── Property Values — grouped by type; only shown when the individual asserts any ─
    if individual.property_values or individual.literal_values:
        fields.append(_fields._sep("Property Values"))
        fields.extend(_individual_property_value_fields(taxonomy, individual, lang))

    # ── Note (ns1:note markdown) ──────────────────────────────────────────────
    fields.extend(_fields._note_display_fields(individual.note, "ind:"))

    # ── Rich Content (schema.org) ─────────────────────────────────────────────
    fields.extend(_fields._schema_media_display_fields(individual, "ind:"))
    fields.extend(_fields._schema_media_action_fields(individual, "ind:"))

    # ── Metadata (configured annotation catalog) ─────────────────────────────
    fields.extend(_fields.entity_metadata_section(individual, entity_metadata_props))

    # ── Danger Zone ──────────────────────────────────────────────────────────
    fields.append(_fields._sep_danger("Danger Zone"))
    fields.append(
        _fields._add_action_field(
            "action:individual_to_class",
            "⇢ Change to class",
            "individual_to_class",
        )
    )
    fields.append(
        _fields._add_action_del_field(
            "action:delete_individual", "⊘ Delete this individual", "delete_individual"
        )
    )

    return fields
