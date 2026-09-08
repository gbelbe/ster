"""Pure domain model — no RDF, no IO, no side effects."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

# ── OWL/RDFS layer ────────────────────────────────────────────────────────────

_BUILTIN_PREFIXES = (
    "http://www.w3.org/2002/07/owl#",  # NOSONAR - RDF namespace IRI
    "http://www.w3.org/2000/01/rdf-schema#",  # NOSONAR - RDF namespace IRI
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",  # NOSONAR - RDF namespace IRI
    "http://www.w3.org/2001/XMLSchema#",  # NOSONAR - RDF namespace IRI
)


def is_builtin_uri(uri: str) -> bool:
    """Return True for URIs from standard W3C namespaces (not user-defined)."""
    return any(uri.startswith(p) for p in _BUILTIN_PREFIXES)


class LabelType(str, Enum):
    PREF = "pref"
    ALT = "alt"
    HIDDEN = "hidden"


@dataclass
class Label:
    lang: str
    value: str
    type: LabelType = LabelType.PREF


@dataclass
class Definition:
    lang: str
    value: str


@dataclass
class Concept:
    uri: str
    labels: list[Label] = field(default_factory=list)
    definitions: list[Definition] = field(default_factory=list)
    scope_notes: list[Definition] = field(default_factory=list)
    broader: list[str] = field(default_factory=list)  # URIs (same scheme)
    narrower: list[str] = field(default_factory=list)  # URIs (same scheme)
    related: list[str] = field(default_factory=list)  # URIs (same scheme)
    top_concept_of: str | None = None  # scheme URI
    # foaf:focus → the OWL class this concept corresponds to (a concept↔class link,
    # distinct from punning). The class's individuals surface under the concept.
    focus: str | None = None
    # SKOS mapping properties — used for cross-scheme links
    broad_match: list[str] = field(default_factory=list)
    narrow_match: list[str] = field(default_factory=list)
    related_match: list[str] = field(default_factory=list)
    exact_match: list[str] = field(default_factory=list)
    close_match: list[str] = field(default_factory=list)
    # Rich-content annotations (schema.org)
    schema_images: list[str] = field(default_factory=list)  # schema:image URLs
    schema_videos: list[str] = field(default_factory=list)  # schema:video URLs
    schema_urls: list[str] = field(default_factory=list)  # schema:url URLs
    # Any *other* predicate on the concept (wgs:lat, geo:asWKT, a project's own
    # property, …), captured generically so the triple round-trips. Classes,
    # properties and schemes have always had this; without it a concept lost every
    # unmodelled predicate on save, silently.
    annotations: list[OntologyAnnotation] = field(default_factory=list)

    @property
    def local_name(self) -> str:
        for sep in ("#", "/"):
            if sep in self.uri:
                return self.uri.rsplit(sep, 1)[-1]
        return self.uri

    def pref_label(self, lang: str = "en") -> str:
        for lbl in self.labels:
            if lbl.type == LabelType.PREF and lbl.lang == lang:
                return lbl.value
        for lbl in self.labels:
            if lbl.type == LabelType.PREF:
                return lbl.value
        return self.local_name

    def pref_labels(self) -> dict[str, str]:
        return {lbl.lang: lbl.value for lbl in self.labels if lbl.type == LabelType.PREF}

    def alt_labels(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for lbl in self.labels:
            if lbl.type == LabelType.ALT:
                result.setdefault(lbl.lang, []).append(lbl.value)
        return result

    def definition(self, lang: str = "en") -> str | None:
        for defn in self.definitions:
            if defn.lang == lang:
                return defn.value
        return None


@dataclass
class OWLProperty:
    """An owl:ObjectProperty / owl:DatatypeProperty / rdfs:Property."""

    uri: str
    prop_type: str = (
        "ObjectProperty"  # ObjectProperty | DatatypeProperty | AnnotationProperty | Property
    )
    labels: list[Label] = field(default_factory=list)  # rdfs:label
    comments: list[Definition] = field(default_factory=list)  # rdfs:comment
    domains: list[str] = field(default_factory=list)  # rdfs:domain class URIs
    ranges: list[str] = field(default_factory=list)  # rdfs:range URIs
    sub_property_of: list[str] = field(default_factory=list)  # rdfs:subPropertyOf
    inverse_of: list[str] = field(default_factory=list)  # owl:inverseOf
    is_functional: bool = False  # owl:FunctionalProperty
    note: str = ""  # ns1:note markdown annotation
    # Any *other* predicate used on the property (skos:note, dcterms:source, …),
    # captured generically so metadata quality can be assessed and round-tripped.
    annotations: list[OntologyAnnotation] = field(default_factory=list)

    @property
    def local_name(self) -> str:
        for sep in ("#", "/"):
            if sep in self.uri:
                return self.uri.rsplit(sep, 1)[-1]
        return self.uri

    def label(self, lang: str = "en") -> str:
        for lbl in self.labels:
            if lbl.lang == lang:
                return lbl.value
        if self.labels:
            return self.labels[0].value
        return self.local_name


@dataclass
class OWLIndividual:
    """An owl:NamedIndividual (or instance typed as a known OWL class)."""

    uri: str
    labels: list[Label] = field(default_factory=list)  # rdfs:label
    comments: list[Definition] = field(default_factory=list)  # rdfs:comment
    types: list[str] = field(default_factory=list)  # rdf:type class URIs (user-defined only)
    # URI-valued property assertions: (property_uri, target_uri)
    property_values: list[tuple[str, str]] = field(default_factory=list)
    # Literal-valued property assertions: (property_uri, value_str, lang_or_datatype)
    # lang_or_datatype: "@en" for lang tags, full datatype URI for typed literals, "" for plain
    literal_values: list[tuple[str, str, str]] = field(default_factory=list)
    schema_images: list[str] = field(default_factory=list)  # schema:image URLs
    schema_videos: list[str] = field(default_factory=list)  # schema:video URLs
    schema_urls: list[str] = field(default_factory=list)  # schema:url URLs
    note: str = ""  # ns1:note markdown annotation

    @property
    def local_name(self) -> str:
        for sep in ("#", "/"):
            if sep in self.uri:
                return self.uri.rsplit(sep, 1)[-1]
        return self.uri

    def label(self, lang: str = "en") -> str:
        for lbl in self.labels:
            if lbl.lang == lang:
                return lbl.value
        if self.labels:
            return self.labels[0].value
        return self.local_name


@dataclass
class RDFClass:
    """An rdfs:Class or owl:Class node — the OWL/RDFS layer of a graph."""

    uri: str
    labels: list[Label] = field(default_factory=list)  # rdfs:label
    comments: list[Definition] = field(default_factory=list)  # rdfs:comment
    sub_class_of: list[str] = field(default_factory=list)  # rdfs:subClassOf URIs
    equivalent_class: list[str] = field(default_factory=list)  # owl:equivalentClass URIs
    disjoint_with: list[str] = field(default_factory=list)  # owl:disjointWith URIs
    schema_images: list[str] = field(default_factory=list)  # schema:image URLs
    schema_videos: list[str] = field(default_factory=list)  # schema:video URLs
    schema_urls: list[str] = field(default_factory=list)  # schema:url URLs
    note: str = ""  # ns1:note markdown annotation
    # Any *other* predicate used on the class (skos:note, rdfs:seeAlso, …), captured
    # generically so metadata quality can be assessed and the triple round-trips.
    annotations: list[OntologyAnnotation] = field(default_factory=list)

    @property
    def local_name(self) -> str:
        for sep in ("#", "/"):
            if sep in self.uri:
                return self.uri.rsplit(sep, 1)[-1]
        return self.uri

    def label(self, lang: str = "en") -> str:
        for lbl in self.labels:
            if lbl.lang == lang:
                return lbl.value
        if self.labels:
            return self.labels[0].value
        return self.local_name


@dataclass
class OntologyAnnotation:
    """A single descriptive metadata triple on an ontology / scheme subject.

    Generic — captures *any* predicate present in the file, known or not, so the
    overview can display and edit every descriptive property. ``value`` is the
    IRI (when ``is_iri``) or the literal lexical form; ``lang`` / ``datatype`` are
    mutually exclusive and apply to literals only.
    """

    predicate: str  # full predicate URI
    value: str  # IRI string (is_iri) or literal lexical form
    is_iri: bool = False
    lang: str = ""
    datatype: str = ""  # datatype URI (e.g. xsd:date), literals only


# Predicate URIs for the well-known ontology fields exposed as typed accessors.
_RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"  # NOSONAR - RDF predicate/property IRI
_DCT_TITLE = "http://purl.org/dc/terms/title"  # NOSONAR - RDF predicate/property IRI
_DCT_DESCRIPTION = "http://purl.org/dc/terms/description"  # NOSONAR - RDF predicate/property IRI
_OWL_VERSION_INFO = (
    "http://www.w3.org/2002/07/owl#versionInfo"  # NOSONAR - RDF predicate/property IRI
)

_OWL_VERSION_IRI = (
    "http://www.w3.org/2002/07/owl#versionIRI"  # NOSONAR - RDF predicate/property IRI
)

_OWL_PRIOR_VERSION = (
    "http://www.w3.org/2002/07/owl#priorVersion"  # NOSONAR - RDF predicate/property IRI
)


@dataclass
class ConceptScheme:
    uri: str
    labels: list[Label] = field(default_factory=list)
    descriptions: list[Definition] = field(default_factory=list)
    top_concepts: list[str] = field(default_factory=list)  # URIs
    creator: str = ""
    created: str = ""  # ISO date string e.g. "2026-03-25"
    languages: list[str] = field(default_factory=list)  # declared language codes
    base_uri: str = ""  # namespace prefix for auto-generating concept URIs
    # Any *other* descriptive predicate on the scheme (skos:note, dct:subject, …)
    annotations: list[OntologyAnnotation] = field(default_factory=list)

    @property
    def local_name(self) -> str:
        for sep in ("#", "/"):
            if sep in self.uri:
                return self.uri.rstrip("/").rsplit(sep, 1)[-1]
        return self.uri

    def title(self, lang: str = "en") -> str:
        for lbl in self.labels:
            if lbl.type == LabelType.PREF and lbl.lang == lang:
                return lbl.value
        for lbl in self.labels:
            if lbl.type == LabelType.PREF:
                return lbl.value
        return self.local_name


@dataclass
class Taxonomy:
    schemes: dict[str, ConceptScheme] = field(default_factory=dict)  # uri → scheme
    concepts: dict[str, Concept] = field(default_factory=dict)  # uri → concept
    owl_classes: dict[str, RDFClass] = field(default_factory=dict)  # uri → class
    owl_individuals: dict[str, OWLIndividual] = field(default_factory=dict)  # uri → individual
    owl_properties: dict[str, OWLProperty] = field(default_factory=dict)  # uri → property
    ontology_uri: str | None = field(default=None)  # owl:Ontology URI if declared
    # Generic descriptive metadata on the owl:Ontology node — every predicate
    # present in the file. The well-known few (label/title/description/version*)
    # are exposed as typed properties below, backed by this single store.
    ontology_annotations: list[OntologyAnnotation] = field(default_factory=list)
    # handle → uri (populated by handles.assign_handles)
    handle_index: dict[str, str] = field(default_factory=dict)
    # prefix → namespace URL (from source file; used for round-trip serialisation)
    namespace_bindings: dict[str, str] = field(default_factory=dict, compare=False, repr=False)
    # set by store.load() — the file this taxonomy was loaded from
    file_path: Path | None = field(default=None, compare=False, repr=False)
    # Every triple the model does not describe, kept verbatim so saving gives the
    # file back. The annotations bucket above covers an unknown *predicate* on a
    # known entity; this covers what has no entity here at all — an OWL class
    # expression hanging off a blank node, a prov:Entity, an rdf:List. Losing
    # those silently is worse than not editing them, so they are carried through
    # untouched. Excluded from equality: two taxonomies mean the same thing
    # whether or not they remember the same residue.
    residue: list[tuple] = field(default_factory=list, compare=False, repr=False)
    # Top concepts ster worked out rather than read. A concept with no broader
    # has to hang somewhere for the tree to show it, but that is a decision about
    # display and must not be written back as though the author asserted it.
    inferred_top_concepts: set[str] = field(default_factory=set, compare=False, repr=False)
    # Classes ster only ever saw *mentioned* — as a subClassOf target, a domain,
    # a restriction filler — and never declared. They belong in the model so the
    # tree can show them, but writing `a owl:Class` for one asserts something
    # the author did not: wine.rdf gained 163 declarations that way.
    inferred_classes: set[str] = field(default_factory=set, compare=False, repr=False)
    # Individuals the file typed only by their class. OWL 2 conventionally also
    # writes `a owl:NamedIndividual`, and Protégé does, but a file that left it
    # out did so on purpose or by habit — either way it is not ster's to add.
    # wine.rdf gained 161 of them.
    inferred_named_individuals: set[str] = field(default_factory=set, compare=False, repr=False)

    # Entities loaded from read-only *context* files, mapped to the file each came
    # from. Membership is the read-only flag; the value answers "where is this
    # defined?", which is the first thing asked of an entity you cannot edit.
    # Everything here is excluded when the taxonomy is serialised, so saving can
    # never absorb a context file into the editable one.
    context_source: dict[str, Path] = field(default_factory=dict, compare=False, repr=False)

    # ── typed accessors over the generic annotation store ─────────────────────
    # These keep the historical ``taxonomy.ontology_title`` etc. API working
    # while the single source of truth is ``ontology_annotations``.
    def _get_annotation(self, predicate: str) -> str | None:
        for a in self.ontology_annotations:
            if a.predicate == predicate:
                return a.value
        return None

    def _set_annotation(self, predicate: str, value: str | None, *, is_iri: bool = False) -> None:
        self.ontology_annotations = [
            a for a in self.ontology_annotations if a.predicate != predicate
        ]
        if value is not None:
            self.ontology_annotations.append(
                OntologyAnnotation(predicate=predicate, value=value, is_iri=is_iri)
            )

    @property
    def ontology_label(self) -> str | None:
        return self._get_annotation(_RDFS_LABEL)

    @ontology_label.setter
    def ontology_label(self, value: str | None) -> None:
        self._set_annotation(_RDFS_LABEL, value)

    @property
    def ontology_title(self) -> str | None:
        """The stated title, or the label standing in for one.

        A fallback, not a back-fill. Showing the label where no title exists is
        a display decision; writing dcterms:title into the file because someone
        opened it is a claim they never made. This used to be done by mutating
        the model on load, and the assertion was then serialised.
        """
        return self._get_annotation(_DCT_TITLE) or self._get_annotation(_RDFS_LABEL)

    @ontology_title.setter
    def ontology_title(self, value: str | None) -> None:
        self._set_annotation(_DCT_TITLE, value)

    @property
    def ontology_description(self) -> str | None:
        """The stated description, or the label standing in for one — see
        :attr:`ontology_title` for why this is a fallback and not a back-fill."""
        return self._get_annotation(_DCT_DESCRIPTION) or self._get_annotation(_RDFS_LABEL)

    @ontology_description.setter
    def ontology_description(self, value: str | None) -> None:
        self._set_annotation(_DCT_DESCRIPTION, value)

    @property
    def version_info(self) -> str | None:
        return self._get_annotation(_OWL_VERSION_INFO)

    @version_info.setter
    def version_info(self, value: str | None) -> None:
        self._set_annotation(_OWL_VERSION_INFO, value)

    @property
    def version_iri(self) -> str | None:
        return self._get_annotation(_OWL_VERSION_IRI)

    @version_iri.setter
    def version_iri(self, value: str | None) -> None:
        self._set_annotation(_OWL_VERSION_IRI, value, is_iri=True)

    @property
    def prior_version(self) -> str | None:
        return self._get_annotation(_OWL_PRIOR_VERSION)

    @prior_version.setter
    def prior_version(self, value: str | None) -> None:
        self._set_annotation(_OWL_PRIOR_VERSION, value, is_iri=True)

    def node_type(self, uri: str) -> str:
        """Return the RDF type: 'promoted', 'concept', 'class', 'individual', 'property', or 'unknown'."""
        in_concepts = uri in self.concepts
        in_classes = uri in self.owl_classes
        if in_concepts and in_classes:
            return "promoted"
        if in_concepts:
            return "linked" if self.concepts[uri].focus else "concept"
        if in_classes:
            return "class"
        if uri in self.owl_individuals:
            return "individual"
        if uri in self.owl_properties:
            return "property"
        return "unknown"

    def uri_taken(self, uri: str) -> bool:
        """True when *uri* already identifies an entity in any layer — a concept, scheme,
        OWL class, individual, or property. New entities must not reuse a URI; the one
        deliberate shared URI (a pun's concept + class) is minted only via
        ``promote_concept_to_class``, which does not go through the create ops."""
        return (
            uri in self.concepts
            or uri in self.schemes
            or uri in self.owl_classes
            or uri in self.owl_individuals
            or uri in self.owl_properties
        )

    def resolve(self, handle_or_uri: str) -> str | None:
        """Return URI for a handle, local name, or full URI. Returns None if not found."""
        # 1. Full URI — pass through if known
        if "://" in handle_or_uri:
            return (
                handle_or_uri
                if handle_or_uri in self.concepts
                or handle_or_uri in self.schemes
                or handle_or_uri in self.owl_classes
                or handle_or_uri in self.owl_individuals
                or handle_or_uri in self.owl_properties
                else None
            )
        # 2. Handle lookup (case-insensitive)
        uri = self.handle_index.get(handle_or_uri.upper())
        if uri:
            return uri
        # 3. Local name lookup
        for u, concept in self.concepts.items():
            if concept.local_name == handle_or_uri:
                return u
        return None

    def _base_uri_from_ontology(self) -> str | None:
        if not (
            self.ontology_uri
            and self.ontology_uri.startswith(
                (
                    "http://",  # NOSONAR - scheme prefix, not a URL
                    "https://",
                )
            )
        ):
            return None
        uri = self.ontology_uri
        if uri.endswith(("/", "#")):
            return uri
        # Detect separator from existing class / property URIs
        root = uri.rstrip("#/")
        for existing in list(self.owl_classes) + list(self.owl_properties):
            if existing.startswith(root) and len(existing) > len(root):
                sep = existing[len(root)]
                if sep in ("#", "/"):
                    return root + sep
        return root + "#"

    def _base_uri_from_concepts(self) -> str | None:
        if not self.concepts:
            return None
        uris = list(self.concepts)
        prefix = uris[0]
        for u in uris[1:]:
            while not u.startswith(prefix):
                idx = max(prefix.rfind("/"), prefix.rfind("#"))
                if idx <= 0:
                    prefix = ""
                    break
                prefix = prefix[: idx + 1]
        if prefix.endswith(("/", "#")):
            return prefix
        return None

    @staticmethod
    def _base_uri_from_scheme(scheme: ConceptScheme | None) -> str | None:
        if not scheme:
            return None
        s = scheme.uri.rstrip("/")
        for sep in ("#", "/"):
            if sep in s:
                return s.rsplit(sep, 1)[0] + sep
        return None

    def base_uri(self) -> str:
        """Return the base URI for auto-generating entity URIs.

        Priority:
        1. scheme.base_uri (explicit SKOS override)
        2. ontology_uri (http/https only — file:// is skipped)
        3. Derived from existing concept URIs (common prefix)
        4. Derived from scheme URI
        5. Empty string
        """
        scheme = self.primary_scheme()
        if scheme and scheme.base_uri:
            return scheme.base_uri
        return (
            self._base_uri_from_ontology()
            or self._base_uri_from_concepts()
            or self._base_uri_from_scheme(scheme)
            or ""
        )

    def uri_to_handle(self, uri: str) -> str | None:
        for h, u in self.handle_index.items():
            if u == uri:
                return h
        return None

    def primary_scheme(self) -> ConceptScheme | None:
        if self.schemes:
            return next(iter(self.schemes.values()))
        return None
