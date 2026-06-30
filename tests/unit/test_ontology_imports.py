"""Unit tests for ster.ontology_imports."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

# ── helpers ───────────────────────────────────────────────────────────────────

_FOAF_NS = "http://xmlns.com/foaf/0.1/"
_FOAF_PERSON = f"{_FOAF_NS}Person"
_FOAF_AGENT = f"{_FOAF_NS}Agent"
_FOAF_KNOWS = f"{_FOAF_NS}knows"
_SCHEMA_NS = "https://schema.org/"
_SCHEMA_PERSON = f"{_SCHEMA_NS}Person"

_KAI_NS = "http://example.org/kai#"
_KAI_PERSON = f"{_KAI_NS}Person"
_KAI_KNOWS = f"{_KAI_NS}knows"


def _make_taxonomy(
    *,
    class_uris: list[str] | None = None,
    subclass_of: dict[str, list[str]] | None = None,
    individual_types: list[str] | None = None,
    property_uris: list[str] | None = None,
    property_domains: dict[str, list[str]] | None = None,
    namespace_bindings: dict[str, str] | None = None,
):
    """Return a minimal stub Taxonomy-like object."""
    from unittest.mock import MagicMock

    taxonomy = MagicMock()
    taxonomy.namespace_bindings = namespace_bindings if namespace_bindings is not None else {}
    owl_classes = {}
    for uri in class_uris or []:
        cls = MagicMock()
        cls.sub_class_of = subclass_of.get(uri, []) if subclass_of else []
        owl_classes[uri] = cls
    taxonomy.owl_classes = owl_classes

    owl_individuals = {}
    for i, t_uri in enumerate(individual_types or []):
        ind = MagicMock()
        ind.types = [t_uri]
        owl_individuals[f"{_KAI_NS}ind{i}"] = ind
    taxonomy.owl_individuals = owl_individuals

    owl_properties = {}
    for p_uri in property_uris or []:
        prop = MagicMock()
        prop.uri = p_uri
        prop.prop_type = "ObjectProperty"
        prop.domains = property_domains.get(p_uri, []) if property_domains else []
        prop.labels = []
        owl_properties[p_uri] = prop
    taxonomy.owl_properties = owl_properties

    return taxonomy


def _make_foaf_rdf() -> str:
    """Minimal FOAF snippet with foaf:knows."""
    return """\
@prefix foaf: <http://xmlns.com/foaf/0.1/> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .

foaf:Person a owl:Class .
foaf:Agent  a owl:Class .
foaf:knows  a owl:ObjectProperty ;
    rdfs:domain foaf:Person ;
    rdfs:label  "knows" .
"""


# ── find_external_class_refs ──────────────────────────────────────────────────


def test_find_external_class_refs_subclass():
    from ster.ontology_imports import find_external_class_refs

    taxonomy = _make_taxonomy(
        class_uris=[_KAI_PERSON],
        subclass_of={_KAI_PERSON: [_FOAF_PERSON]},
    )
    refs = find_external_class_refs(taxonomy)
    assert _FOAF_PERSON in refs


def test_find_external_class_refs_type():
    from ster.ontology_imports import find_external_class_refs

    taxonomy = _make_taxonomy(individual_types=[_SCHEMA_PERSON])
    refs = find_external_class_refs(taxonomy)
    assert _SCHEMA_PERSON in refs


def test_find_external_class_refs_local_only():
    from ster.ontology_imports import find_external_class_refs

    taxonomy = _make_taxonomy(
        class_uris=[_KAI_PERSON],
        subclass_of={_KAI_PERSON: []},
        individual_types=[_KAI_PERSON],
    )
    refs = find_external_class_refs(taxonomy)
    assert refs == set()


# ── namespace_url_from_uri ────────────────────────────────────────────────────


def test_namespace_from_uri_hash():
    from ster.ontology_imports import namespace_url_from_uri

    assert namespace_url_from_uri(_FOAF_PERSON) == _FOAF_NS


def test_namespace_from_uri_slash():
    from ster.ontology_imports import namespace_url_from_uri

    assert namespace_url_from_uri(_SCHEMA_PERSON) == _SCHEMA_NS


# ── fetch_ontology ────────────────────────────────────────────────────────────


def _foaf_cache_filename() -> str:
    import hashlib

    ns = _FOAF_NS
    key = hashlib.md5(ns.encode(), usedforsecurity=False).hexdigest()[:8]
    slug = ns.replace("https://", "").replace("http://", "").replace("/", "_")
    return f"{slug}{key}.ttl"


def test_fetch_ontology_uses_cache(tmp_path: Path):
    from ster.ontology_imports import fetch_ontology

    cache_file = tmp_path / _foaf_cache_filename()
    cache_file.write_text(_make_foaf_rdf(), encoding="utf-8")

    with patch("ster.ontology_imports.urllib.request.urlopen") as mock_open:
        g = fetch_ontology(_FOAF_NS, cache_dir=tmp_path)

    mock_open.assert_not_called()
    assert g is not None
    assert len(g) > 0


def test_fetch_ontology_writes_cache(tmp_path: Path):
    from ster.ontology_imports import fetch_ontology

    response = MagicMock()
    response.read.return_value = _make_foaf_rdf().encode()
    response.__enter__ = lambda s: s
    response.__exit__ = MagicMock(return_value=False)

    with patch("ster.ontology_imports.urllib.request.urlopen", return_value=response):
        g = fetch_ontology(_FOAF_NS, cache_dir=tmp_path)

    assert g is not None
    assert len(g) > 0
    cache_files = list(tmp_path.glob("*.ttl"))
    assert len(cache_files) == 1


def test_fetch_ontology_unreachable(tmp_path: Path):
    import urllib.error

    from ster.ontology_imports import fetch_ontology

    with patch(
        "ster.ontology_imports.urllib.request.urlopen",
        side_effect=urllib.error.URLError("timeout"),
    ):
        g = fetch_ontology(_FOAF_NS, cache_dir=tmp_path)

    assert g is not None
    assert len(g) == 0


# ── get_properties_for_class ──────────────────────────────────────────────────


def _foaf_graph():
    import rdflib

    g = rdflib.Graph()
    g.parse(data=_make_foaf_rdf(), format="turtle")
    return g


def test_properties_for_class_direct_domain():
    from ster.ontology_imports import get_properties_for_class

    g = _foaf_graph()
    props = get_properties_for_class(g, _FOAF_PERSON, superclasses=set())
    uris = [p.uri for p in props]
    assert _FOAF_KNOWS in uris


def test_properties_for_class_superclass_domain():
    # Add foaf:mbox with domain foaf:Agent
    import rdflib

    from ster.ontology_imports import get_properties_for_class

    g = _foaf_graph()
    FOAF = rdflib.Namespace(_FOAF_NS)
    OWL = rdflib.OWL
    RDFS = rdflib.RDFS
    g.add((FOAF.mbox, rdflib.RDF.type, OWL.ObjectProperty))
    g.add((FOAF.mbox, RDFS.domain, FOAF.Agent))

    props = get_properties_for_class(g, _FOAF_PERSON, superclasses={_FOAF_AGENT})
    uris = [p.uri for p in props]
    assert f"{_FOAF_NS}mbox" in uris


def test_properties_for_class_no_domain():
    import rdflib

    from ster.ontology_imports import get_properties_for_class

    g = rdflib.Graph()
    FOAF = rdflib.Namespace(_FOAF_NS)
    OWL = rdflib.OWL
    RDFS = rdflib.RDFS
    g.add((FOAF.title, rdflib.RDF.type, OWL.DatatypeProperty))
    g.add((FOAF.title, RDFS.label, rdflib.Literal("title")))

    props = get_properties_for_class(g, _FOAF_PERSON, superclasses=set())
    uris = [p.uri for p in props]
    assert f"{_FOAF_NS}title" in uris


# ── suggest_external_properties ──────────────────────────────────────────────


# ── is_external_uri ───────────────────────────────────────────────────────────


def test_is_external_uri_foreign_ns():
    from ster.ontology_imports import is_external_uri

    taxonomy = _make_taxonomy(
        class_uris=[_KAI_PERSON],
        namespace_bindings={"foaf": _FOAF_NS},
    )
    assert is_external_uri(_FOAF_PERSON, taxonomy) is True


def test_is_external_uri_primary_ns():
    from ster.ontology_imports import is_external_uri

    taxonomy = _make_taxonomy(class_uris=[_KAI_PERSON])
    assert is_external_uri(_KAI_PERSON, taxonomy) is False


def test_is_external_uri_builtin():
    from ster.ontology_imports import is_external_uri

    taxonomy = _make_taxonomy()
    assert is_external_uri("http://www.w3.org/2002/07/owl#Class", taxonomy) is False


def test_is_external_uri_no_bindings():
    from ster.ontology_imports import is_external_uri

    taxonomy = _make_taxonomy()
    assert is_external_uri(_FOAF_PERSON, taxonomy) is False


# ── prefix_label ──────────────────────────────────────────────────────────────


def test_prefix_label_known_ns():
    from ster.ontology_imports import prefix_label

    taxonomy = _make_taxonomy(namespace_bindings={"foaf": _FOAF_NS})
    assert prefix_label(_FOAF_PERSON, taxonomy) == "foaf:Person"


def test_prefix_label_unknown_ns():
    from ster.ontology_imports import prefix_label

    taxonomy = _make_taxonomy()
    assert prefix_label("http://unknown.org/ns#Thing", taxonomy) == "Thing"


# ── COMMON_ONTOLOGIES ─────────────────────────────────────────────────────────


def test_common_ontologies_list():
    from ster.ontology_imports import COMMON_ONTOLOGIES

    assert len(COMMON_ONTOLOGIES) >= 4
    names = [entry[0] for entry in COMMON_ONTOLOGIES]
    assert any("FOAF" in n for n in names)
    assert any("Schema" in n for n in names)


# ── add_namespace_to_taxonomy ─────────────────────────────────────────────────


def test_add_namespace_writes_binding():
    from ster.ontology_imports import add_namespace_to_taxonomy

    taxonomy = _make_taxonomy(namespace_bindings={})
    add_namespace_to_taxonomy(_FOAF_NS, "foaf", taxonomy)
    assert taxonomy.namespace_bindings["foaf"] == _FOAF_NS


def test_add_namespace_idempotent():
    from ster.ontology_imports import add_namespace_to_taxonomy

    taxonomy = _make_taxonomy(namespace_bindings={"foaf": _FOAF_NS})
    add_namespace_to_taxonomy(_FOAF_NS, "foaf", taxonomy)
    assert taxonomy.namespace_bindings["foaf"] == _FOAF_NS
    assert len(taxonomy.namespace_bindings) == 1


# ── suggest_properties_merged (existing) ─────────────────────────────────────


def test_suggest_properties_merged(tmp_path: Path):
    from ster.ontology_imports import suggest_external_properties

    taxonomy = _make_taxonomy(
        class_uris=[_KAI_PERSON],
        subclass_of={_KAI_PERSON: [_FOAF_PERSON]},
        individual_types=[_KAI_PERSON],
        property_uris=[_KAI_KNOWS],
        property_domains={_KAI_KNOWS: [_KAI_PERSON]},
    )

    response = MagicMock()
    response.read.return_value = _make_foaf_rdf().encode()
    response.__enter__ = lambda s: s
    response.__exit__ = MagicMock(return_value=False)

    with patch("ster.ontology_imports.urllib.request.urlopen", return_value=response):
        props = suggest_external_properties(
            taxonomy,
            individual_types=[_KAI_PERSON],
            cache_dir=tmp_path,
        )

    uris = [p.uri for p in props]
    assert _FOAF_KNOWS in uris
    assert len(uris) == len(set(uris)), "duplicate URIs found"


# ── is_annotation_property ───────────────────────────────────────────────────

_SKOS_NS = "http://www.w3.org/2004/02/skos/core#"
_FOAF_DEPICTION = f"{_FOAF_NS}depiction"
_SKOS_SCOPE_NOTE = f"{_SKOS_NS}scopeNote"


def test_well_known_predicates_are_annotation_properties():
    """Common annotation predicates beyond dcterms (foaf, skos) are recognised."""
    from ster.ontology_imports import is_annotation_property

    taxonomy = _make_taxonomy()
    assert is_annotation_property(taxonomy, _FOAF_DEPICTION)
    assert is_annotation_property(taxonomy, _SKOS_SCOPE_NOTE)


def test_unknown_predicate_is_not_an_annotation_property():
    """A bespoke URI with no declaration anywhere is not recognised."""
    from ster.ontology_imports import is_annotation_property

    taxonomy = _make_taxonomy()
    assert not is_annotation_property(taxonomy, f"{_KAI_NS}bespoke")


def test_locally_declared_annotation_property_is_recognised():
    """A URI declared owl:AnnotationProperty in the local ontology is recognised."""
    from ster.ontology_imports import is_annotation_property

    uri = f"{_KAI_NS}myAnno"
    taxonomy = _make_taxonomy()
    prop = MagicMock()
    prop.prop_type = "AnnotationProperty"
    taxonomy.owl_properties[uri] = prop
    assert is_annotation_property(taxonomy, uri)


def test_locally_declared_non_annotation_property_is_not_recognised():
    """A URI declared as a different property type is not an annotation property."""
    from ster.ontology_imports import is_annotation_property

    uri = f"{_KAI_NS}knows2"
    taxonomy = _make_taxonomy()
    prop = MagicMock()
    prop.prop_type = "ObjectProperty"
    taxonomy.owl_properties[uri] = prop
    assert not is_annotation_property(taxonomy, uri)


def test_external_cached_annotation_property_is_recognised(tmp_path, monkeypatch):
    """A predicate declared owl:AnnotationProperty in a bound, cached external
    ontology is recognised; the same predicate with no binding is not."""
    import rdflib

    from ster import ontology_imports
    from ster.ontology_imports import is_annotation_property

    cache = tmp_path / "ont-cache"
    cache.mkdir()
    monkeypatch.setattr(ontology_imports, "_DEFAULT_CACHE_DIR", cache)

    ns = "https://ext.example.org/v#"
    uri = f"{ns}myAnno"
    g = rdflib.Graph()
    g.add((rdflib.URIRef(uri), rdflib.RDF.type, rdflib.OWL.AnnotationProperty))
    g.serialize(destination=str(ontology_imports._cache_file(ns, cache)), format="turtle")

    bound = _make_taxonomy(namespace_bindings={"ext": ns})
    assert is_annotation_property(bound, uri)

    unbound = _make_taxonomy()
    assert not is_annotation_property(unbound, uri)


def test_external_cached_non_annotation_property_is_not_recognised(tmp_path, monkeypatch):
    """A predicate present in the cached external ontology but NOT typed as an
    annotation property is not recognised."""
    import rdflib

    from ster import ontology_imports
    from ster.ontology_imports import is_annotation_property

    cache = tmp_path / "ont-cache"
    cache.mkdir()
    monkeypatch.setattr(ontology_imports, "_DEFAULT_CACHE_DIR", cache)

    ns = "https://ext.example.org/v#"
    uri = f"{ns}someObjectProp"
    g = rdflib.Graph()
    g.add((rdflib.URIRef(uri), rdflib.RDF.type, rdflib.OWL.ObjectProperty))
    g.serialize(destination=str(ontology_imports._cache_file(ns, cache)), format="turtle")

    bound = _make_taxonomy(namespace_bindings={"ext": ns})
    assert not is_annotation_property(bound, uri)
