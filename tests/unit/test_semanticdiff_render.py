"""Unit tests for the terminal renderers — the layers of the drill-down."""

from __future__ import annotations

from semanticdiff.git_log import Commit
from semanticdiff.history import CommitChanges
from semanticdiff.render.text import render_commits, render_entity, render_summary
from semanticdiff.vocabulary import Change, ChangeKind, ChangeSet, EntityKind

RANGE = "v0.1..v0.2"
VEHICLE = "ex:Vehicle"
PRODUCT = "ex:Product"


def commit(subject: str = "add a class", sha: str = "1085c9c0", other_files: int = 0) -> Commit:
    return Commit(
        sha=sha,
        short_sha=sha[:7],
        author="Ada Lovelace",
        date="2026-09-04T10:00:00+02:00",
        subject=subject,
        other_files=other_files,
    )


def change(
    kind: ChangeKind = ChangeKind.ADDED,
    curie: str = VEHICLE,
    label: str | None = None,
    detail: tuple[str, ...] = (),
    previous_curie: str | None = None,
    entity: EntityKind = EntityKind.CLASS,
    of_class: str | None = None,
) -> Change:
    return Change(
        kind=kind,
        entity=entity,
        uri=f"http://example.org/{curie.split(':')[-1]}",
        curie=curie,
        label=label,
        label_lang="en" if label else None,
        previous_curie=previous_curie,
        detail=detail,
        of_class=of_class,
    )


def individuals(n: int, of_class: str, kind: ChangeKind = ChangeKind.ADDED, start: int = 0):
    """`n` individual changes of one class, as a bulk edit would produce."""
    return [
        change(kind, f"ex:n{i}", entity=EntityKind.INDIVIDUAL, of_class=of_class)
        for i in range(start, start + n)
    ]


def entry(*changes: Change, subject: str = "add a class", other_files: int = 0) -> CommitChanges:
    return CommitChanges(
        commit=commit(subject=subject, other_files=other_files),
        changes=ChangeSet(changes),
    )


# ── layer 0: the summary ──────────────────────────────────────────────────────


def test_summary_counts_by_change_kind() -> None:
    history = [
        entry(change(ChangeKind.ADDED, "ex:A"), change(ChangeKind.ADDED, "ex:B")),
        entry(change(ChangeKind.MODIFIED, "ex:C"), change(ChangeKind.REMOVED, "ex:D")),
    ]

    out = render_summary(history, RANGE)

    assert "2 added" in out
    assert "1 modified" in out
    assert "1 removed" in out


def test_summary_omits_kinds_with_zero_count() -> None:
    out = render_summary([entry(change(ChangeKind.ADDED, "ex:A"))], RANGE)

    assert "removed" not in out
    assert "renamed" not in out


def test_summary_names_the_revision_range_and_commit_count() -> None:
    history = [entry(change(), subject="one"), entry(change(curie="ex:B"), subject="two")]

    out = render_summary(history, RANGE)

    assert RANGE in out
    assert "2 commits" in out


def test_summary_of_an_empty_history_says_so() -> None:
    assert "no commits" in render_summary([], RANGE).lower()


# ── layer 1: the per-commit view ──────────────────────────────────────────────


def test_commit_view_names_added_entity() -> None:
    out = render_commits([entry(change(ChangeKind.ADDED, VEHICLE))])

    assert VEHICLE in out
    assert "1085c9c" in out
    assert "Ada Lovelace" in out


def test_commit_view_prefers_label_over_uri() -> None:
    out = render_commits([entry(change(ChangeKind.ADDED, VEHICLE, label="Vehicle"))])

    assert "Vehicle" in out
    assert VEHICLE in out


def test_commit_view_falls_back_to_curie_when_unlabelled() -> None:
    assert VEHICLE in render_commits([entry(change(ChangeKind.ADDED, VEHICLE, label=None))])


def test_commit_view_shows_change_detail() -> None:
    out = render_commits([entry(change(ChangeKind.MODIFIED, PRODUCT, detail=("+2 properties",)))])

    assert "+2 properties" in out


def test_commit_view_shows_a_rename_with_both_uris() -> None:
    renamed = change(ChangeKind.RENAMED, "ex:Store", previous_curie="ex:Shop")

    out = render_commits([entry(renamed)])

    assert "ex:Shop" in out
    assert "ex:Store" in out


def test_commit_view_notes_non_rdf_files_changed() -> None:
    assert "2 non-RDF files" in render_commits([entry(change(), other_files=2)])


def test_commit_view_omits_the_non_rdf_note_when_there_are_none() -> None:
    assert "non-RDF" not in render_commits([entry(change(), other_files=0)])


def test_commit_with_no_semantic_change_is_reported_as_such() -> None:
    out = render_commits([entry(subject="reformat only")])

    assert "reformat only" in out
    assert "no semantic change" in out.lower()


def test_a_formatting_only_commit_says_it_is_formatting() -> None:
    """The file changed and the graph did not — say which, not just "nothing"."""
    assert "pure formatting" in render_commits([entry(subject="reformat only")]).lower()


def test_unreadable_commit_is_flagged_in_the_output() -> None:
    broken = CommitChanges(commit=commit(subject="broken"), changes=ChangeSet(()), unreadable=True)

    assert "unreadable" in render_commits([broken]).lower()


def test_empty_history_renders_a_no_commits_message() -> None:
    assert "no commits" in render_commits([]).lower()


# ── layer 3: the raw text, only on request ────────────────────────────────────


def with_raw_text() -> CommitChanges:
    return CommitChanges(
        commit=commit(),
        changes=ChangeSet((change(),)),
        raw_text="diff --git a/onto.ttl b/onto.ttl\n+ex:Vehicle a owl:Class .",
    )


def test_text_omitted_by_default() -> None:
    assert "diff --git" not in render_commits([with_raw_text()])


def test_text_option_includes_raw_hunk() -> None:
    assert "diff --git" in render_commits([with_raw_text()], show_text=True)


# ── layer 2: one entity's story ───────────────────────────────────────────────


def test_entity_view_filters_to_one_uri() -> None:
    history = [
        entry(change(ChangeKind.ADDED, PRODUCT), subject="one"),
        entry(change(ChangeKind.ADDED, "ex:Van"), subject="two"),
        entry(change(ChangeKind.MODIFIED, PRODUCT), subject="three"),
    ]

    out = render_entity(history, PRODUCT)

    assert "one" in out
    assert "three" in out
    assert "two" not in out


def test_entity_view_accepts_a_full_uri() -> None:
    history = [entry(change(ChangeKind.ADDED, PRODUCT), subject="one")]

    assert "one" in render_entity(history, "http://example.org/Product")


def test_entity_view_reports_when_entity_never_changed() -> None:
    out = render_entity([entry(change(ChangeKind.ADDED, PRODUCT))], "ex:Absent")

    assert "ex:Absent" in out
    assert "never changed" in out.lower()


# ── bulk individuals are counted, not listed ──────────────────────────────────
#
# On adeo-retail-geography, 9 301 of 9 414 output lines were individuals: 98.8%
# of the report, hiding 58 class and 26 property changes and two renames that
# were the only things worth reading.


def test_bulk_individual_additions_are_tallied_per_class() -> None:
    out = render_commits([entry(*individuals(1203, "City"))])

    assert "1203 individuals" in out
    assert "ex:n0" not in out


def test_tally_names_the_class() -> None:
    assert "(City)" in render_commits([entry(*individuals(20, "City"))])


def test_individuals_of_different_classes_are_tallied_separately() -> None:
    out = render_commits([entry(*individuals(20, "City"), *individuals(30, "Store", start=100))])

    assert "20 individuals" in out
    assert "30 individuals" in out


def test_added_and_removed_individuals_are_tallied_separately() -> None:
    out = render_commits(
        [
            entry(
                *individuals(20, "City"),
                *individuals(9, "City", kind=ChangeKind.REMOVED, start=100),
            )
        ]
    )

    assert "+20 individuals" in out
    assert "-9 individuals" in out


def test_a_few_individuals_are_listed_rather_than_tallied() -> None:
    """Three names say more than the number three."""
    out = render_commits([entry(*individuals(3, "City"))])

    assert "ex:n0" in out
    assert "3 individuals" not in out


def test_the_threshold_is_per_class_not_per_commit() -> None:
    out = render_commits([entry(*individuals(2, "City"), *individuals(2, "Store", start=100))])

    assert "individuals" not in out
    assert "ex:n0" in out and "ex:n100" in out


def test_renamed_individual_is_listed_even_when_siblings_are_tallied() -> None:
    renamed = change(
        ChangeKind.RENAMED,
        "ex:region-sibiu",
        previous_curie="ex:city-sibiu",
        entity=EntityKind.INDIVIDUAL,
        of_class="City",
    )
    out = render_commits([entry(*individuals(50, "City"), renamed)])

    assert "ex:city-sibiu" in out
    assert "ex:region-sibiu" in out
    assert "50 individuals" in out


def test_deprecated_individual_is_listed_even_when_siblings_are_tallied() -> None:
    gone = change(ChangeKind.DEPRECATED, "ex:old", entity=EntityKind.INDIVIDUAL, of_class="City")
    out = render_commits([entry(*individuals(50, "City"), gone)])

    assert "ex:old" in out


def test_classes_and_properties_are_never_tallied() -> None:
    many = [change(ChangeKind.ADDED, f"ex:C{i}") for i in range(30)]

    out = render_commits([entry(*many)])

    assert "ex:C0" in out
    assert "30 " not in out


def test_individuals_with_no_class_are_tallied_together() -> None:
    out = render_commits([entry(*individuals(20, None))])

    assert "20 individuals" in out


def test_a_tallied_commit_still_lists_its_class_changes() -> None:
    out = render_commits(
        [
            entry(
                change(ChangeKind.MODIFIED, PRODUCT, detail=("+2 properties",)),
                *individuals(50, "City"),
            )
        ]
    )

    assert PRODUCT in out
    assert "+2 properties" in out
    assert "50 individuals" in out
