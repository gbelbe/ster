"""Pure domain model — no RDF, no IO, no side effects."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

# ── OWL/RDFS layer ────────────────────────────────────────────────────────────

_BUILTIN_PREFIXES = (
    "http://www.w3.org/2002/07/owl#",
    "http://www.w3.org/2000/01/rdf-schema#",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "http://www.w3.org/2001/XMLSchema#",
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
    # SKOS mapping properties — used for cross-scheme links
    broad_match: list[str] = field(default_factory=list)
    narrow_match: list[str] = field(default_factory=list)
    related_match: list[str] = field(default_factory=list)
    exact_match: list[str] = field(default_factory=list)
    close_match: list[str] = field(default_factory=list)

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
class RDFClass:
    """An rdfs:Class or owl:Class node — the OWL/RDFS layer of a graph."""

    uri: str
    labels: list[Label] = field(default_factory=list)  # rdfs:label
    comments: list[Definition] = field(default_factory=list)  # rdfs:comment
    sub_class_of: list[str] = field(default_factory=list)  # rdfs:subClassOf URIs
    equivalent_class: list[str] = field(default_factory=list)  # owl:equivalentClass URIs
    disjoint_with: list[str] = field(default_factory=list)  # owl:disjointWith URIs

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
class ConceptScheme:
    uri: str
    labels: list[Label] = field(default_factory=list)
    descriptions: list[Definition] = field(default_factory=list)
    top_concepts: list[str] = field(default_factory=list)  # URIs
    creator: str = ""
    created: str = ""  # ISO date string e.g. "2026-03-25"
    languages: list[str] = field(default_factory=list)  # declared language codes
    base_uri: str = ""  # namespace prefix for auto-generating concept URIs

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
    # handle → uri (populated by handles.assign_handles)
    handle_index: dict[str, str] = field(default_factory=dict)
    # set by store.load() — the file this taxonomy was loaded from
    file_path: Path | None = field(default=None, compare=False, repr=False)

    def node_type(self, uri: str) -> str:
        """Return the RDF type of a node: 'promoted', 'concept', 'class', or 'unknown'."""
        in_concepts = uri in self.concepts
        in_classes = uri in self.owl_classes
        if in_concepts and in_classes:
            return "promoted"
        if in_concepts:
            return "concept"
        if in_classes:
            return "class"
        return "unknown"

    def resolve(self, handle_or_uri: str) -> str | None:
        """Return URI for a handle, local name, or full URI. Returns None if not found."""
        # 1. Full URI — pass through if known
        if "://" in handle_or_uri:
            return (
                handle_or_uri
                if handle_or_uri in self.concepts or handle_or_uri in self.schemes
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

    def base_uri(self) -> str:
        """Return the base URI for auto-generating concept URIs."""
        scheme = self.primary_scheme()
        if scheme and scheme.base_uri:
            return scheme.base_uri
        # Derive from existing concept URIs (common prefix)
        if self.concepts:
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
        # Derive from scheme URI
        if scheme:
            s = scheme.uri.rstrip("/")
            for sep in ("#", "/"):
                if sep in s:
                    return s.rsplit(sep, 1)[0] + sep
        return ""

    def uri_to_handle(self, uri: str) -> str | None:
        for h, u in self.handle_index.items():
            if u == uri:
                return h
        return None

    def primary_scheme(self) -> ConceptScheme | None:
        if self.schemes:
            return next(iter(self.schemes.values()))
        return None
