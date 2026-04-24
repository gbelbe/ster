"""Pure taxonomy-diff logic extracted from git_log — no curses, no subprocess."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field

from .handles import assign_handles
from .model import Concept, LabelType, OWLIndividual, RDFClass, Taxonomy

# ──────────────────────────── data model ─────────────────────────────────────


@dataclass
class LogEntry:
    full_hash: str  # %H  — full SHA-1
    short_hash: str  # %h  — abbreviated
    subject: str  # %s  — first line of commit message
    author: str  # %an — author name
    date: str  # %ad — absolute date (YYYY-MM-DD)
    refs: str  # %D  — branch/tag decorations


@dataclass
class FieldDiff:
    """One field-level change within a concept."""

    label: str  # e.g. "prefLabel[en]", "altLabel[fr]", "definition[en]"
    before: str  # value before the commit  ("" if added)
    after: str  # value after the commit   ("" if removed)

    @property
    def status(self) -> str:
        if not self.before:
            return "added"
        if not self.after:
            return "removed"
        return "changed"


@dataclass
class ConceptChange:
    uri: str
    status: str  # "added" | "removed" | "changed" | "unchanged"
    field_diffs: list[FieldDiff] = field(default_factory=list)


# ──────────────────────────── pure parse / diff functions ────────────────────


def _parse_log(raw: str) -> list[LogEntry]:
    """Parse ``git log --pretty=tformat:\x1f%H\x1f%h\x1f%s\x1f%an\x1f%ad\x1f%D`` output."""
    SEP = "\x1f"
    entries: list[LogEntry] = []
    for line in raw.splitlines():
        if SEP not in line:
            continue
        parts = line.split(SEP)
        # Line starts with SEP → parts[0] is empty, then 6 fields
        if len(parts) < 7:
            continue

        # Strip control/escape characters from human-readable fields so they
        # don't corrupt curses rendering (e.g. raw ^[[A from arrow-key mishaps)
        def _clean(s: str) -> str:
            return "".join(c for c in s if c >= " " or c == "\t")

        entries.append(
            LogEntry(
                full_hash=parts[1].strip(),
                short_hash=parts[2].strip(),
                subject=_clean(parts[3]),
                author=_clean(parts[4]),
                date=parts[5].strip(),
                refs=parts[6].strip(),
            )
        )
    return entries


def _concept_field_diffs(before: Concept, after: Concept) -> list[FieldDiff]:
    diffs: list[FieldDiff] = []

    # prefLabel
    b_pref = {lbl.lang: lbl.value for lbl in before.labels if lbl.type == LabelType.PREF}
    a_pref = {lbl.lang: lbl.value for lbl in after.labels if lbl.type == LabelType.PREF}
    for lang in sorted(set(b_pref) | set(a_pref)):
        b, a = b_pref.get(lang, ""), a_pref.get(lang, "")
        if b != a:
            diffs.append(FieldDiff(f"prefLabel[{lang}]", b, a))

    # altLabel  (multi-valued per lang)
    b_alt: dict[str, set[str]] = {}
    a_alt: dict[str, set[str]] = {}
    for lbl in before.labels:
        if lbl.type == LabelType.ALT:
            b_alt.setdefault(lbl.lang, set()).add(lbl.value)
    for lbl in after.labels:
        if lbl.type == LabelType.ALT:
            a_alt.setdefault(lbl.lang, set()).add(lbl.value)
    for lang in sorted(set(b_alt) | set(a_alt)):
        for v in sorted(b_alt.get(lang, set()) - a_alt.get(lang, set())):
            diffs.append(FieldDiff(f"altLabel[{lang}]", v, ""))
        for v in sorted(a_alt.get(lang, set()) - b_alt.get(lang, set())):
            diffs.append(FieldDiff(f"altLabel[{lang}]", "", v))

    # definition
    b_def = {d.lang: d.value for d in before.definitions}
    a_def = {d.lang: d.value for d in after.definitions}
    for lang in sorted(set(b_def) | set(a_def)):
        b, a = b_def.get(lang, ""), a_def.get(lang, "")
        if b != a:
            diffs.append(FieldDiff(f"definition[{lang}]", b, a))

    # scopeNote
    b_sn = {d.lang: d.value for d in before.scope_notes}
    a_sn = {d.lang: d.value for d in after.scope_notes}
    for lang in sorted(set(b_sn) | set(a_sn)):
        b, a = b_sn.get(lang, ""), a_sn.get(lang, "")
        if b != a:
            diffs.append(FieldDiff(f"scopeNote[{lang}]", b, a))

    return diffs


def _owl_class_field_diffs(before: RDFClass, after: RDFClass) -> list[FieldDiff]:
    diffs: list[FieldDiff] = []
    b_lbl = {lbl.lang: lbl.value for lbl in before.labels}
    a_lbl = {lbl.lang: lbl.value for lbl in after.labels}
    for lang in sorted(set(b_lbl) | set(a_lbl)):
        b, a = b_lbl.get(lang, ""), a_lbl.get(lang, "")
        if b != a:
            diffs.append(FieldDiff(f"label[{lang}]", b, a))
    b_cmt = {c.lang: c.value for c in before.comments}
    a_cmt = {c.lang: c.value for c in after.comments}
    for lang in sorted(set(b_cmt) | set(a_cmt)):
        b, a = b_cmt.get(lang, ""), a_cmt.get(lang, "")
        if b != a:
            diffs.append(FieldDiff(f"comment[{lang}]", b, a))
    return diffs


def _owl_ind_field_diffs(before: OWLIndividual, after: OWLIndividual) -> list[FieldDiff]:
    diffs: list[FieldDiff] = []
    b_lbl = {lbl.lang: lbl.value for lbl in before.labels}
    a_lbl = {lbl.lang: lbl.value for lbl in after.labels}
    for lang in sorted(set(b_lbl) | set(a_lbl)):
        b, a = b_lbl.get(lang, ""), a_lbl.get(lang, "")
        if b != a:
            diffs.append(FieldDiff(f"label[{lang}]", b, a))
    b_cmt = {c.lang: c.value for c in before.comments}
    a_cmt = {c.lang: c.value for c in after.comments}
    for lang in sorted(set(b_cmt) | set(a_cmt)):
        b, a = b_cmt.get(lang, ""), a_cmt.get(lang, "")
        if b != a:
            diffs.append(FieldDiff(f"comment[{lang}]", b, a))
    return diffs


def compute_taxonomy_diff(before: Taxonomy, after: Taxonomy) -> dict[str, ConceptChange]:
    """Compare two taxonomies; return a mapping from URI to ConceptChange."""
    result: dict[str, ConceptChange] = {}

    # SKOS concepts
    for uri in set(before.concepts) | set(after.concepts):
        bc = before.concepts.get(uri)
        ac = after.concepts.get(uri)
        if bc is None:
            result[uri] = ConceptChange(uri, "added")
        elif ac is None:
            result[uri] = ConceptChange(uri, "removed")
        else:
            fd = _concept_field_diffs(bc, ac)
            result[uri] = ConceptChange(uri, "changed" if fd else "unchanged", fd)

    # OWL classes
    for uri in set(before.owl_classes) | set(after.owl_classes):
        bc2 = before.owl_classes.get(uri)
        ac2 = after.owl_classes.get(uri)
        if bc2 is None:
            result[uri] = ConceptChange(uri, "added")
        elif ac2 is None:
            result[uri] = ConceptChange(uri, "removed")
        else:
            fd2 = _owl_class_field_diffs(bc2, ac2)
            result[uri] = ConceptChange(uri, "changed" if fd2 else "unchanged", fd2)

    # OWL individuals
    for uri in set(before.owl_individuals) | set(after.owl_individuals):
        bi = before.owl_individuals.get(uri)
        ai = after.owl_individuals.get(uri)
        if bi is None:
            result[uri] = ConceptChange(uri, "added")
        elif ai is None:
            result[uri] = ConceptChange(uri, "removed")
        else:
            fd3 = _owl_ind_field_diffs(bi, ai)
            result[uri] = ConceptChange(uri, "changed" if fd3 else "unchanged", fd3)

    return result


def build_diff_taxonomy(before: Taxonomy, after: Taxonomy) -> Taxonomy:
    """Create a merged taxonomy for display: after + ghost entities from before.

    Deleted concepts/classes/individuals are re-inserted so they still appear
    in the tree (coloured red by the renderer).
    """
    merged = deepcopy(after)

    # Ghost SKOS concepts
    for uri in sorted(set(before.concepts) - set(after.concepts)):
        ghost = deepcopy(before.concepts[uri])
        merged.concepts[uri] = ghost
        attached = False
        for p_uri in ghost.broader:
            if p_uri in merged.concepts:
                p = merged.concepts[p_uri]
                if uri not in p.narrower:
                    p.narrower.append(uri)
                attached = True
                break
        if not attached:
            scheme = merged.primary_scheme()
            if scheme and uri not in scheme.top_concepts:
                scheme.top_concepts.append(uri)

    # Ghost OWL classes
    for uri in sorted(set(before.owl_classes) - set(after.owl_classes)):
        merged.owl_classes[uri] = deepcopy(before.owl_classes[uri])

    # Ghost OWL individuals
    for uri in sorted(set(before.owl_individuals) - set(after.owl_individuals)):
        merged.owl_individuals[uri] = deepcopy(before.owl_individuals[uri])

    assign_handles(merged)
    return merged


def _subtree_has_change(
    taxonomy: Taxonomy,
    uri: str,
    diff: dict[str, ConceptChange],
    visited: set[str],
) -> bool:
    if uri in visited:
        return False
    visited.add(uri)
    ch = diff.get(uri)
    if ch and ch.status != "unchanged":
        return True
    concept = taxonomy.concepts.get(uri)
    if not concept:
        return False
    return any(_subtree_has_change(taxonomy, c, diff, visited) for c in concept.narrower)


def compute_auto_fold(taxonomy: Taxonomy, diff: dict[str, ConceptChange]) -> set[str]:
    """Return URIs whose entire subtree is unchanged — fold them by default."""
    folded: set[str] = set()
    for uri, concept in taxonomy.concepts.items():
        if concept.narrower and not _subtree_has_change(taxonomy, uri, diff, set()):
            folded.add(uri)
    for scheme in taxonomy.schemes.values():
        if scheme.top_concepts and not any(
            _subtree_has_change(taxonomy, tc, diff, set()) for tc in scheme.top_concepts
        ):
            folded.add(scheme.uri)
    # Fold unchanged OWL classes that have subclasses
    children_map: dict[str, list[str]] = {uri: [] for uri in taxonomy.owl_classes}
    for uri, cls in taxonomy.owl_classes.items():
        for parent in cls.sub_class_of:
            if parent in children_map:
                children_map[parent].append(uri)
    for uri in taxonomy.owl_classes:
        if children_map.get(uri):
            ch = diff.get(uri)
            subtree_changed = ch and ch.status != "unchanged"
            if not subtree_changed:
                subtree_changed = any(
                    diff.get(c) and diff[c].status != "unchanged" for c in children_map.get(uri, [])
                )
            if not subtree_changed:
                folded.add(uri)
    return folded
