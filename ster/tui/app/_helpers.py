"""Module-level helper functions for the TUI app: the API-server bridge
(best-effort context publishing for MCP), the codec functions for tree-node
``data`` sentinels (property-header "add" prefixes, call-to-action leaf
prefixes), and the panel-layer navigation hint text.
"""

from __future__ import annotations

from pathlib import Path

from ster.model import Taxonomy

from ._constants import _ACTION_SUFFIX, _ADD_PROP_PREFIX, _CTA_PREFIX, _NAV_HINTS

FALLBACK_PORTS = 9  # next ports a second ster may take when the configured one is held by another


def _start_context_server(taxonomy: Taxonomy, path: Path | None) -> bool:
    """Bring up the API server so agents can reach the MCP endpoint.

    Runs on a daemon thread beside the TUI. Best-effort: it must never stop the
    editor from opening. When the configured port is held by another ster (a
    second instance, say), this one takes the next free port, so it has a
    server of its own and the agent page it opens follows its own graph, not the
    other instance's. A ``ster serve`` of this very file is the exception: it
    already is the server, and a second one would only split the traffic. No
    HTML renderer is supplied; opening the graph viewer later attaches the VOWL
    one to this same server.
    """
    try:
        from ...api_server import start_background  # noqa: PLC0415

        if start_background(taxonomy, path):
            return True
        if _served_by_same_file(path):
            return False
        return start_background(taxonomy, path, fallback_ports=FALLBACK_PORTS)
    except Exception:  # noqa: BLE001 — the editor must open regardless
        return False


def _served_by_same_file(path: Path | None) -> bool:
    """True when a ``ster serve`` of *path* (same build) already holds the port: the claim that would reuse it."""
    try:
        from ...viz_vowl import claim_port  # noqa: PLC0415
        from ...viz_vowl._claim import REUSE  # noqa: PLC0415

        return bool(claim_port(path, confirm=lambda _question: False).outcome == REUSE)
    except Exception:  # noqa: BLE001 — a probe must never be the thing that fails
        return False


def _moved_notice() -> tuple[str, str] | None:
    """The toast for a server that started on another port than the configured one, else None."""
    from ...api_server import bound_port, configured_server  # noqa: PLC0415

    bound, wanted = bound_port(), configured_server()[1]
    if bound is None or bound == wanted:
        return None
    return (
        f"MCP and the agent page use port {bound} here: {wanted} is held by another ster. "
        f"An agent configured for {wanted} reaches that one.",
        "information",
    )


def _context_server_notice(started: bool, path: Path | None) -> tuple[str, str] | None:
    """The one toast to show when the TUI's own server did not start, as
    ``(message, severity)``; None when nothing needs saying.

    Without it a held port silently means no MCP. The port is only *looked at*
    here: the claim is made with a confirm that always declines, so nothing is
    ever closed from a startup path. A same-file, same-build ``ster serve`` is
    fine and is named as the server in use; anything else is a warning that
    names the holder. A free port that still would not start is not a port
    problem, so it gets no toast.
    """
    if started:
        return _moved_notice()
    try:
        from ...viz_vowl import claim_port  # noqa: PLC0415
        from ...viz_vowl._claim import BLOCKED, REUSE  # noqa: PLC0415

        claim = claim_port(path, confirm=lambda _question: False)
    except Exception:  # noqa: BLE001 — a notice must never be the thing that fails
        return None
    if claim.outcome == REUSE:
        return (
            f"MCP and the graph are served by another ster process at {claim.url}.",
            "information",
        )
    if claim.outcome == BLOCKED:
        return (f"MCP is off: {claim.message}", "warning")
    return None


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
