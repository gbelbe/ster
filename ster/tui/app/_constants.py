"""Module-level constants for the TUI app: tree/widget selectors, sentinel-data
prefixes/suffixes for tree-node ``data`` (property-header "add" and call-to-action
leaves), and small display lookup tables. Shared by the mixins and support modules
in this package.
"""

from __future__ import annotations

_ACTION_SUFFIX = "__"
_DETAIL_SELECTOR = "#detail"
_SOURCE_SELECTOR = "#source"
# The right pane is a switcher holding both faces of one slot: the composed
# detail panel and the entity's raw Turtle.
_RIGHT_SELECTOR = "#right"
_READ_ONLY_MESSAGE = "Read-only session (no file loaded)."
_TREE_SELECTOR = "#tree"
_ONTOLOGY_TREE_SELECTOR = "#ont-tree"
_PROPERTY_TREE_SELECTOR = "#prop-tree"
_CONTEXT_MENU_SELECTOR = "#ctx-menu"
_LOADING_SELECTOR = "#loading"
_LARGE_TAXONOMY_THRESHOLD = 10_000
# Human-readable resource type shown in the detail-pane title (e.g. "Person (Class)").
_KIND_TITLE = {
    "class": "Class",
    "individual": "Individual",
    "property": "Property",
    "scheme": "Concept scheme",
    "concept": "Concept",
}
# A property-section header's ``data``: distinct from an action sentinel so left-click /
# Enter just expands it, while right-click offers "add a property of this kind".
_ADD_PROP_PREFIX = "__addprop:"
# section): encodes the create action to run when it is activated (Enter / click). Distinct
# from a real entity URI and from the header add-sentinel above.
_CTA_PREFIX = "__cta:"
# The three OWL property kinds a header can create (the catch-all "Untyped Properties"
# group cannot). Object properties open the full modal; the other two a lightweight one.
# prop_type → (menu title, add-item label, create action, modal title).
_PROP_MENU: dict[str, tuple[str, str, str, str]] = {
    "ObjectProperty": (
        "Object properties",
        "＋ Add object property",
        "create_object_property",
        "New object property",
    ),
    "DatatypeProperty": (
        "Datatype properties",
        "＋ Add datatype property",
        "create_datatype_property",
        "New datatype property",
    ),
    "AnnotationProperty": (
        "Annotation properties",
        "＋ Add annotation property",
        "create_annotation_property",
        "New annotation property",
    ),
}
_CREATABLE_PROP_KINDS = frozenset(_PROP_MENU)
_PROP_CREATE_ACTIONS: dict[str, str] = {row[2]: kind for kind, row in _PROP_MENU.items()}

# Contextual keyboard hint shown on the focused pane's bottom border — one line per
# navigation layer, so the keys always match where the cursor is. Kept short to fit the
# border; the full cheat-sheet is the ? help screen.
_NAV_HINTS: dict[str, str] = {
    "panel": "↑↓ switch · ↵ open · ␣ fold",
    "item": "↑↓ nav · → detail · ^C copy · ␛ panels",
    "detail": "↑↓ rows · ↵ edit · ^C copy · ␛ panels",
}
