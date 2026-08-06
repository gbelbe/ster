"""Graph visualization helpers — label formatting and node detail builders.

Shared utilities consumed by viz_vowl.py and any future renderers.
"""

from __future__ import annotations

from pathlib import Path

from .model import (
    Concept,
    ConceptScheme,
    LabelType,
    OWLIndividual,
    RDFClass,
    Taxonomy,
    is_builtin_uri,
)
from .taxonomy_analysis import analyze_taxonomy

# ── Helpers ───────────────────────────────────────────────────────────────────


def _label(text: str, max_len: int = 18) -> str:
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _local(uri: str) -> str:
    for sep in ("#", "/"):
        if sep in uri:
            return uri.rsplit(sep, 1)[-1]
    return uri


def _ontology_title(taxonomy: Taxonomy, file_path: Path | None) -> str:
    if taxonomy.ontology_label:
        return taxonomy.ontology_label
    if taxonomy.ontology_uri:
        uri = taxonomy.ontology_uri.rstrip("/")
        for sep in ("#", "/"):
            if sep in uri:
                return uri.rsplit(sep, 1)[-1]
        return taxonomy.ontology_uri
    if file_path:
        return file_path.stem
    return "Ontology"


def _label_for(uri: str, taxonomy: Taxonomy) -> str:
    if uri in taxonomy.concepts:
        return taxonomy.concepts[uri].pref_label("en")
    if uri in taxonomy.owl_classes:
        return taxonomy.owl_classes[uri].label("en")
    if uri in taxonomy.owl_individuals:
        return taxonomy.owl_individuals[uri].label("en")
    if uri in taxonomy.owl_properties:
        return taxonomy.owl_properties[uri].label("en")
    return _local(uri)


# ── Node detail builders ──────────────────────────────────────────────────────


def _detail_concept(concept: Concept, taxonomy: Taxonomy) -> dict:
    labels = [
        {
            "lang": lbl.lang,
            "kind": "pref" if lbl.type == LabelType.PREF else "alt",
            "value": lbl.value,
        }
        for lbl in concept.labels
    ]
    description = concept.definitions[0].value if concept.definitions else ""
    scope = concept.scope_notes[0].value if concept.scope_notes else ""
    relations: list[dict] = []
    for u in concept.broader:
        relations.append({"rel": "broader", "uri": u, "label": _label_for(u, taxonomy)})
    for u in concept.narrower:
        relations.append({"rel": "narrower", "uri": u, "label": _label_for(u, taxonomy)})
    for u in concept.related:
        relations.append({"rel": "related", "uri": u, "label": _label_for(u, taxonomy)})
    for u in concept.exact_match:
        relations.append({"rel": "exactMatch", "uri": u, "label": _label_for(u, taxonomy)})
    for u in concept.close_match:
        relations.append({"rel": "closeMatch", "uri": u, "label": _label_for(u, taxonomy)})
    for u in concept.broad_match:
        relations.append({"rel": "broadMatch", "uri": u, "label": _label_for(u, taxonomy)})
    for u in concept.narrow_match:
        relations.append({"rel": "narrowMatch", "uri": u, "label": _label_for(u, taxonomy)})
    for u in concept.related_match:
        relations.append({"rel": "relatedMatch", "uri": u, "label": _label_for(u, taxonomy)})
    return {
        "labels": labels,
        "description": description,
        "scopeNote": scope,
        "images": concept.schema_images,
        "videos": concept.schema_videos,
        "urls": concept.schema_urls,
        "relations": relations,
    }


def _detail_class(cls: RDFClass, taxonomy: Taxonomy) -> dict:
    labels = [{"lang": lbl.lang, "kind": "label", "value": lbl.value} for lbl in cls.labels]
    comments = [{"lang": c.lang, "value": c.value} for c in cls.comments]
    relations: list[dict] = []
    for u in cls.sub_class_of:
        if not is_builtin_uri(u):
            relations.append({"rel": "subClassOf", "uri": u, "label": _label_for(u, taxonomy)})
    for u in cls.equivalent_class:
        if not is_builtin_uri(u):
            relations.append({"rel": "equivalentClass", "uri": u, "label": _label_for(u, taxonomy)})
    for u in cls.disjoint_with:
        if not is_builtin_uri(u):
            relations.append({"rel": "disjointWith", "uri": u, "label": _label_for(u, taxonomy)})
    return {
        "labels": labels,
        "description": "",
        "scopeNote": "",
        "comments": comments,
        "images": cls.schema_images,
        "videos": cls.schema_videos,
        "urls": cls.schema_urls,
        "relations": relations,
    }


def _detail_individual(ind: OWLIndividual, taxonomy: Taxonomy) -> dict:
    labels = [{"lang": lbl.lang, "kind": "label", "value": lbl.value} for lbl in ind.labels]
    comments = [{"lang": c.lang, "value": c.value} for c in ind.comments]
    relations: list[dict] = []
    for u in ind.types:
        if not is_builtin_uri(u):
            relations.append({"rel": "type", "uri": u, "label": _label_for(u, taxonomy)})
    for prop_uri, val_uri in ind.property_values:
        prop = taxonomy.owl_properties.get(prop_uri)
        prop_label = prop.label("en") if prop else _local(prop_uri)
        relations.append(
            {"rel": prop_label, "uri": val_uri, "label": _label_for(val_uri, taxonomy)}
        )
    return {
        "labels": labels,
        "description": "",
        "scopeNote": "",
        "comments": comments,
        "images": ind.schema_images,
        "videos": ind.schema_videos,
        "urls": ind.schema_urls,
        "relations": relations,
    }


def _detail_scheme(scheme: ConceptScheme, _taxonomy: Taxonomy) -> dict:
    labels = [
        {
            "lang": lbl.lang,
            "kind": "pref" if lbl.type == LabelType.PREF else "alt",
            "value": lbl.value,
        }
        for lbl in scheme.labels
    ]
    description = scheme.descriptions[0].value if scheme.descriptions else ""
    return {
        "labels": labels,
        "description": description,
        "scopeNote": "",
        "images": [],
        "videos": [],
        "urls": [],
        "relations": [],
    }


# ── Taxonomy metadata (for detail panel default view) ─────────────────────────


def _taxonomy_meta(taxonomy: Taxonomy, file_path: Path | None) -> dict:
    title = _ontology_title(taxonomy, file_path)
    counts = {
        "classes": len(taxonomy.owl_classes),
        "individuals": len(taxonomy.owl_individuals),
        "properties": len(taxonomy.owl_properties),
        "schemes": len(taxonomy.schemes),
        "top_concepts": sum(1 for c in taxonomy.concepts.values() if c.top_concept_of),
        "concepts": len(taxonomy.concepts),
    }
    analyses = analyze_taxonomy(taxonomy)
    schemes_data: list[dict] = []
    for uri, analysis in analyses.items():
        scheme = taxonomy.schemes.get(uri)
        scheme_title = scheme.title("en") if scheme else _local(uri)
        schemes_data.append(
            {
                "scheme_uri": uri,
                "scheme_title": scheme_title,
                "stats": {
                    "total_concepts": analysis.stats.total_concepts,
                    "top_level_concepts": analysis.stats.top_level_concepts,
                    "max_depth": analysis.stats.max_depth,
                    "avg_depth": analysis.stats.avg_depth,
                    "languages": analysis.stats.languages,
                },
                "completions": [
                    {
                        "display_name": c.display_name,
                        "total": c.total,
                        "by_language": c.by_language,
                    }
                    for c in analysis.completions
                ],
                "issue_counts": {
                    "errors": sum(1 for i in analysis.issues if i.severity == "error"),
                    "warnings": sum(1 for i in analysis.issues if i.severity == "warning"),
                },
            }
        )
    return {
        "title": title,
        "ontology_uri": taxonomy.ontology_uri or "",
        "counts": counts,
        "schemes": schemes_data,
    }
