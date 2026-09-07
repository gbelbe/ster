"""Step definitions for the semanticdiff feature.

Graph-level scenarios build turtle in memory; history-level scenarios build a
real throw-away git repository, so the git adapter is exercised rather than
mocked.
"""

from __future__ import annotations

from typing import Any

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from rdflib import Graph

from semanticdiff.changeset import compare
from semanticdiff.git_log import UnknownRevisionError
from semanticdiff.history import read_history
from semanticdiff.render.text import render_commits, render_entity, render_summary
from semanticdiff.vocabulary import ChangeKind, EntityKind
from tests._ontology_repo import ONTOLOGY, RepoBuilder

scenarios("../features/semanticdiff/semantic_diff.feature")

PREFIXES = """
@prefix ex:   <http://example.org/> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
"""

RESTRICTION = """
ex:Vehicle a owl:Class ; rdfs:subClassOf [
    a owl:Restriction ;
    owl:onProperty ex:wheels ;
    owl:minCardinality "2"^^xsd:nonNegativeInteger
] .
"""

_KINDS = {
    "added": ChangeKind.ADDED,
    "removed": ChangeKind.REMOVED,
    "modified": ChangeKind.MODIFIED,
    "deprecated": ChangeKind.DEPRECATED,
}

_ENTITIES = {
    "class": EntityKind.CLASS,
    "property": EntityKind.PROPERTY,
    "concept": EntityKind.CONCEPT,
    "individual": EntityKind.INDIVIDUAL,
}


@pytest.fixture
def ctx() -> dict[str, Any]:
    return {"range": "HEAD"}


def turtle(body: str) -> Graph:
    graph = Graph()
    graph.parse(data=PREFIXES + body, format="turtle")
    return graph


def reserialised(graph: Graph) -> Graph:
    """The same graph, triples in a different order and blank nodes relabelled."""
    lines = graph.serialize(format="nt").splitlines()
    rebuilt = Graph()
    rebuilt.parse(data="\n".join(reversed(lines)), format="nt")
    return rebuilt


def _restriction(cls: str, prop: str, n: int) -> str:
    return (
        f"{cls} a owl:Class ; rdfs:subClassOf [ a owl:Restriction ; "
        f'owl:onProperty {prop} ; owl:cardinality "{n}"^^xsd:nonNegativeInteger ] .'
    )


def a_class(curie: str, label: str | None = None) -> str:
    suffix = f' ; rdfs:label "{label}"@en' if label else ""
    return f"{curie} a owl:Class{suffix} ."


def history_of(ctx: dict[str, Any], *, with_text: bool = False) -> list:
    if "history" not in ctx:
        ctx["history"] = read_history(ctx["repo"].path, ctx["range"], ONTOLOGY, with_text=with_text)
    return ctx["history"]


# ── Given: graphs ─────────────────────────────────────────────────────────────


@given(parsers.parse('a base graph with class "{curie}"'))
def given_base_class(ctx, curie):
    ctx["base"] = a_class(curie)


@given(parsers.parse('a base graph with class "{curie}" labelled "{label}"'))
def given_base_labelled(ctx, curie, label):
    ctx["base"] = a_class(curie, label)


@given(parsers.parse('a base graph with classes "{first}" and "{second}"'))
def given_base_two_classes(ctx, first, second):
    ctx["base"] = a_class(first) + a_class(second)


@given(parsers.parse('a base graph with classes "{first}" and "{second}" both labelled "{label}"'))
def given_base_two_same_label(ctx, first, second, label):
    ctx["base"] = a_class(first, label) + a_class(second, label)


@given(parsers.parse('a base graph with property "{prop}" with domain "{cls}"'))
def given_base_property(ctx, prop, cls):
    ctx["base"] = f"{prop} a owl:ObjectProperty ; rdfs:domain {cls} ."


@given(parsers.parse('a base graph with concept "{curie}"'))
def given_base_concept(ctx, curie):
    ctx["base"] = f"{curie} a skos:Concept ."


@given(parsers.parse('a base graph where "{cls}" restricts "{prop}" to {n:d}'))
def given_base_restriction_n(ctx, cls, prop, n):
    ctx["base"] = _restriction(cls, prop, n)


@given(parsers.parse('a later graph where "{cls}" restricts "{prop}" to {n:d}'))
def given_later_restriction_n(ctx, cls, prop, n):
    ctx["later"] = _restriction(cls, prop, n)


@given("a base graph with a restriction expressed through a blank node")
def given_base_restriction(ctx):
    ctx["base"] = RESTRICTION


@given(parsers.parse('a later graph with class "{curie}"'))
def given_later_class(ctx, curie):
    ctx["later"] = a_class(curie)


@given(parsers.parse('a later graph with class "{curie}" labelled "{label}"'))
def given_later_labelled(ctx, curie, label):
    ctx["later"] = a_class(curie, label)


@given(parsers.parse('a later graph with classes "{first}" and "{second}"'))
def given_later_two_classes(ctx, first, second):
    ctx["later"] = a_class(first) + a_class(second)


@given(parsers.parse('a later graph with property "{prop}" with domain "{cls}"'))
def given_later_property(ctx, prop, cls):
    ctx["later"] = f"{prop} a owl:ObjectProperty ; rdfs:domain {cls} ."


@given(parsers.parse('a later graph with concepts "{first}" and "{second}"'))
def given_later_two_concepts(ctx, first, second):
    ctx["later"] = f"{first} a skos:Concept . {second} a skos:Concept ."


@given(parsers.parse('a later graph where "{child}" is a subclass of "{parent}"'))
def given_later_subclass(ctx, child, parent):
    ctx["later"] = ctx["base"] + f"{child} a owl:Class ; rdfs:subClassOf {parent} ."


@given(parsers.parse('a later graph where "{prop}" is a property with domain "{cls}"'))
def given_later_domain(ctx, prop, cls):
    ctx["later"] = ctx["base"] + f"{prop} a owl:DatatypeProperty ; rdfs:domain {cls} ."


@given(parsers.parse('a later graph where "{curie}" is marked deprecated'))
def given_later_deprecated(ctx, curie):
    ctx["later"] = ctx["base"] + f"{curie} owl:deprecated true ."


@given("a later graph that is the same graph serialised with reordered triples")
@given("a later graph that is the same graph with different blank node ids")
def given_later_reserialised(ctx):
    ctx["reserialise"] = True


# ── Given: repositories ───────────────────────────────────────────────────────


@given(
    parsers.parse(
        'a repository whose ontology file was edited in three commits between "{start}" and "{end}"'
    )
)
def given_repo_three_commits(ctx, ontology_repo: RepoBuilder, start, end):
    ontology_repo.commit(ttl=a_class("ex:A"), message="base")
    ontology_repo.tag(start)
    for name in ("ex:B", "ex:C", "ex:D"):
        ontology_repo.commit(ttl=a_class("ex:A") + a_class(name), message=f"add {name}")
    ontology_repo.tag(end)
    ctx["repo"] = ontology_repo


@given("a repository with one commit editing the ontology and one editing the README")
def given_repo_mixed(ctx, ontology_repo: RepoBuilder):
    ontology_repo.commit(ttl=a_class("ex:A"), message="ontology")
    ontology_repo.commit(files={"README.md": "hello"}, message="readme only")
    ctx["repo"] = ontology_repo


@given("a repository whose first commit adds an ontology with two classes")
def given_repo_first_commit(ctx, ontology_repo: RepoBuilder):
    ontology_repo.commit(ttl=a_class("ex:A") + a_class("ex:B"), message="initial")
    ctx["repo"] = ontology_repo


@given("a repository with one commit")
def given_repo_one_commit(ctx, ontology_repo: RepoBuilder):
    ontology_repo.commit(ttl=a_class("ex:A"), message="only")
    ctx["repo"] = ontology_repo


@given("a repository whose middle commit leaves the ontology file unparseable")
def given_repo_broken_middle(ctx, ontology_repo: RepoBuilder):
    ontology_repo.commit(ttl=a_class("ex:A"), message="good one")
    ontology_repo.commit(raw="not turtle at all {{{", message="broken one")
    ontology_repo.commit(ttl=a_class("ex:A") + a_class("ex:B"), message="good two")
    ctx["repo"] = ontology_repo


@given("a repository whose commit edits the ontology and two unrelated files")
def given_repo_extra_files(ctx, ontology_repo: RepoBuilder):
    ontology_repo.commit(
        ttl=a_class("ex:A"),
        files={"README.md": "hi", "notes.txt": "n"},
        message="mixed",
    )
    ctx["repo"] = ontology_repo


@given("a history adding two classes, modifying one and removing one")
def given_history_mixed_counts(ctx, ontology_repo: RepoBuilder):
    ontology_repo.commit(ttl=a_class("ex:A") + a_class("ex:B") + a_class("ex:Old"), message="base")
    ontology_repo.tag("v0.1")
    ontology_repo.commit(
        ttl=a_class("ex:A", "A") + a_class("ex:B") + a_class("ex:C") + a_class("ex:D"),
        message="churn",
    )
    ontology_repo.tag("v0.2")
    ctx["repo"] = ontology_repo
    ctx["range"] = "v0.1..v0.2"


@given(parsers.parse('a history whose commit adds class "{curie}"'))
def given_history_adds_class(ctx, ontology_repo: RepoBuilder, curie):
    ontology_repo.commit(ttl=a_class(curie), message=f"add {curie}")
    ctx["repo"] = ontology_repo


@given(parsers.parse('a history whose commit adds class "{curie}" labelled "{label}"'))
def given_history_adds_labelled(ctx, ontology_repo: RepoBuilder, curie, label):
    ontology_repo.commit(ttl=a_class(curie, label), message=f"add {curie}")
    ctx["repo"] = ontology_repo


@given(parsers.parse('a history whose commit adds {count:d} individuals of class "{cls}"'))
def given_history_many_individuals(ctx, ontology_repo: RepoBuilder, count, cls):
    body = [a_class(f"ex:{cls}", cls)]
    body += [f"ex:n{i} a ex:{cls} ." for i in range(count)]
    ontology_repo.commit(ttl="".join(body), message=f"add {count} {cls}")
    ctx["repo"] = ontology_repo
    ctx["count"] = count


@given("a repository whose commit only reformats the ontology")
def given_repo_reformat_only(ctx, ontology_repo: RepoBuilder):
    ontology_repo.commit(ttl='ex:A a owl:Class ; rdfs:label "A"@en .', message="first")
    ontology_repo.commit(
        ttl='# regrouped\nex:A\n    rdfs:label """A"""@en ;\n    a owl:Class .',
        message="reformat only",
    )
    ctx["repo"] = ontology_repo


@given(parsers.parse('a history in which "{first}" changed twice and "{second}" changed once'))
def given_history_two_entities(ctx, ontology_repo: RepoBuilder, first, second):
    ontology_repo.commit(ttl=a_class(first), message="one")
    ontology_repo.commit(ttl=a_class(first, "Product"), message="two")
    ontology_repo.commit(ttl=a_class(first, "Product") + a_class(second), message="three")
    ctx["repo"] = ontology_repo


# ── When ──────────────────────────────────────────────────────────────────────


@when("the two graphs are compared")
def when_compared(ctx):
    base = turtle(ctx["base"]) if "base" in ctx else Graph()
    later = reserialised(base) if ctx.get("reserialise") else turtle(ctx["later"])
    ctx["changes"] = compare(base, later)


@when(parsers.parse('the history is read between "{start}" and "{end}"'))
def when_history_between(ctx, start, end):
    ctx["range"] = f"{start}..{end}"
    ctx["history"] = read_history(ctx["repo"].path, ctx["range"], ONTOLOGY)


@when("the whole history is read")
def when_history_whole(ctx):
    ctx["history"] = read_history(ctx["repo"].path, "HEAD", ONTOLOGY)


@when("the history is read for a revision that does not exist")
def when_history_unknown_rev(ctx):
    try:
        read_history(ctx["repo"].path, "v9.9..HEAD", ONTOLOGY)
    except UnknownRevisionError as exc:
        ctx["error"] = exc


@when("the summary is rendered")
def when_summary(ctx):
    ctx["output"] = render_summary(history_of(ctx), ctx["range"])


@when("the per-commit view is rendered")
@when("the per-commit view is rendered without the text option")
def when_commits(ctx):
    ctx["output"] = render_commits(history_of(ctx, with_text=True))


@when("the per-commit view is rendered with the text option")
def when_commits_with_text(ctx):
    ctx["output"] = render_commits(history_of(ctx, with_text=True), show_text=True)


@when(parsers.parse('the history of "{curie}" is rendered'))
def when_entity(ctx, curie):
    ctx["output"] = render_entity(history_of(ctx), curie)


# ── Then: changes ─────────────────────────────────────────────────────────────


def found(ctx, curie: str, kind: ChangeKind, entity: str | None = None) -> bool:
    """Whether a change of that kind — and, when named, that entity kind — is reported."""
    return any(
        change.curie == curie
        and change.kind is kind
        and (entity is None or change.entity is _ENTITIES[entity])
        for change in ctx["changes"]
    )


@then(parsers.parse('the changes include an added {entity} "{curie}"'))
def then_added(ctx, entity, curie):
    assert found(ctx, curie, ChangeKind.ADDED, entity), ctx["changes"]


@then(parsers.parse('the changes include a removed {entity} "{curie}"'))
def then_removed(ctx, entity, curie):
    assert found(ctx, curie, ChangeKind.REMOVED, entity), ctx["changes"]


@then(parsers.parse('the changes include a modified {entity} "{curie}"'))
def then_modified(ctx, entity, curie):
    assert found(ctx, curie, ChangeKind.MODIFIED, entity), ctx["changes"]


@then(parsers.parse('the changes include a deprecated {entity} "{curie}"'))
def then_deprecated(ctx, entity, curie):
    assert found(ctx, curie, ChangeKind.DEPRECATED, entity), ctx["changes"]


@then(parsers.parse('"{curie}" is not reported as {kind}'))
def then_not_reported(ctx, curie, kind):
    assert not found(ctx, curie, _KINDS[kind]), ctx["changes"]


@then(parsers.parse('the detail for "{curie}" mentions "{text}"'))
def then_detail(ctx, curie, text):
    details = [c.detail for c in ctx["changes"] if c.curie == curie]
    assert any(text in d for detail in details for d in detail), details


@then("no class is reported as removed")
def then_none_removed(ctx):
    assert all(c.kind is not ChangeKind.REMOVED for c in ctx["changes"])


@then(parsers.parse('the changes include a rename from "{old}" to "{new}"'))
def then_rename(ctx, old, new):
    assert any(
        c.kind is ChangeKind.RENAMED and c.previous_curie == old and c.curie == new
        for c in ctx["changes"]
    ), ctx["changes"]


@then("no blank node is named in the changes")
def then_no_blank_node(ctx):
    assert all(not c.curie.startswith("_:") for c in ctx["changes"]), ctx["changes"]


@then("no rename is reported")
def then_no_rename(ctx):
    assert all(c.kind is not ChangeKind.RENAMED for c in ctx["changes"])


@then("no changes are reported")
def then_no_changes(ctx):
    assert len(ctx["changes"]) == 0, ctx["changes"]


# ── Then: history ─────────────────────────────────────────────────────────────


@then("three commits are reported")
def then_three_commits(ctx):
    assert len(ctx["history"]) == 3


@then("one commit is reported")
def then_one_commit(ctx):
    assert len(ctx["history"]) == 1


@then("each reported commit carries its author, date and subject")
def then_commit_metadata(ctx):
    for entry in ctx["history"]:
        assert entry.commit.author
        assert entry.commit.date
        assert entry.commit.subject


@then("both classes are reported as added")
def then_both_added(ctx):
    changes = ctx["history"][0].changes
    assert {c.curie for c in changes} == {"ex:A", "ex:B"}
    assert all(c.kind is ChangeKind.ADDED for c in changes)


@then("an error naming the unknown revision is raised")
def then_unknown_rev(ctx):
    assert isinstance(ctx.get("error"), UnknownRevisionError)
    assert "v9.9" in str(ctx["error"])


@then("that commit is reported as unreadable")
def then_unreadable(ctx):
    assert ctx["history"][1].unreadable is True


@then("the surrounding commits are still reported")
def then_surrounding(ctx):
    assert ctx["history"][0].unreadable is False
    assert ctx["history"][2].unreadable is False


# ── Then: rendered output ─────────────────────────────────────────────────────


@then("the summary states two additions, one modification and one removal")
def then_summary_counts(ctx):
    assert "2 added" in ctx["output"]
    assert "1 modified" in ctx["output"]
    assert "1 removed" in ctx["output"]


@then(parsers.parse('the output names "{curie}" as added under that commit'))
def then_output_names(ctx, curie):
    assert curie in ctx["output"]
    assert "+" in ctx["output"]


@then(parsers.parse('the output shows the label "{label}"'))
def then_output_label(ctx, label):
    assert label in ctx["output"]


@then(parsers.parse('only the two commits touching "{curie}" are shown'))
def then_entity_commits(ctx, curie):
    assert ctx["output"].count("●") == 2
    assert "three" not in ctx["output"]


@then("no raw diff hunk appears in the output")
def then_no_hunk(ctx):
    assert "diff --git" not in ctx["output"]


@then("the raw diff hunk appears in the output")
def then_hunk(ctx):
    assert "diff --git" in ctx["output"]


@then(parsers.parse("the output counts {count:d} individuals"))
def then_counts_individuals(ctx, count):
    assert f"{count} individuals" in ctx["output"]


@then("the output does not name them one by one")
def then_not_named(ctx):
    assert "ex:n0" not in ctx["output"]


@then("the output names them one by one")
def then_named(ctx):
    assert "ex:n0" in ctx["output"]
    assert "individuals" not in ctx["output"]


@then(parsers.parse('the count names the class "{cls}"'))
def then_count_names_class(ctx, cls):
    assert f"({cls})" in ctx["output"]


@then("the output says the change was pure formatting")
def then_pure_formatting(ctx):
    assert "pure formatting" in ctx["output"].lower()


@then("the output notes two non-RDF files changed")
def then_non_rdf(ctx):
    assert "2 non-RDF files" in ctx["output"]
