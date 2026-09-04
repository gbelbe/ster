"""Module-level helper functions for the TUI app: the API-server bridge
(best-effort context publishing for MCP), the codec functions for tree-node
``data`` sentinels (property-header "add" prefixes, call-to-action leaf
prefixes), and the panel-layer navigation hint text.
"""

from __future__ import annotations

from pathlib import Path

from ster.model import Taxonomy

from ._constants import _ACTION_SUFFIX, _ADD_PROP_PREFIX, _CTA_PREFIX, _NAV_HINTS


def _start_context_server(taxonomy: Taxonomy, path: Path | None) -> bool:
    """Bring up the API server so agents can reach the MCP endpoint.

    Runs on a daemon thread beside the TUI. Best-effort: a taken port (a second
    ster instance, say) just means no MCP this session — it must never stop the
    editor from opening. No HTML renderer is supplied; opening the graph viewer
    later attaches the VOWL one to this same server.
    """
    try:
        from ...api_server import start_background  # noqa: PLC0415

        return start_background(taxonomy, path)
    except Exception:  # noqa: BLE001 — the editor must open regardless
        return False


def _publish_selection(uri: str | None) -> None:
    """Tell the running API server which entity is on screen, for MCP's
    ``get_current_context``.

    A no-op when no server is running (the common case — the server only starts
    once a file is opened), and never allowed to disturb navigation: publishing
    context is strictly best-effort.
    """
    try:
        from ...api_server import current_app  # noqa: PLC0415

        app = current_app()
        if app is not None:
            app.state._ster["selection"] = uri
    except Exception:  # noqa: BLE001 — context publishing must never break the UI
        pass


def _add_prop_uri(prop_type: str) -> str:
    return f"{_ADD_PROP_PREFIX}{prop_type}{_ACTION_SUFFIX}"


def _prop_section_key(prop_type: str) -> str:
    """Stable focus key for a property-tree section (Object / Datatype / …), so a deleted
    top-level property can land the cursor on its section. The three OWL kinds map straight
    across; anything else falls to the 'Untyped Properties' section."""
    known = {"ObjectProperty", "DatatypeProperty", "AnnotationProperty"}
    return f"__ster:propsection:{prop_type if prop_type in known else 'Property'}__"


def _parse_add_prop(uri: str | None) -> str | None:
    """The property type of an "add property here" section sentinel, else None."""
    if uri and uri.startswith(_ADD_PROP_PREFIX) and uri.endswith(_ACTION_SUFFIX):
        return uri[len(_ADD_PROP_PREFIX) : -len(_ACTION_SUFFIX)]
    return None


def _cta_uri(action: str) -> str:
    return f"{_CTA_PREFIX}{action}{_ACTION_SUFFIX}"


def _parse_cta(uri: str | None) -> str | None:
    """The create action of a call-to-action leaf sentinel, else None."""
    if uri and uri.startswith(_CTA_PREFIX) and uri.endswith(_ACTION_SUFFIX):
        return uri[len(_CTA_PREFIX) : -len(_ACTION_SUFFIX)]
    return None


def _nav_hint(context: str | None) -> str:
    """The border hint for a navigation layer ('panel' / 'item' / 'detail'), or '' for none."""
    return _NAV_HINTS.get(context or "", "")
