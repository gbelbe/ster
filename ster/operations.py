"""Compatibility shim — the domain logic now lives in the ``ster.domain`` package.

Every operation is re-exported here so existing call sites keep importing
``ster.operations``. New code should import from the matching layer module
directly: ``ster.domain.{skos,owl,onto,cross}``. See
docs/architecture/module-layout.md.
"""

from __future__ import annotations

from .domain.cross import _owns_owl as _owns_owl
from .domain.cross import count_uri_references as count_uri_references
from .domain.cross import expand_uri as expand_uri
from .domain.cross import rename_entity_uri as rename_entity_uri
from .domain.cross import resolve as resolve

# Re-export the ontology-metadata layer (moved to ster.domain.onto) so the ~37
# call sites keep importing from ster.operations. See docs/architecture/module-layout.md.
from .domain.onto import collect_ontology_entities as collect_ontology_entities
from .domain.onto import count_domain_rename_changes as count_domain_rename_changes
from .domain.onto import count_ontology_rename_changes as count_ontology_rename_changes
from .domain.onto import count_prefix_uses as count_prefix_uses
from .domain.onto import ontology_domain as ontology_domain
from .domain.onto import ontology_prefix as ontology_prefix
from .domain.onto import rename_ontology_domain as rename_ontology_domain
from .domain.onto import rename_ontology_uri as rename_ontology_uri
from .domain.onto import rename_prefix as rename_prefix
from .domain.onto import validate_domain as validate_domain
from .domain.onto import validate_prefix as validate_prefix
from .domain.owl import PROPERTY_KINDS as PROPERTY_KINDS
from .domain.owl import SUPPORTED_DATATYPES as SUPPORTED_DATATYPES
from .domain.owl import _owl_subclass_tree as _owl_subclass_tree
from .domain.owl import add_owl_property as add_owl_property
from .domain.owl import add_subclass_of as add_subclass_of
from .domain.owl import advance_property_create as advance_property_create
from .domain.owl import clear_property_values as clear_property_values
from .domain.owl import count_owl_uri_references as count_owl_uri_references
from .domain.owl import delete_owl_class as delete_owl_class
from .domain.owl import delete_owl_property as delete_owl_property
from .domain.owl import find_individuals_using_property as find_individuals_using_property
from .domain.owl import rename_owl_uri as rename_owl_uri
from .domain.skos import _is_ancestor as _is_ancestor
from .domain.skos import _subtree_uris as _subtree_uris
from .domain.skos import add_broader_link as add_broader_link
from .domain.skos import add_concept as add_concept
from .domain.skos import add_related as add_related
from .domain.skos import count_concept_uri_references as count_concept_uri_references
from .domain.skos import create_scheme as create_scheme
from .domain.skos import move_concept as move_concept
from .domain.skos import remove_concept as remove_concept
from .domain.skos import remove_definition as remove_definition
from .domain.skos import remove_label as remove_label
from .domain.skos import remove_related as remove_related
from .domain.skos import remove_scope_note as remove_scope_note
from .domain.skos import rename_uri as rename_uri
from .domain.skos import set_definition as set_definition
from .domain.skos import set_label as set_label
from .domain.skos import set_scope_note as set_scope_note
