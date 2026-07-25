"""Unit tests for the semanticlint inline-fix logic (``plugins.semanticlint.fixes``).

Pure: each fixer maps a plain issue dict + a Taxonomy to a Fix descriptor and to the
command object(s) that apply it. No Textual, no disk.
"""

from __future__ import annotations

from pathlib import Path

from ster.core.commands.cross import RenameEntity
from ster.core.commands.skos import SkosMoveConcept, SkosRemoveLabel, SkosSetLabel
from ster.model import Concept, Label, LabelType, Taxonomy
from ster.plugins.semanticlint import fixes

PATH = Path("/tmp/onto.ttl")


def _issue(check_id: str, subject: str = "http://ex.org/C1", severity: str = "error") -> dict:
    return {"severity": severity, "check_id": check_id, "subject": subject, "message": "m"}


# ── blocking_errors ─────────────────────────────────────────────────────────────


def test_blocking_errors_keeps_only_error_severity():
    issues = [
        _issue("RDF003"),
        _issue("QUA001", severity="warning"),
        _issue("QUA002", severity="info"),
    ]
    kept = fixes.blocking_errors(issues)
    assert [i["check_id"] for i in kept] == ["RDF003"]


def test_blocking_errors_empty_when_no_errors():
    assert fixes.blocking_errors([_issue("X", severity="warning")]) == []


def test_blocking_errors_preserves_order():
    issues = [_issue("A"), _issue("B"), _issue("C")]
    assert [i["check_id"] for i in fixes.blocking_errors(issues)] == ["A", "B", "C"]


# ── SKO003: redundant label (auto) ──────────────────────────────────────────────


def _concept_with_labels(*labels: Label) -> Taxonomy:
    tax = Taxonomy()
    tax.concepts["http://ex.org/C1"] = Concept(uri="http://ex.org/C1", labels=list(labels))
    return tax


def test_sko003_is_auto_when_altlabel_duplicates_preflabel():
    tax = _concept_with_labels(
        Label("en", "Dog", LabelType.PREF), Label("en", "Dog", LabelType.ALT)
    )
    fix = fixes.fix_for(_issue("SKO003"), tax)
    assert fix.kind == "auto"
    assert "Dog" in fix.suggestion


def test_sko003_commands_remove_the_duplicate_altlabel():
    tax = _concept_with_labels(
        Label("en", "Dog", LabelType.PREF), Label("en", "Dog", LabelType.ALT)
    )
    cmds = fixes.commands_for(_issue("SKO003"), tax, PATH)
    assert cmds == [SkosRemoveLabel(PATH, "http://ex.org/C1", "en", "Dog", kind="alt")]


def test_sko003_falls_back_to_suggestion_when_nothing_removable():
    tax = _concept_with_labels(Label("en", "Dog", LabelType.PREF))  # no overlap
    fix = fixes.fix_for(_issue("SKO003"), tax)
    assert fix.kind == "suggest"
    assert fixes.commands_for(_issue("SKO003"), tax, PATH) == []


# ── SKO001: duplicate prefLabel per language (pick) ─────────────────────────────


def test_sko001_is_pick_with_the_competing_preflabels_as_options():
    tax = _concept_with_labels(
        Label("en", "Dog", LabelType.PREF), Label("en", "Hound", LabelType.PREF)
    )
    fix = fixes.fix_for(_issue("SKO001"), tax)
    assert fix.kind == "pick"
    assert {v for _, v in fix.options} == {"Dog", "Hound"}


def test_sko001_keeps_chosen_pref_and_demotes_the_rest_to_alt():
    tax = _concept_with_labels(
        Label("en", "Dog", LabelType.PREF), Label("en", "Hound", LabelType.PREF)
    )
    cmds = fixes.commands_for(_issue("SKO001"), tax, PATH, choice="Dog")
    assert SkosSetLabel(PATH, "http://ex.org/C1", "en", "Dog", kind="pref") in cmds
    assert SkosSetLabel(PATH, "http://ex.org/C1", "en", "Hound", kind="alt") in cmds


def test_sko001_no_commands_without_a_choice():
    tax = _concept_with_labels(
        Label("en", "Dog", LabelType.PREF), Label("en", "Hound", LabelType.PREF)
    )
    assert fixes.commands_for(_issue("SKO001"), tax, PATH, choice="") == []


# ── SKO010: broader cycle (pick) ────────────────────────────────────────────────


def test_sko010_is_pick_over_the_subject_and_its_parents():
    tax = Taxonomy()
    tax.concepts["http://ex.org/C1"] = Concept(uri="http://ex.org/C1", broader=["http://ex.org/C2"])
    fix = fixes.fix_for(_issue("SKO010"), tax)
    assert fix.kind == "pick"
    assert {v for _, v in fix.options} == {"http://ex.org/C1", "http://ex.org/C2"}


def test_sko010_moves_the_chosen_concept_to_the_top():
    tax = Taxonomy()
    tax.concepts["http://ex.org/C1"] = Concept(uri="http://ex.org/C1", broader=["http://ex.org/C2"])
    cmds = fixes.commands_for(_issue("SKO010"), tax, PATH, choice="http://ex.org/C2")
    assert cmds == [SkosMoveConcept(PATH, "http://ex.org/C2", None)]


# ── RDF003: malformed URI (edit) ────────────────────────────────────────────────


def test_rdf003_is_edit_with_a_sanitized_prefill():
    bad = "http://ex.org/a#b#c"
    fix = fixes.fix_for(_issue("RDF003", subject=bad), Taxonomy())
    assert fix.kind == "edit"
    assert fix.prefill.count("#") == 1  # collapsed the extra fragment


def test_rdf003_prefill_percent_encodes_a_space():
    fix = fixes.fix_for(_issue("RDF003", subject="http://ex.org/my concept"), Taxonomy())
    assert " " not in fix.prefill
    assert "%20" in fix.prefill


def test_rdf003_renames_to_the_corrected_uri():
    bad = "http://ex.org/my concept"
    cmds = fixes.commands_for(
        _issue("RDF003", subject=bad), Taxonomy(), PATH, choice="http://ex.org/concept"
    )
    assert cmds == [RenameEntity(PATH, bad, "http://ex.org/concept")]


def test_rdf003_no_rename_when_unchanged_or_blank():
    bad = "http://ex.org/x y"
    assert fixes.commands_for(_issue("RDF003", subject=bad), Taxonomy(), PATH, choice=bad) == []
    assert fixes.commands_for(_issue("RDF003", subject=bad), Taxonomy(), PATH, choice="  ") == []


# ── suggestion-only errors (no safe in-place command) ───────────────────────────


def test_rdf007_is_a_suggestion_with_no_commands():
    fix = fixes.fix_for(_issue("RDF007"), Taxonomy())
    assert fix.kind == "suggest"
    assert not fix.actionable
    assert fixes.commands_for(_issue("RDF007"), Taxonomy(), PATH) == []


def test_sko020_is_a_suggestion():
    fix = fixes.fix_for(_issue("SKO020"), Taxonomy())
    assert fix.kind == "suggest"
    assert "inScheme" in fix.suggestion


def test_unknown_check_is_a_generic_suggestion():
    fix = fixes.fix_for(_issue("ZZZ999"), Taxonomy())
    assert fix.kind == "suggest"
    assert fixes.commands_for(_issue("ZZZ999"), Taxonomy(), PATH) == []


def test_actionable_reflects_fix_kind():
    assert fixes.Fix("auto", "s").actionable
    assert fixes.Fix("edit", "s").actionable
    assert fixes.Fix("pick", "s").actionable
    assert not fixes.Fix("suggest", "s").actionable
