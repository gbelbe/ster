"""TaxonomyWorkspace — holds all open Taxonomy objects for a session.

The workspace is the central runtime object for multi-file editing.
Individual files are loaded and saved through their own Taxonomy; the workspace
provides a unified read view and cross-file resolution utilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import store
from .model import Concept, ConceptScheme, Taxonomy


@dataclass
class TaxonomyWorkspace:
    """All open taxonomies for the current editing session (ordered dict)."""

    taxonomies: dict[Path, Taxonomy] = field(default_factory=dict)

    # ── loading ───────────────────────────────────────────────────────────────

    @classmethod
    def from_files(cls, paths: list[Path]) -> TaxonomyWorkspace:
        """Load all *paths* and return a new workspace."""
        ws = cls()
        for p in paths:
            taxonomy = store.load(p)
            ws.taxonomies[p] = taxonomy
        return ws

    @classmethod
    def from_taxonomy(cls, taxonomy: Taxonomy, path: Path) -> TaxonomyWorkspace:
        """Wrap a single already-loaded Taxonomy in a workspace."""
        ws = cls()
        ws.taxonomies[path] = taxonomy
        return ws

    def add_file(self, path: Path) -> Taxonomy:
        """Load *path* and add it to the workspace."""
        taxonomy = store.load(path)
        self.taxonomies[path] = taxonomy
        return taxonomy

    # ── saving ────────────────────────────────────────────────────────────────

    def save_file(self, path: Path) -> None:
        t = self.taxonomies.get(path)
        if t is not None:
            store.save(t, path)

    def save_all(self) -> None:
        for path, t in self.taxonomies.items():
            store.save(t, path)

    # ── merged view (used by single-taxonomy code paths in the viewer) ────────

    def merged_taxonomy(self) -> Taxonomy:
        """Return a single Taxonomy that merges all concepts and schemes.

        Used so that existing single-taxonomy navigation code works unchanged.
        Mutations to this object are NOT written back; always mutate the source
        taxonomy directly and call merged_taxonomy() again after rebuilding.
        """
        merged = Taxonomy()
        for taxonomy in self.taxonomies.values():
            merged.schemes.update(taxonomy.schemes)
            merged.concepts.update(taxonomy.concepts)
            merged.handle_index.update(taxonomy.handle_index)
        return merged

    # ── per-URI resolution ────────────────────────────────────────────────────

    def uri_to_file(self, uri: str) -> Path | None:
        """Return the file path that owns *uri* (concept or scheme)."""
        for path, t in self.taxonomies.items():
            if uri in t.concepts or uri in t.schemes:
                return path
        return None

    def taxonomy_for_uri(self, uri: str) -> Taxonomy | None:
        """Return the Taxonomy that owns *uri*."""
        for t in self.taxonomies.values():
            if uri in t.concepts or uri in t.schemes:
                return t
        return None

    def concept_for(self, uri: str) -> tuple[Path, Concept] | None:
        for path, t in self.taxonomies.items():
            if uri in t.concepts:
                return path, t.concepts[uri]
        return None

    def scheme_for(self, uri: str) -> tuple[Path, ConceptScheme] | None:
        for path, t in self.taxonomies.items():
            if uri in t.schemes:
                return path, t.schemes[uri]
        return None

    # ── cross-file queries ────────────────────────────────────────────────────

    def all_schemes(self) -> list[tuple[Path, ConceptScheme]]:
        return [
            (path, scheme) for path, t in self.taxonomies.items() for scheme in t.schemes.values()
        ]

    def scheme_count(self) -> int:
        return sum(len(t.schemes) for t in self.taxonomies.values())

    def multiple_schemes(self) -> bool:
        """True when more than one ConceptScheme is open — drives mapping UI."""
        return self.scheme_count() > 1

    def concept_scheme_uri(self, concept_uri: str) -> str | None:
        """Return the ConceptScheme URI for *concept_uri*, searching all files."""
        from .store import _concept_scheme_uri

        for t in self.taxonomies.values():
            if concept_uri in t.concepts:
                return _concept_scheme_uri(t, concept_uri)
        return None

    def is_known_uri(self, uri: str) -> bool:
        return self.uri_to_file(uri) is not None

    def unresolved_refs(self) -> set[str]:
        """All URIs referenced in hierarchy/mapping props but not loaded."""
        known: set[str] = set()
        referenced: set[str] = set()
        for t in self.taxonomies.values():
            known.update(t.concepts)
            known.update(t.schemes)
            for c in t.concepts.values():
                referenced.update(c.broader)
                referenced.update(c.narrower)
                referenced.update(c.related)
                referenced.update(c.broad_match)
                referenced.update(c.narrow_match)
                referenced.update(c.related_match)
                referenced.update(c.exact_match)
                referenced.update(c.close_match)
        return referenced - known
