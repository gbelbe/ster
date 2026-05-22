"""Unit tests for VOWL hierarchical layout optimisation helpers.

Tests _root_class_order(), _individual_orbit_data(), and the layout hints
embedded by build_vowl_graph() in its output payload.
"""

from __future__ import annotations

import math

from ster.model import (
    Concept,
    ConceptScheme,
    OWLIndividual,
    OWLProperty,
    RDFClass,
    Taxonomy,
)
from ster.viz_vowl import (
    _HTML_TEMPLATE,
    _individual_orbit_data,
    _root_class_order,
    build_vowl_graph,
)

NS = "https://example.org/onto#"


def uri(name: str) -> str:
    return NS + name


# ── _root_class_order ─────────────────────────────────────────────────────────


def test_root_class_order_empty():
    tax = Taxonomy()
    assert _root_class_order(tax) == []


def test_root_class_order_single_root():
    tax = Taxonomy()
    tax.owl_classes[uri("A")] = RDFClass(uri=uri("A"))
    result = _root_class_order(tax)
    assert result == [uri("A")]


def test_root_class_order_two_unconnected_stable():
    tax = Taxonomy()
    tax.owl_classes[uri("A")] = RDFClass(uri=uri("A"))
    tax.owl_classes[uri("B")] = RDFClass(uri=uri("B"))
    result = _root_class_order(tax)
    assert set(result) == {uri("A"), uri("B")}
    assert len(result) == 2


def test_root_class_order_connected_pair_adjacent():
    """A and B linked by objectProperty, C isolated → A and B must be adjacent."""
    tax = Taxonomy()
    tax.owl_classes[uri("A")] = RDFClass(uri=uri("A"))
    tax.owl_classes[uri("B")] = RDFClass(uri=uri("B"))
    tax.owl_classes[uri("C")] = RDFClass(uri=uri("C"))
    tax.owl_properties[uri("rel")] = OWLProperty(
        uri=uri("rel"),
        prop_type="ObjectProperty",
        domains=[uri("A")],
        ranges=[uri("B")],
    )
    result = _root_class_order(tax)
    idx_a = result.index(uri("A"))
    idx_b = result.index(uri("B"))
    assert abs(idx_a - idx_b) == 1


def test_root_class_order_chain_is_monotone():
    """A→B and B→C via objectProperties → order must be monotone: A,B,C or C,B,A."""
    tax = Taxonomy()
    for name in ("A", "B", "C"):
        tax.owl_classes[uri(name)] = RDFClass(uri=uri(name))
    tax.owl_properties[uri("p1")] = OWLProperty(
        uri=uri("p1"),
        prop_type="ObjectProperty",
        domains=[uri("A")],
        ranges=[uri("B")],
    )
    tax.owl_properties[uri("p2")] = OWLProperty(
        uri=uri("p2"),
        prop_type="ObjectProperty",
        domains=[uri("B")],
        ranges=[uri("C")],
    )
    result = _root_class_order(tax)
    idx = {name: result.index(uri(name)) for name in ("A", "B", "C")}
    # B must be between A and C
    assert min(idx["A"], idx["C"]) < idx["B"] < max(idx["A"], idx["C"])


def test_root_class_order_includes_all_roots():
    tax = Taxonomy()
    names = ("R1", "R2", "R3", "R4")
    for name in names:
        tax.owl_classes[uri(name)] = RDFClass(uri=uri(name))
    result = _root_class_order(tax)
    assert len(result) == 4
    assert set(result) == {uri(n) for n in names}


def test_root_class_order_intra_subtree_property_ignored():
    """objectProperty between classes in the same subtree must not change root order."""
    tax = Taxonomy()
    tax.owl_classes[uri("Root")] = RDFClass(uri=uri("Root"))
    tax.owl_classes[uri("Child")] = RDFClass(uri=uri("Child"), sub_class_of=[uri("Root")])
    tax.owl_classes[uri("Other")] = RDFClass(uri=uri("Other"))
    # property between Root and Child — same subtree, should not affect order
    tax.owl_properties[uri("p")] = OWLProperty(
        uri=uri("p"),
        prop_type="ObjectProperty",
        domains=[uri("Root")],
        ranges=[uri("Child")],
    )
    result = _root_class_order(tax)
    # Only Root and Other are roots; both must be present
    assert set(result) == {uri("Root"), uri("Other")}


# ── _individual_orbit_data ────────────────────────────────────────────────────


def test_orbit_data_no_individuals():
    tax = Taxonomy()
    tax.owl_classes[uri("A")] = RDFClass(uri=uri("A"))
    assert _individual_orbit_data(tax, [uri("A")]) == {}


def test_orbit_data_class_with_parent_only():
    """Individual on a leaf class whose only connection is its parent above.
    The free arc is downward (away from parent), so angle should be near +π/2.
    """
    tax = Taxonomy()
    tax.owl_classes[uri("Root")] = RDFClass(uri=uri("Root"))
    tax.owl_classes[uri("Leaf")] = RDFClass(uri=uri("Leaf"), sub_class_of=[uri("Root")])
    tax.owl_individuals[uri("Ind")] = OWLIndividual(uri=uri("Ind"), types=[uri("Leaf")])
    result = _individual_orbit_data(tax, [uri("Root")])
    angle = result[uri("Ind")]["angle"]
    # Parent is above (−π/2 direction); free arc is below (+π/2).
    # Allow ±π/2 tolerance around +π/2.
    assert abs(math.sin(angle) - 1.0) < 0.9  # sin near 1 means near +π/2


def test_orbit_data_class_with_no_connections():
    """Individual on an isolated root class → fallback angle is π/2."""
    tax = Taxonomy()
    tax.owl_classes[uri("Iso")] = RDFClass(uri=uri("Iso"))
    tax.owl_individuals[uri("Ind")] = OWLIndividual(uri=uri("Ind"), types=[uri("Iso")])
    result = _individual_orbit_data(tax, [uri("Iso")])
    assert math.isclose(result[uri("Ind")]["angle"], math.pi / 2, abs_tol=1e-9)


def test_orbit_data_orbit_r_subclass():
    """Non-root class: orbitR = 40 + 34 + 8 = 82."""
    tax = Taxonomy()
    tax.owl_classes[uri("Root")] = RDFClass(uri=uri("Root"))
    tax.owl_classes[uri("Sub")] = RDFClass(uri=uri("Sub"), sub_class_of=[uri("Root")])
    tax.owl_individuals[uri("Ind")] = OWLIndividual(uri=uri("Ind"), types=[uri("Sub")])
    result = _individual_orbit_data(tax, [uri("Root")])
    assert result[uri("Ind")]["orbit_r"] == 82


def test_orbit_data_orbit_r_root_class():
    """Root class: orbitR = 50 + 34 + 8 = 92."""
    tax = Taxonomy()
    tax.owl_classes[uri("Root")] = RDFClass(uri=uri("Root"))
    tax.owl_individuals[uri("Ind")] = OWLIndividual(uri=uri("Ind"), types=[uri("Root")])
    result = _individual_orbit_data(tax, [uri("Root")])
    assert result[uri("Ind")]["orbit_r"] == 92


def test_orbit_data_single_individual_zero_spread():
    """Single individual → arc spread is 0, angle equals free center exactly."""
    tax = Taxonomy()
    tax.owl_classes[uri("Root")] = RDFClass(uri=uri("Root"))
    tax.owl_individuals[uri("Ind")] = OWLIndividual(uri=uri("Ind"), types=[uri("Root")])
    result = _individual_orbit_data(tax, [uri("Root")])
    # With no connections, free center is π/2; single individual placed there
    assert math.isclose(result[uri("Ind")]["angle"], math.pi / 2, abs_tol=1e-9)


def test_orbit_data_multiple_individuals_distinct_angles():
    """Three individuals on the same class must all have distinct angles."""
    tax = Taxonomy()
    tax.owl_classes[uri("Root")] = RDFClass(uri=uri("Root"))
    for name in ("I1", "I2", "I3"):
        tax.owl_individuals[uri(name)] = OWLIndividual(uri=uri(name), types=[uri("Root")])
    result = _individual_orbit_data(tax, [uri("Root")])
    angles = [result[uri(n)]["angle"] for n in ("I1", "I2", "I3")]
    assert len(set(angles)) == 3


def test_orbit_data_angles_symmetric_around_free_center():
    """With 3 individuals and no connections, the middle angle equals π/2 (free center)."""
    tax = Taxonomy()
    tax.owl_classes[uri("Root")] = RDFClass(uri=uri("Root"))
    names = ("I1", "I2", "I3")
    for name in names:
        tax.owl_individuals[uri(name)] = OWLIndividual(uri=uri(name), types=[uri("Root")])
    result = _individual_orbit_data(tax, [uri("Root")])
    angles = sorted(result[uri(n)]["angle"] for n in names)
    mid = angles[1]
    assert math.isclose(mid, math.pi / 2, abs_tol=1e-9)


def test_orbit_data_many_individuals_use_multiple_rings():
    """When too many individuals to fit in one ring without overlapping, overflow
    goes into a second ring at a larger orbit radius."""
    tax = Taxonomy()
    tax.owl_classes[uri("Root")] = RDFClass(uri=uri("Root"))
    # Add 30 individuals — far more than can fit on a single ring of the root class
    names = [f"I{k}" for k in range(30)]
    for name in names:
        tax.owl_individuals[uri(name)] = OWLIndividual(uri=uri(name), types=[uri("Root")])
    result = _individual_orbit_data(tax, [uri("Root")])
    assert len(result) == 30
    orbit_radii = {od["orbit_r"] for od in result.values()}
    # Overflow must have triggered at least a second ring
    assert len(orbit_radii) >= 2
    # Every ring beyond the first must have a strictly larger radius
    for r in sorted(orbit_radii)[1:]:
        assert r > min(orbit_radii)


def test_orbit_data_individuals_do_not_overlap():
    """Adjacent individuals on the same ring must be separated by at least 2·r_ind."""
    from ster.viz_vowl import _INDIVIDUAL_R

    tax = Taxonomy()
    tax.owl_classes[uri("Root")] = RDFClass(uri=uri("Root"))
    names = [f"I{k}" for k in range(12)]
    for name in names:
        tax.owl_individuals[uri(name)] = OWLIndividual(uri=uri(name), types=[uri("Root")])
    result = _individual_orbit_data(tax, [uri("Root")])
    # Group by ring radius
    by_ring: dict[int, list[float]] = {}
    for od in result.values():
        by_ring.setdefault(od["orbit_r"], []).append(od["angle"])
    for ring_r, angles in by_ring.items():
        if len(angles) < 2:
            continue
        for a1, a2 in zip(sorted(angles), sorted(angles)[1:], strict=False):
            chord = 2 * ring_r * math.sin((a2 - a1) / 2)
            assert chord >= 2 * _INDIVIDUAL_R - 0.5  # allow 0.5 px rounding


# ── build_vowl_graph integration ──────────────────────────────────────────────


def test_build_vowl_graph_has_root_class_order_owl():
    tax = Taxonomy()
    tax.owl_classes[uri("A")] = RDFClass(uri=uri("A"))
    result = build_vowl_graph(tax)
    assert "rootClassOrder" in result
    assert isinstance(result["rootClassOrder"], list)


def test_build_vowl_graph_root_class_order_complete():
    tax = Taxonomy()
    tax.owl_classes[uri("A")] = RDFClass(uri=uri("A"))
    tax.owl_classes[uri("B")] = RDFClass(uri=uri("B"))
    result = build_vowl_graph(tax)
    assert set(result["rootClassOrder"]) == {uri("A"), uri("B")}
    assert len(result["rootClassOrder"]) == 2


def test_build_vowl_graph_individual_has_orbit_keys():
    tax = Taxonomy()
    tax.owl_classes[uri("A")] = RDFClass(uri=uri("A"))
    tax.owl_individuals[uri("Ind")] = OWLIndividual(uri=uri("Ind"), types=[uri("A")])
    result = build_vowl_graph(tax)
    ind_node = next(n for n in result["nodes"] if n["id"] == uri("Ind"))
    assert "orbitAngle" in ind_node
    assert "orbitR" in ind_node
    assert "orbitClassUri" in ind_node


def test_build_vowl_graph_class_node_has_group_radius():
    tax = Taxonomy()
    tax.owl_classes[uri("A")] = RDFClass(uri=uri("A"))
    tax.owl_individuals[uri("Ind")] = OWLIndividual(uri=uri("Ind"), types=[uri("A")])
    result = build_vowl_graph(tax)
    cls_node = next(n for n in result["nodes"] if n["id"] == uri("A"))
    assert "groupRadius" in cls_node
    assert cls_node["groupRadius"] > 50  # larger than root-class circle radius


def test_build_vowl_graph_skos_no_root_class_order():
    tax = Taxonomy()
    tax.schemes[uri("S")] = ConceptScheme(uri=uri("S"))
    tax.concepts[uri("Cat")] = Concept(uri=uri("Cat"))
    result = build_vowl_graph(tax)
    assert "rootClassOrder" not in result


# ── objectProperty ↔ subClassOf crossing avoidance ───────────────────────────


def test_html_template_contains_seg_cross():
    """_HTML_TEMPLATE must embed the segment-intersection helper for crossing avoidance."""
    assert "segCross" in _HTML_TEMPLATE


def test_html_template_avoids_op_sc_crossings_section_present():
    """Tick handler must include the objectProperty↔subClassOf crossing-avoidance loop."""
    assert "subClassOf" in _HTML_TEMPLATE
    assert "opSign" in _HTML_TEMPLATE
    assert "scLinks" in _HTML_TEMPLATE
