"""Shared taxonomy detail/flatten logic for the New-TUI.

The old full-screen curses viewer and REPL shell were removed once the Textual
New-TUI (:mod:`ster.tui`) reached parity; what remains here is reused by the
New-TUI (:mod:`~ster.nav.logic` detail builders, :mod:`~ster.nav.prefs`,
:mod:`~ster.nav.ai_model_picker`).
"""

from __future__ import annotations

from .logic import (  # noqa: F401
    _ACTION_ADD_SCHEME,
    _FILE_URI_PREFIX,
    _GLOBAL_URI,
    _OWL_ONTOLOGY_PREFIX,
    _OWL_SECTION_URI,
    _UNATTACHED_INDS_URI,
    DetailField,
    TreeLine,
    _available_langs,
    _breadcrumb,
    _children,
    _count_descendants,
    _effective_types,
    _file_sentinel,
    _flatten_taxonomy,
    _flatten_workspace,
    _is_ontology_sentinel,
    _ontology_sentinel,
    _parent_uri,
    _sep,
    build_concept_detail,
    build_detail_fields,
    build_global_fields,
    build_individual_detail,
    build_ontology_overview_fields,
    build_promoted_detail,
    build_property_detail,
    build_rdf_class_detail,
    build_scheme_detail,
    build_scheme_fields,
    flatten_mixed_tree,
    flatten_ontology_tree,
    flatten_tree,
)
