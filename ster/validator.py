"""SKOS consistency validation for a TaxonomyWorkspace.

All checks are non-destructive reads.  Results are returned as a list of
ValidationIssue objects that the UI can use for highlighting and reporting.
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from .workspace import TaxonomyWorkspace


@dataclass
class ValidationIssue:
    severity: Literal["error", "warning"]
    code: str          # e.g. "broken_ref", "cycle", "dup_pref_label", …
    uri: str           # the concept/scheme URI where the issue was found
    message: str
    related_uri: str | None = None   # the other URI involved (if any)


# ──────────────────────────── validator ──────────────────────────────────────

class SkosValidator:
    """Run a suite of SKOS consistency checks against a workspace."""

    def validate(self, workspace: TaxonomyWorkspace) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        issues.extend(self._check_broken_refs(workspace))
        issues.extend(self._check_broken_mappings(workspace))
        issues.extend(self._check_missing_in_scheme(workspace))
        issues.extend(self._check_dup_pref_label(workspace))
        issues.extend(self._check_cycles(workspace))
        return issues

    # ── individual checks ─────────────────────────────────────────────────────

    def _check_broken_refs(self, ws: TaxonomyWorkspace) -> list[ValidationIssue]:
        """broader/narrower/related pointing to a URI not in any loaded file."""
        issues = []
        for path, t in ws.taxonomies.items():
            fname = path.name
            for uri, c in t.concepts.items():
                for ref in c.broader + c.narrower + c.related:
                    if not ws.is_known_uri(ref):
                        issues.append(ValidationIssue(
                            severity="error", code="broken_ref",
                            uri=uri, related_uri=ref,
                            message=f"[{fname}] {uri!r} references unloaded URI {ref!r}",
                        ))
        return issues

    def _check_broken_mappings(self, ws: TaxonomyWorkspace) -> list[ValidationIssue]:
        """Mapping properties pointing to a URI not in any loaded file."""
        issues = []
        _mapping_attrs = (
            "broad_match", "narrow_match", "related_match",
            "exact_match", "close_match",
        )
        for path, t in ws.taxonomies.items():
            fname = path.name
            for uri, c in t.concepts.items():
                for attr in _mapping_attrs:
                    for ref in getattr(c, attr):
                        if not ws.is_known_uri(ref):
                            issues.append(ValidationIssue(
                                severity="warning", code="broken_mapping",
                                uri=uri, related_uri=ref,
                                message=(
                                    f"[{fname}] mapping from {uri!r} to "
                                    f"unloaded concept {ref!r}"
                                ),
                            ))
        return issues

    def _check_missing_in_scheme(self, ws: TaxonomyWorkspace) -> list[ValidationIssue]:
        """Concepts not reachable from any ConceptScheme (orphans)."""
        issues = []
        for path, t in ws.taxonomies.items():
            fname = path.name
            for uri in t.concepts:
                if ws.concept_scheme_uri(uri) is None:
                    issues.append(ValidationIssue(
                        severity="warning", code="missing_in_scheme",
                        uri=uri,
                        message=f"[{fname}] {uri!r} is not reachable from any ConceptScheme",
                    ))
        return issues

    def _check_dup_pref_label(self, ws: TaxonomyWorkspace) -> list[ValidationIssue]:
        """Two concepts with the same prefLabel (same lang) in the same scheme."""
        issues = []
        for path, t in ws.taxonomies.items():
            fname = path.name
            # scheme_uri → (lang::value → first_concept_uri)
            seen: dict[str, dict[str, str]] = defaultdict(dict)
            for uri, c in t.concepts.items():
                s_uri = ws.concept_scheme_uri(uri) or "__no_scheme__"
                for lbl in c.labels:
                    key = f"{lbl.lang}::{lbl.value}"
                    if key in seen[s_uri]:
                        issues.append(ValidationIssue(
                            severity="error", code="dup_pref_label",
                            uri=uri, related_uri=seen[s_uri][key],
                            message=(
                                f"[{fname}] Duplicate prefLabel "
                                f"{lbl.value!r}@{lbl.lang}"
                            ),
                        ))
                    else:
                        seen[s_uri][key] = uri
        return issues

    def _check_cycles(self, ws: TaxonomyWorkspace) -> list[ValidationIssue]:
        """Cycles in the broader/narrower hierarchy."""
        issues: list[ValidationIssue] = []
        visited: set[str] = set()
        reported: set[str] = set()

        def dfs(uri: str, path_set: frozenset[str]) -> None:
            if uri in path_set:
                if uri not in reported:
                    reported.add(uri)
                    issues.append(ValidationIssue(
                        severity="error", code="cycle",
                        uri=uri,
                        message=f"Broader cycle detected involving {uri!r}",
                    ))
                return
            if uri in visited:
                return
            visited.add(uri)
            result = ws.concept_for(uri)
            if result is None:
                return
            _, concept = result
            new_path = path_set | {uri}
            for broader_uri in concept.broader:
                dfs(broader_uri, new_path)

        for t in ws.taxonomies.values():
            for uri in t.concepts:
                dfs(uri, frozenset())

        return issues
