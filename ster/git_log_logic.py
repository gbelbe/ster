"""Pure taxonomy-diff logic extracted from git_log — no curses, no subprocess."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field

from .handles import assign_handles
from .model import Concept, LabelType, OWLIndividual, OWLProperty, RDFClass, Taxonomy

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


def _set_diff(label: str, before: list[str], after: list[str]) -> list[FieldDiff]:
    """Return FieldDiffs for items added/removed in a list-valued field."""
    b, a = set(before), set(after)
    diffs: list[FieldDiff] = []
    for v in sorted(b - a):
        diffs.append(FieldDiff(label, v, ""))
    for v in sorted(a - b):
        diffs.append(FieldDiff(label, "", v))
    return diffs


def _lang_diffs(
    label_fmt: str, before_map: dict[str, str], after_map: dict[str, str]
) -> list[FieldDiff]:
    """Return FieldDiffs for per-language scalar fields (label, definition…)."""
    diffs: list[FieldDiff] = []
    for lang in sorted(set(before_map) | set(after_map)):
        b, a = before_map.get(lang, ""), after_map.get(lang, "")
        if b != a:
            diffs.append(FieldDiff(label_fmt.format(lang=lang), b, a))
    return diffs


def _concept_field_diffs(before: Concept, after: Concept) -> list[FieldDiff]:
    diffs: list[FieldDiff] = []

    # prefLabel (scalar per lang)
    diffs += _lang_diffs(
        "prefLabel[{lang}]",
        {lbl.lang: lbl.value for lbl in before.labels if lbl.type == LabelType.PREF},
        {lbl.lang: lbl.value for lbl in after.labels if lbl.type == LabelType.PREF},
    )

    # altLabel (multi-valued per lang)
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

    # definition / scopeNote (scalar per lang)
    diffs += _lang_diffs(
        "definition[{lang}]",
        {d.lang: d.value for d in before.definitions},
        {d.lang: d.value for d in after.definitions},
    )
    diffs += _lang_diffs(
        "scopeNote[{lang}]",
        {d.lang: d.value for d in before.scope_notes},
        {d.lang: d.value for d in after.scope_notes},
    )

    # Structural relations
    diffs += _set_diff("broader", before.broader, after.broader)
    diffs += _set_diff("narrower", before.narrower, after.narrower)
    diffs += _set_diff("related", before.related, after.related)

    # SKOS mapping properties
    diffs += _set_diff("broadMatch", before.broad_match, after.broad_match)
    diffs += _set_diff("narrowMatch", before.narrow_match, after.narrow_match)
    diffs += _set_diff("exactMatch", before.exact_match, after.exact_match)
    diffs += _set_diff("closeMatch", before.close_match, after.close_match)
    diffs += _set_diff("relatedMatch", before.related_match, after.related_match)

    # schema.org annotations
    diffs += _set_diff("schema:image", before.schema_images, after.schema_images)
    diffs += _set_diff("schema:video", before.schema_videos, after.schema_videos)
    diffs += _set_diff("schema:url", before.schema_urls, after.schema_urls)

    return diffs


def _owl_class_field_diffs(before: RDFClass, after: RDFClass) -> list[FieldDiff]:
    diffs: list[FieldDiff] = []
    diffs += _lang_diffs(
        "label[{lang}]",
        {lbl.lang: lbl.value for lbl in before.labels},
        {lbl.lang: lbl.value for lbl in after.labels},
    )
    diffs += _lang_diffs(
        "comment[{lang}]",
        {c.lang: c.value for c in before.comments},
        {c.lang: c.value for c in after.comments},
    )
    diffs += _set_diff("subClassOf", before.sub_class_of, after.sub_class_of)
    diffs += _set_diff("equivalentClass", before.equivalent_class, after.equivalent_class)
    diffs += _set_diff("disjointWith", before.disjoint_with, after.disjoint_with)
    diffs += _set_diff("schema:image", before.schema_images, after.schema_images)
    diffs += _set_diff("schema:video", before.schema_videos, after.schema_videos)
    diffs += _set_diff("schema:url", before.schema_urls, after.schema_urls)
    return diffs


def _owl_ind_field_diffs(before: OWLIndividual, after: OWLIndividual) -> list[FieldDiff]:
    diffs: list[FieldDiff] = []
    diffs += _lang_diffs(
        "label[{lang}]",
        {lbl.lang: lbl.value for lbl in before.labels},
        {lbl.lang: lbl.value for lbl in after.labels},
    )
    diffs += _lang_diffs(
        "comment[{lang}]",
        {c.lang: c.value for c in before.comments},
        {c.lang: c.value for c in after.comments},
    )
    diffs += _set_diff("rdf:type", before.types, after.types)
    # property assertions: represent each as "prop → target"
    b_pv = [f"{p} → {t}" for p, t in before.property_values]
    a_pv = [f"{p} → {t}" for p, t in after.property_values]
    diffs += _set_diff("propertyValue", b_pv, a_pv)
    diffs += _set_diff("schema:image", before.schema_images, after.schema_images)
    diffs += _set_diff("schema:video", before.schema_videos, after.schema_videos)
    diffs += _set_diff("schema:url", before.schema_urls, after.schema_urls)
    return diffs


def _owl_prop_field_diffs(before: OWLProperty, after: OWLProperty) -> list[FieldDiff]:
    diffs: list[FieldDiff] = []
    diffs += _lang_diffs(
        "label[{lang}]",
        {lbl.lang: lbl.value for lbl in before.labels},
        {lbl.lang: lbl.value for lbl in after.labels},
    )
    diffs += _lang_diffs(
        "comment[{lang}]",
        {c.lang: c.value for c in before.comments},
        {c.lang: c.value for c in after.comments},
    )
    diffs += _set_diff("domain", before.domains, after.domains)
    diffs += _set_diff("range", before.ranges, after.ranges)
    diffs += _set_diff("subPropertyOf", before.sub_property_of, after.sub_property_of)
    diffs += _set_diff("inverseOf", before.inverse_of, after.inverse_of)
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

    # OWL properties
    for uri in set(before.owl_properties) | set(after.owl_properties):
        bp = before.owl_properties.get(uri)
        ap = after.owl_properties.get(uri)
        if bp is None:
            result[uri] = ConceptChange(uri, "added")
        elif ap is None:
            result[uri] = ConceptChange(uri, "removed")
        else:
            fd4 = _owl_prop_field_diffs(bp, ap)
            result[uri] = ConceptChange(uri, "changed" if fd4 else "unchanged", fd4)

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

    # Ghost OWL properties
    for uri in sorted(set(before.owl_properties) - set(after.owl_properties)):
        merged.owl_properties[uri] = deepcopy(before.owl_properties[uri])

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
