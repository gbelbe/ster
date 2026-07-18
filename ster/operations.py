"""Compatibility shim — the domain logic now lives in the ``ster.domain`` package.

Every operation is re-exported here so existing call sites keep importing
``ster.operations``. New code should import from the matching layer module
directly: ``ster.domain.{skos,owl,onto,cross}``. See
docs/architecture/module-layout.md.
"""

from __future__ import annotations

from .domain.cross import DCT_SUBJECT as DCT_SUBJECT
from .domain.cross import _owns_owl as _owns_owl
from .domain.cross import add_schema_media as add_schema_media
from .domain.cross import count_uri_references as count_uri_references
from .domain.cross import demote_pun_to_concept as demote_pun_to_concept
from .domain.cross import expand_uri as expand_uri
from .domain.cross import language_in_use as language_in_use
from .domain.cross import promote_concept_to_class as promote_concept_to_class
from .domain.cross import remove_language as remove_language
from .domain.cross import remove_schema_media as remove_schema_media
from .domain.cross import rename_entity_uri as rename_entity_uri
from .domain.cross import resolve as resolve
from .domain.cross import tag_individual_with_concept as tag_individual_with_concept

# Re-export the ontology-metadata layer (moved to ster.domain.onto) so the ~37
# call sites keep importing from ster.operations. See docs/architecture/module-layout.md.
from .domain.onto import _ontology_separator as _ontology_separator
from .domain.onto import collect_ontology_entities as collect_ontology_entities
from .domain.onto import count_domain_rename_changes as count_domain_rename_changes
from .domain.onto import count_ontology_rename_changes as count_ontology_rename_changes
from .domain.onto import count_prefix_uses as count_prefix_uses
from .domain.onto import ontology_domain as ontology_domain
from .domain.onto import ontology_prefix as ontology_prefix
from .domain.onto import rename_ontology_domain as rename_ontology_domain
from .domain.onto import rename_ontology_uri as rename_ontology_uri
from .domain.onto import rename_prefix as rename_prefix
from .domain.onto import set_ontology_metadata as set_ontology_metadata
from .domain.onto import set_ontology_prefix as set_ontology_prefix
from .domain.onto import validate_domain as validate_domain
from .domain.onto import validate_prefix as validate_prefix
from .domain.owl import PROPERTY_KINDS as PROPERTY_KINDS
from .domain.owl import SUPPORTED_DATATYPES as SUPPORTED_DATATYPES
from .domain.owl import _owl_subclass_tree as _owl_subclass_tree
from .domain.owl import add_external_superclass as add_external_superclass
from .domain.owl import add_individual_type as add_individual_type
from .domain.owl import add_owl_individual as add_owl_individual
from .domain.owl import add_owl_property as add_owl_property
from .domain.owl import add_property_class as add_property_class
from .domain.owl import add_subclass_of as add_subclass_of
from .domain.owl import advance_property_create as advance_property_create
from .domain.owl import clear_property_values as clear_property_values
from .domain.owl import convert_class_to_individual as convert_class_to_individual
from .domain.owl import convert_individual_to_class as convert_individual_to_class
from .domain.owl import count_owl_uri_references as count_owl_uri_references
from .domain.owl import delete_owl_class as delete_owl_class
from .domain.owl import delete_owl_individual as delete_owl_individual
from .domain.owl import delete_owl_property as delete_owl_property
from .domain.owl import find_individuals_using_property as find_individuals_using_property
from .domain.owl import remove_individual_literal as remove_individual_literal
from .domain.owl import remove_individual_property_value as remove_individual_property_value
from .domain.owl import remove_individual_type as remove_individual_type
from .domain.owl import remove_owl_comment as remove_owl_comment
from .domain.owl import remove_owl_label as remove_owl_label
from .domain.owl import remove_property_class as remove_property_class
from .domain.owl import remove_subclass_of as remove_subclass_of
from .domain.owl import rename_owl_uri as rename_owl_uri
from .domain.owl import set_individual_literal as set_individual_literal
from .domain.owl import set_individual_property_value as set_individual_property_value
from .domain.owl import set_owl_comment as set_owl_comment
from .domain.owl import set_owl_label as set_owl_label
from .domain.owl import set_owl_note as set_owl_note
from .domain.skos import _is_ancestor as _is_ancestor
from .domain.skos import _subtree_uris as _subtree_uris
from .domain.skos import add_broader_link as add_broader_link
from .domain.skos import add_concept as add_concept
from .domain.skos import add_concept_mapping_link as add_concept_mapping_link
from .domain.skos import add_related as add_related
from .domain.skos import count_concept_uri_references as count_concept_uri_references
from .domain.skos import create_scheme as create_scheme
from .domain.skos import move_concept as move_concept
from .domain.skos import remove_concept as remove_concept
from .domain.skos import remove_concept_mapping_link as remove_concept_mapping_link
from .domain.skos import remove_definition as remove_definition
from .domain.skos import remove_label as remove_label
from .domain.skos import remove_related as remove_related
from .domain.skos import remove_scheme as remove_scheme
from .domain.skos import remove_scope_note as remove_scope_note
from .domain.skos import rename_uri as rename_uri
from .domain.skos import set_definition as set_definition
from .domain.skos import set_label as set_label
from .domain.skos import set_scheme_field as set_scheme_field
from .domain.skos import set_scope_note as set_scope_note
