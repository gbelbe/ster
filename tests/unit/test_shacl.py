"""Unit tests for ster.shacl — the SHACL business-rule writer.

Pure engine (turtle text + sibling shapes.ttl I/O), isolating all SHACL authoring
behind one adapter so semanticlint stays the only SHACL *reader*.
"""

from __future__ import annotations

from pathlib import Path

from ster import shacl

ZOO = "https://example.org/zoo/"


def test_shapes_path_for_is_a_sibling_shapes_ttl() -> None:
    """The rules live next to the ontology as <stem>.shapes.ttl (semanticlint auto-picks
    up any *.shapes.ttl sibling)."""
    assert shacl.shapes_path_for(Path("/data/zoo.ttl")) == Path("/data/zoo.shapes.ttl")


def test_mandatory_property_rule_has_dated_comment_and_min_count() -> None:
    """The rule targets the class, requires the property (minCount 1), and is preceded
    by a dated comment explaining what it does."""
    iri, ttl = shacl.mandatory_property_rule(
        ZOO + "Animal",
        ZOO + "hasOwner",
        target_label="Animal",
        prop_label="has owner",
        date="2026-07-06",
    )
    assert ttl.startswith("# ster 2026-07-06:")  # dated comment first
    assert "Animal" in ttl and "has owner" in ttl  # explains what it enforces
    assert "a sh:NodeShape" in ttl
    assert f"sh:targetClass <{ZOO}Animal>" in ttl
    assert f"sh:path <{ZOO}hasOwner>" in ttl
    assert "sh:minCount 1" in ttl
    assert f"<{iri}>" in ttl  # the shape's own IRI heads the block


def test_mandatory_property_rule_iri_is_deterministic() -> None:
    """Same (target, property) → same shape IRI, so re-enforcing is idempotent."""
    a = shacl.mandatory_property_rule(
        ZOO + "Animal",
        ZOO + "hasOwner",
        target_label="Animal",
        prop_label="has owner",
        date="2026-07-06",
    )[0]
    b = shacl.mandatory_property_rule(
        ZOO + "Animal",
        ZOO + "hasOwner",
        target_label="Animal",
        prop_label="has owner",
        date="2027-01-01",
    )[0]
    assert a == b  # independent of the date


def test_append_rules_creates_file_with_sh_prefix(tmp_path) -> None:
    path = tmp_path / "zoo.shapes.ttl"
    rule = shacl.mandatory_property_rule(
        ZOO + "Animal",
        ZOO + "hasOwner",
        target_label="Animal",
        prop_label="has owner",
        date="2026-07-06",
    )
    written = shacl.append_rules(path, [rule])
    text = path.read_text(encoding="utf-8")
    assert written == [rule[0]]  # returns the IRI it wrote
    assert "@prefix sh: <http://www.w3.org/ns/shacl#> ." in text
    assert "sh:minCount 1" in text


def test_append_rules_is_idempotent(tmp_path) -> None:
    """Re-appending the same rule writes nothing and leaves the file unchanged."""
    path = tmp_path / "zoo.shapes.ttl"
    rule = shacl.mandatory_property_rule(
        ZOO + "Animal",
        ZOO + "hasOwner",
        target_label="Animal",
        prop_label="has owner",
        date="2026-07-06",
    )
    shacl.append_rules(path, [rule])
    before = path.read_text(encoding="utf-8")
    written = shacl.append_rules(path, [rule])
    assert written == []  # nothing new
    assert path.read_text(encoding="utf-8") == before  # byte-identical


def test_mandatory_on_node_rule_targets_the_node() -> None:
    """A node rule requires the property on one specific resource (the ontology), via
    sh:targetNode — used to enforce ontology-level metadata."""
    iri, ttl = shacl.mandatory_on_node_rule(
        ZOO,
        ZOO + "hasCreator",
        node_label="the ontology",
        prop_label="creator",
        date="2026-07-06",
    )
    assert ttl.startswith("# ster 2026-07-06:")
    assert f"sh:targetNode <{ZOO}>" in ttl
    assert f"sh:path <{ZOO}hasCreator>" in ttl and "sh:minCount 1" in ttl
    assert f"<{iri}>" in ttl


def test_node_and_class_rules_have_distinct_iris() -> None:
    """A node rule and a class rule for the same property don't collide."""
    node = shacl.mandatory_on_node_rule(
        ZOO, ZOO + "p", node_label="o", prop_label="p", date="2026-07-06"
    )[0]
    cls = shacl.mandatory_property_rule(
        ZOO + "C", ZOO + "p", target_label="C", prop_label="p", date="2026-07-06"
    )[0]
    assert node != cls


def test_remove_rules_drops_only_the_named_shapes(tmp_path) -> None:
    """remove_rules deletes the comment+shape block for each given IRI, leaving the rest
    of the file intact."""
    path = tmp_path / "zoo.shapes.ttl"
    keep = shacl.mandatory_property_rule(
        ZOO + "Animal",
        ZOO + "hasOwner",
        target_label="Animal",
        prop_label="has owner",
        date="2026-07-06",
    )
    drop = shacl.mandatory_property_rule(
        ZOO + "Person",
        ZOO + "hasName",
        target_label="Person",
        prop_label="has name",
        date="2026-07-06",
    )
    shacl.append_rules(path, [keep, drop])
    removed = shacl.remove_rules(path, [drop[0]])
    text = path.read_text(encoding="utf-8")
    assert removed == [drop[0]]
    assert f"<{keep[0]}>" in text  # kept rule still present
    assert f"<{drop[0]}>" not in text  # dropped rule gone
    assert "has name" not in text  # its comment gone too


def test_remove_rules_on_missing_iri_is_a_no_op(tmp_path) -> None:
    path = tmp_path / "zoo.shapes.ttl"
    rule = shacl.mandatory_property_rule(
        ZOO + "Animal",
        ZOO + "hasOwner",
        target_label="Animal",
        prop_label="has owner",
        date="2026-07-06",
    )
    shacl.append_rules(path, [rule])
    before = path.read_text(encoding="utf-8")
    assert shacl.remove_rules(path, ["urn:ster:shape:Nope:nope:required"]) == []
    assert path.read_text(encoding="utf-8") == before


def test_append_rules_writes_one_block_per_domain(tmp_path) -> None:
    path = tmp_path / "zoo.shapes.ttl"
    rules = [
        shacl.mandatory_property_rule(
            ZOO + "Animal",
            ZOO + "hasOwner",
            target_label="Animal",
            prop_label="has owner",
            date="2026-07-06",
        ),
        shacl.mandatory_property_rule(
            ZOO + "Person",
            ZOO + "hasOwner",
            target_label="Person",
            prop_label="has owner",
            date="2026-07-06",
        ),
    ]
    written = shacl.append_rules(path, rules)
    assert len(written) == 2
    text = path.read_text(encoding="utf-8")
    assert text.count("a sh:NodeShape") == 2
    assert text.count("@prefix sh:") == 1  # header written once
