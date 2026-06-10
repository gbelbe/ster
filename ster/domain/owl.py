"""OWL operations — classes, properties, individuals, and the subclass hierarchy.

Part of the domain layer (docs/architecture/module-layout.md): reached through
``ster.operations``, never imported directly by a front-end.
"""

from __future__ import annotations

from ..exceptions import CircularHierarchyError, ClassNotFoundError, URIAlreadyExistsError
from ..model import Label, OWLIndividual, OWLProperty, Taxonomy
from ._shared import _replace_in_list


def add_owl_property(
    taxonomy: Taxonomy,
    uri: str,
    prop_type: str,
    label: str,
    lang: str,
    domain_uri: str | None = None,
    range_uri: str | None = None,
) -> OWLProperty:
    """Create a new OWL property and register it in *taxonomy*.

    Raises ValueError if *uri* is already taken.
    """
    if uri in taxonomy.owl_properties:
        raise ValueError(f"Property already exists: {uri}")
    labels = [Label(lang=lang, value=label)] if label else []
    domains = [domain_uri] if domain_uri else []
    ranges = [range_uri] if range_uri else []
    prop = OWLProperty(uri=uri, prop_type=prop_type, labels=labels, domains=domains, ranges=ranges)
    taxonomy.owl_properties[uri] = prop
    return prop


_XSD = "http://www.w3.org/2001/XMLSchema#"

# Datatypes offered when defining an attribute (datatype property) on a class.
SUPPORTED_DATATYPES: list[tuple[str, str]] = [
    ("string", _XSD + "string"),
    ("URL (anyURI)", _XSD + "anyURI"),
    ("integer", _XSD + "integer"),
    ("decimal", _XSD + "decimal"),
    ("boolean", _XSD + "boolean"),
    ("date", _XSD + "date"),
    ("dateTime", _XSD + "dateTime"),
]

# Kind picker rows: (label, prop_type). Index 0 = attribute, 1 = relationship.
PROPERTY_KINDS: list[tuple[str, str]] = [
    ("Attribute (data value)", "DatatypeProperty"),
    ("Relationship (link to another entity)", "ObjectProperty"),
]


def advance_property_create(step: str, choice: int) -> tuple[str, str | None, str | None]:
    """Advance the add-class-property picker by one selection.

    Returns ``(next, prop_type, range_uri)``:
    - ``("datatype", None, None)`` — show the datatype picker next (attribute kind);
    - ``("create", "ObjectProperty", None)`` — prompt for a URI and create a relationship;
    - ``("create", "DatatypeProperty", <xsd uri>)`` — prompt for a URI and create an
      attribute with the chosen datatype as its range.
    """
    if step == "kind":
        if choice == 0:  # Attribute → choose a datatype first
            return ("datatype", None, None)
        return ("create", "ObjectProperty", None)  # Relationship
    # step == "datatype"
    _label, range_uri = SUPPORTED_DATATYPES[choice]
    return ("create", "DatatypeProperty", range_uri)


def find_individuals_using_property(taxonomy: Taxonomy, prop_uri: str) -> list[str]:
    """Return URIs of all individuals that have at least one value for *prop_uri*."""
    return [
        ind_uri
        for ind_uri, ind in taxonomy.owl_individuals.items()
        if any(pv_uri == prop_uri for pv_uri, _ in ind.property_values)
    ]


def delete_owl_property(taxonomy: Taxonomy, prop_uri: str) -> list[str]:
    """Remove *prop_uri* from *taxonomy* and return impacted individual URIs.

    Raises KeyError if the property does not exist.
    """
    impacted = find_individuals_using_property(taxonomy, prop_uri)
    del taxonomy.owl_properties[prop_uri]
    return impacted


def clear_property_values(taxonomy: Taxonomy, prop_uri: str) -> None:
    """Remove all property-value tuples for *prop_uri* from every individual."""
    for ind in taxonomy.owl_individuals.values():
        ind.property_values = [(p, v) for p, v in ind.property_values if p != prop_uri]


def _owl_subclass_tree(taxonomy: Taxonomy, root_uri: str) -> set[str]:
    """Return all URIs in the OWL subclass tree rooted at *root_uri* (inclusive)."""
    result: set[str] = set()

    def visit(u: str) -> None:
        if u in result:
            return
        result.add(u)
        for other_uri, cls in taxonomy.owl_classes.items():
            if u in cls.sub_class_of and other_uri not in result:
                visit(other_uri)

    visit(root_uri)
    return result


def delete_owl_class(
    taxonomy: Taxonomy,
    uri: str,
    *,
    mode: str,
) -> None:
    """Delete an OWL class from *taxonomy*.

    *mode* controls how subclasses and typed individuals are handled:

    ``"keep_all"``
        Delete the class only.  Direct subclasses are re-parented to the
        deleted class's own parents (or become roots).  Individuals typed
        as the deleted class are re-typed to those same parents.

    ``"cascade_subclasses"``
        Delete the class and all its subclass descendants (transitive).
        Individuals typed to any deleted class are re-typed to the deleted
        class's parents (or lose all types when there are none).

    ``"delete_all"``
        Delete the class, all subclass descendants, and every individual
        typed to any of the deleted classes.
    """
    if uri not in taxonomy.owl_classes:
        return

    deleted_cls = taxonomy.owl_classes[uri]
    # parents of the class being deleted (only those that are themselves OWL classes)
    surviving_parents = [
        p for p in deleted_cls.sub_class_of if p in taxonomy.owl_classes and p != uri
    ]
    deleted_uris = {uri} if mode == "keep_all" else _owl_subclass_tree(taxonomy, uri)

    _retype_individuals_after_delete(taxonomy, deleted_uris, surviving_parents, mode)
    _reparent_classes_after_delete(taxonomy, deleted_uris, surviving_parents)
    _strip_property_refs_to_deleted(taxonomy, deleted_uris)
    for dead in deleted_uris:
        taxonomy.owl_classes.pop(dead, None)


def _retype_individuals_after_delete(
    taxonomy: Taxonomy, deleted_uris: set[str], surviving_parents: list[str], mode: str
) -> None:
    """Re-type (or, in delete_all mode, delete) individuals typed by a removed class."""
    for ind_uri in list(taxonomy.owl_individuals):
        ind = taxonomy.owl_individuals[ind_uri]
        affected_types = [t for t in ind.types if t in deleted_uris]
        if not affected_types:
            continue
        if mode == "delete_all":
            del taxonomy.owl_individuals[ind_uri]
            continue
        for t in affected_types:
            ind.types.remove(t)
        for parent in surviving_parents:
            if parent not in ind.types:
                ind.types.append(parent)


def _reparent_classes_after_delete(
    taxonomy: Taxonomy, deleted_uris: set[str], surviving_parents: list[str]
) -> None:
    """Detach deleted classes from other classes' sub_class_of, re-parenting to survivors."""
    for other_uri, cls in taxonomy.owl_classes.items():
        if other_uri in deleted_uris:
            continue
        for dead in deleted_uris:
            if dead in cls.sub_class_of:
                cls.sub_class_of.remove(dead)
                for parent in surviving_parents:
                    if parent not in cls.sub_class_of and parent != other_uri:
                        cls.sub_class_of.append(parent)


def _strip_property_refs_to_deleted(taxonomy: Taxonomy, deleted_uris: set[str]) -> None:
    """Drop deleted-class URIs from every property's domains and ranges."""
    for prop in taxonomy.owl_properties.values():
        prop.domains = [d for d in prop.domains if d not in deleted_uris]
        prop.ranges = [r for r in prop.ranges if r not in deleted_uris]


# ──────────────────────────── OWL promotion ──────────────────────────────────


# ──────────────────────────── OWL subclass hierarchy ─────────────────────────


def add_subclass_of(taxonomy: Taxonomy, child_uri: str, parent_uri: str) -> None:
    """Add an rdfs:subClassOf link from child_uri to parent_uri.

    Idempotent: calling twice with the same arguments has no effect.
    Raises ClassNotFoundError if either URI is absent from owl_classes.
    Raises CircularHierarchyError on self-reference or transitively circular links.
    """
    if child_uri not in taxonomy.owl_classes:
        raise ClassNotFoundError(child_uri)
    if parent_uri not in taxonomy.owl_classes:
        raise ClassNotFoundError(parent_uri)
    if child_uri == parent_uri:
        raise CircularHierarchyError(child_uri, parent_uri)
    if _is_class_ancestor(taxonomy, child_uri, parent_uri):
        raise CircularHierarchyError(parent_uri, child_uri)
    child = taxonomy.owl_classes[child_uri]
    if parent_uri not in child.sub_class_of:
        child.sub_class_of.append(parent_uri)


# ──────────────────────────── internal helpers ───────────────────────────────


def _is_class_ancestor(taxonomy: Taxonomy, candidate_uri: str, of_uri: str) -> bool:
    """Return True if candidate_uri is an ancestor of of_uri in the OWL class hierarchy."""
    visited: set[str] = set()

    def check(uri: str) -> bool:
        if uri in visited:
            return False
        visited.add(uri)
        cls = taxonomy.owl_classes.get(uri)
        if not cls:
            return False
        for parent_uri in cls.sub_class_of:
            if parent_uri == candidate_uri:
                return True
            if check(parent_uri):
                return True
        return False

    return check(of_uri)


# ──────────────────────────── OWL URI rename ─────────────────────────────────


def rename_owl_uri(taxonomy: Taxonomy, old_uri: str, new_uri: str) -> None:
    """Rename an OWL class, individual, or property URI, updating all references.

    Raises URIAlreadyExistsError if *new_uri* is already occupied by any entity
    in owl_classes, owl_individuals, or owl_properties.
    """
    all_uris = (
        set(taxonomy.owl_classes) | set(taxonomy.owl_individuals) | set(taxonomy.owl_properties)
    )
    if new_uri in all_uris:
        raise URIAlreadyExistsError(new_uri)

    if old_uri in taxonomy.owl_classes:
        _rename_owl_class(taxonomy, old_uri, new_uri)
    elif old_uri in taxonomy.owl_individuals:
        _rename_owl_individual(taxonomy, old_uri, new_uri)
    elif old_uri in taxonomy.owl_properties:
        _rename_owl_property(taxonomy, old_uri, new_uri)


def _rename_owl_class(taxonomy: Taxonomy, old_uri: str, new_uri: str) -> None:
    cls = taxonomy.owl_classes.pop(old_uri)
    cls.uri = new_uri
    taxonomy.owl_classes[new_uri] = cls

    # Update own sub_class_of list (if it somehow self-referenced)
    _replace_in_list(cls.sub_class_of, old_uri, new_uri)

    # Update all other classes
    for other_cls in taxonomy.owl_classes.values():
        _replace_in_list(other_cls.sub_class_of, old_uri, new_uri)
        _replace_in_list(other_cls.equivalent_class, old_uri, new_uri)
        _replace_in_list(other_cls.disjoint_with, old_uri, new_uri)

    # Update individuals' rdf:type lists
    for ind in taxonomy.owl_individuals.values():
        _replace_in_list(ind.types, old_uri, new_uri)

    # Update property domains and ranges
    for prop in taxonomy.owl_properties.values():
        _replace_in_list(prop.domains, old_uri, new_uri)
        _replace_in_list(prop.ranges, old_uri, new_uri)


def _rename_owl_individual(taxonomy: Taxonomy, old_uri: str, new_uri: str) -> None:
    ind = taxonomy.owl_individuals.pop(old_uri)
    ind.uri = new_uri
    taxonomy.owl_individuals[new_uri] = ind

    # Update other individuals' property_values where this URI appears as value
    for other_ind in taxonomy.owl_individuals.values():
        other_ind.property_values = [
            (p, new_uri if v == old_uri else v) for p, v in other_ind.property_values
        ]
        other_ind.literal_values = [
            (new_uri if p == old_uri else p, v, ld) for p, v, ld in other_ind.literal_values
        ]


def _rename_owl_property(taxonomy: Taxonomy, old_uri: str, new_uri: str) -> None:
    prop = taxonomy.owl_properties.pop(old_uri)
    prop.uri = new_uri
    taxonomy.owl_properties[new_uri] = prop

    # Update all individuals' property_values and literal_values where this URI appears as predicate
    for ind in taxonomy.owl_individuals.values():
        ind.property_values = [(new_uri if p == old_uri else p, v) for p, v in ind.property_values]
        ind.literal_values = [
            (new_uri if p == old_uri else p, v, ld) for p, v, ld in ind.literal_values
        ]

    # Update other properties referencing this one via subPropertyOf / inverseOf
    for other_prop in taxonomy.owl_properties.values():
        _replace_in_list(other_prop.sub_property_of, old_uri, new_uri)
        _replace_in_list(other_prop.inverse_of, old_uri, new_uri)


def count_owl_uri_references(taxonomy: Taxonomy, uri: str) -> int:
    """Count the number of RDF-model positions where *uri* appears.

    Counts both the entity's own triples (subject) and all cross-references
    from other entities (object / predicate).  Used to inform the user how
    many statements will change when a URI is renamed.
    """
    return _count_owl_own_triples(taxonomy, uri) + _count_owl_incoming_refs(taxonomy, uri)


def _count_owl_own_triples(taxonomy: Taxonomy, uri: str) -> int:
    """Count the subject triples of *uri*'s own class / individual / property declaration."""
    count = 0
    if uri in taxonomy.owl_classes:
        c = taxonomy.owl_classes[uri]
        count += 1 + len(c.labels) + len(c.comments)
        count += len(c.sub_class_of) + len(c.equivalent_class) + len(c.disjoint_with)
    if uri in taxonomy.owl_individuals:
        i = taxonomy.owl_individuals[uri]
        count += 1 + len(i.labels) + len(i.comments) + len(i.types) + len(i.property_values)
    if uri in taxonomy.owl_properties:
        p = taxonomy.owl_properties[uri]
        count += 1 + len(p.labels) + len(p.comments) + len(p.domains) + len(p.ranges)
    return count


def _count_individual_refs_to(ind: OWLIndividual, uri: str) -> int:
    """Count how many times *uri* appears in one individual's types / property values."""
    n = ind.types.count(uri)
    n += sum(1 for p, v in ind.property_values if uri in (p, v))
    n += sum(1 for p, _v, _ld in ind.literal_values if p == uri)
    return n


def _count_owl_incoming_refs(taxonomy: Taxonomy, uri: str) -> int:
    """Count references to *uri* from other classes / individuals / properties."""
    count = 0
    for cls_uri, cls in taxonomy.owl_classes.items():
        if cls_uri != uri:
            count += cls.sub_class_of.count(uri) + cls.equivalent_class.count(uri)
            count += cls.disjoint_with.count(uri)
    for ind_uri, ind in taxonomy.owl_individuals.items():
        if ind_uri != uri:
            count += _count_individual_refs_to(ind, uri)
    for prop_uri, prop in taxonomy.owl_properties.items():
        if prop_uri != uri:
            count += prop.domains.count(uri) + prop.ranges.count(uri)
            count += prop.sub_property_of.count(uri) + prop.inverse_of.count(uri)
    return count
