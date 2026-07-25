"""Inline fixes for semanticlint ERROR violations — the fix-it worklist behind the
scan-on-open modal.

Pure logic, no Textual: given a plain issue dict (from
:func:`runner.lint_overview`) and the live :class:`~ster.model.Taxonomy`, a *fixer*
returns a :class:`Fix` describing how the user resolves it *in place* — one of four
kinds:

* ``auto``   — one keypress, no input (the fix is unambiguous);
* ``edit``   — an editable field pre-filled with a corrected value;
* ``pick``   — choose one of several options;
* ``suggest``— no safe in-place command exists; show concrete guidance only.

A fixer also builds the ``ster.core.commands`` object(s) that apply the fix, so the
mapping from a violation to a mutation lives here in the plugin, not in the app. The
app just runs whatever commands ``commands_for`` returns through ``TaxonomyService``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ster.model import Concept, Taxonomy

ERROR = "error"

# Characters a URI may never contain (mirrors semanticlint RDF003's illegal set).
_ILLEGAL_URI_CHARS = re.compile(r'[<>"{}|\\^`\x00-\x1f\x7f]')


def blocking_errors(issues: list[dict]) -> list[dict]:
    """The ERROR-severity subset of *issues*, in the order given (the modal only ever
    surfaces blocking errors on open)."""
    return [i for i in issues if i.get("severity") == ERROR]


@dataclass(frozen=True)
class Fix:
    """How one violation is resolved in place.

    *options* are ``(label, value)`` pairs for ``pick``; *prefill* seeds the ``edit``
    field. ``subject`` is the entity the fix acts on.
    """

    kind: str  # "auto" | "edit" | "pick" | "suggest"
    suggestion: str
    subject: str = ""
    prefill: str = ""
    options: tuple[tuple[str, str], ...] = ()

    @property
    def actionable(self) -> bool:
        """True when the fix can be applied from the modal (not a plain suggestion)."""
        return self.kind in ("auto", "edit", "pick")


def _sanitize_uri(uri: str) -> str:
    """A best-effort valid-URI suggestion for a malformed one: percent-encode spaces,
    collapse any second ``#`` into the fragment, and drop illegal characters."""
    if uri.count("#") > 1:
        head, _, tail = uri.partition("#")
        uri = f"{head}#{tail.replace('#', '%23')}"
    uri = uri.replace(" ", "%20")
    return _ILLEGAL_URI_CHARS.sub("", uri)


def _duplicate_label(concept: Concept) -> tuple[str, str] | None:
    """A ``(lang, value)`` that is both the ``prefLabel`` and a non-pref label on
    *concept* (SKO003), or ``None``. The non-pref copy is the redundant one to drop."""
    from ster.model import LabelType

    pref = {(lbl.lang, lbl.value) for lbl in concept.labels if lbl.type == LabelType.PREF}
    for lbl in concept.labels:
        if lbl.type != LabelType.PREF and (lbl.lang, lbl.value) in pref:
            return (lbl.lang, lbl.value)
    return None


def _duplicate_prefs(concept: Concept) -> tuple[str, tuple[str, ...]] | None:
    """The ``(lang, values)`` where *concept* has more than one ``prefLabel`` in one
    language (SKO001), or ``None`` — the values compete to be the single prefLabel."""
    from ster.model import LabelType

    by_lang: dict[str, list[str]] = {}
    for lbl in concept.labels:
        if lbl.type == LabelType.PREF:
            by_lang.setdefault(lbl.lang, []).append(lbl.value)
    for lang, values in by_lang.items():
        if len(values) > 1:
            return (lang, tuple(values))
    return None


# ── fixers ──────────────────────────────────────────────────────────────────────
# Each returns a Fix (describe) and, given the user's choice, the command list to run.


class _Fixer:
    """Base fixer: an unfixable violation (concrete guidance only)."""

    guidance = "Review and correct this issue manually."

    def describe(self, issue: dict, tax: Taxonomy) -> Fix:
        return Fix("suggest", self.guidance, subject=issue.get("subject", ""))

    def commands(self, issue: dict, tax: Taxonomy, path: Path, choice: str) -> list:
        return []


class _Sko003Fixer(_Fixer):
    """A label that is both prefLabel and altLabel/hiddenLabel — drop the redundant copy."""

    def describe(self, issue: dict, tax: Taxonomy) -> Fix:
        subject = issue.get("subject", "")
        concept = tax.concepts.get(subject)
        dup = _duplicate_label(concept) if concept else None
        if dup is None:  # nothing removable (e.g. a hidden-only overlap) — guide instead
            return Fix("suggest", "Make prefLabel, altLabel and hiddenLabel distinct.", subject)
        lang, value = dup
        tag = f"@{lang}" if lang else ""
        return Fix(
            "auto", f"Remove the duplicate altLabel “{value}{tag}” (kept as prefLabel).", subject
        )

    def commands(self, issue: dict, tax: Taxonomy, path: Path, choice: str) -> list:
        from ster.core.commands.skos import SkosRemoveLabel

        subject = issue.get("subject", "")
        concept = tax.concepts.get(subject)
        dup = _duplicate_label(concept) if concept else None
        if dup is None:
            return []
        lang, value = dup
        return [SkosRemoveLabel(path, subject, lang, value, kind="alt")]


class _Sko001Fixer(_Fixer):
    """More than one prefLabel in a language — pick the one to keep; demote the rest."""

    def describe(self, issue: dict, tax: Taxonomy) -> Fix:
        subject = issue.get("subject", "")
        concept = tax.concepts.get(subject)
        dup = _duplicate_prefs(concept) if concept else None
        if dup is None:
            return Fix(
                "suggest", "Keep one prefLabel per language; demote the rest to altLabel.", subject
            )
        lang, values = dup
        options = tuple((v, v) for v in values)
        return Fix(
            "pick",
            f"Choose the prefLabel to keep for “{lang}”; the others become altLabels.",
            subject,
            options=options,
        )

    def commands(self, issue: dict, tax: Taxonomy, path: Path, choice: str) -> list:
        from ster.core.commands.skos import SkosSetLabel

        subject = issue.get("subject", "")
        concept = tax.concepts.get(subject)
        dup = _duplicate_prefs(concept) if concept else None
        if dup is None or not choice:
            return []
        lang, values = dup
        # Set the chosen value as the sole prefLabel (replaces the language's prefs),
        # then re-add the losers as altLabels so no label is lost.
        cmds: list = [SkosSetLabel(path, subject, lang, choice, kind="pref")]
        cmds += [SkosSetLabel(path, subject, lang, v, kind="alt") for v in values if v != choice]
        return cmds


class _Sko010Fixer(_Fixer):
    """A cycle in the broader hierarchy — pick a concept in the cycle to detach to the
    scheme top, breaking it."""

    def describe(self, issue: dict, tax: Taxonomy) -> Fix:
        subject = issue.get("subject", "")
        concept = tax.concepts.get(subject)
        # The cheap, safe candidates: the subject and its direct parents. Detaching any
        # one of them from its parents breaks a cycle running through the subject.
        candidates = [subject, *(concept.broader if concept else [])]
        options = tuple((_local(c), c) for c in candidates if c)
        if not options:
            return Fix("suggest", "Remove one skos:broader link to break the cycle.", subject)
        return Fix(
            "pick",
            "Choose a concept to move to the top (drops its parents) and break the cycle.",
            subject,
            options=options,
        )

    def commands(self, issue: dict, tax: Taxonomy, path: Path, choice: str) -> list:
        from ster.core.commands.skos import SkosMoveConcept

        if not choice:
            return []
        return [SkosMoveConcept(path, choice, None)]  # move to top → removes its broaders


class _Rdf003Fixer(_Fixer):
    """A malformed URI — offer a sanitized suggestion to rename the entity to."""

    def describe(self, issue: dict, tax: Taxonomy) -> Fix:
        subject = issue.get("subject", "")
        return Fix(
            "edit",
            "Rename to a valid URI (no spaces, a single “#”, valid %-encoding).",
            subject,
            prefill=_sanitize_uri(subject),
        )

    def commands(self, issue: dict, tax: Taxonomy, path: Path, choice: str) -> list:
        from ster.core.commands.cross import RenameEntity

        subject = issue.get("subject", "")
        new_uri = choice.strip()
        if not new_uri or new_uri == subject:
            return []
        return [RenameEntity(path, subject, new_uri)]


class _Rdf007Fixer(_Fixer):
    guidance = (
        "Give each entity a distinct URI, or keep only compatible facets "
        "(concept+class or class+individual)."
    )


class _Sko020Fixer(_Fixer):
    guidance = "Add skos:inScheme for the scheme — ster writes it automatically when you save."


def _local(uri: str) -> str:
    return uri.rsplit("/", 1)[-1].rsplit("#", 1)[-1] if uri else uri


_FIXERS: dict[str, _Fixer] = {
    "SKO003": _Sko003Fixer(),
    "SKO001": _Sko001Fixer(),
    "SKO010": _Sko010Fixer(),
    "RDF003": _Rdf003Fixer(),
    "RDF007": _Rdf007Fixer(),
    "SKO020": _Sko020Fixer(),
}

_DEFAULT = _Fixer()


def fix_for(issue: dict, tax: Taxonomy) -> Fix:
    """The :class:`Fix` describing how to resolve *issue* in place."""
    return _FIXERS.get(issue.get("check_id", ""), _DEFAULT).describe(issue, tax)


def commands_for(issue: dict, tax: Taxonomy, path: Path, choice: str = "") -> list:
    """The command object(s) that apply *issue*'s fix given the user's *choice* (the
    edit value or the picked option; ignored by ``auto`` fixers). Empty when there is
    nothing to apply."""
    return _FIXERS.get(issue.get("check_id", ""), _DEFAULT).commands(issue, tax, path, choice)
