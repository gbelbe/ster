"""The home menu's "Connect AI Agent (MCP)" entry.

The endpoint only exists while the server runs and its token is generated per
install, so the friction is never the protocol — it is finding the URL and the
bearer token. The menu starts the server, prints both, and copies the endpoint.
"""

from __future__ import annotations

import json

from ster import cli


def test_endpoint_is_the_mcp_path_on_the_running_server():
    endpoint, _snippet = cli.mcp_connection_info("http://127.0.0.1:8765", "tok")

    assert endpoint == "http://127.0.0.1:8765/mcp"


def test_endpoint_does_not_double_the_slash():
    endpoint, _snippet = cli.mcp_connection_info("http://127.0.0.1:8765/", "tok")

    assert endpoint == "http://127.0.0.1:8765/mcp"


def test_snippet_is_the_vendor_neutral_mcp_servers_object():
    """Every MCP-capable client reads this shape; nothing here is Claude-specific."""
    _endpoint, snippet = cli.mcp_connection_info("http://127.0.0.1:8765", "tok")

    config = json.loads(snippet)

    assert config["mcpServers"]["ster"] == {
        "type": "http",
        "url": "http://127.0.0.1:8765/mcp",
        "headers": {"Authorization": "Bearer tok"},
    }


def test_snippet_carries_the_live_token():
    """The token is per-install, so a copied snippet has to be usable as-is."""
    _endpoint, snippet = cli.mcp_connection_info("http://127.0.0.1:8765", "secret-value")

    assert "Bearer secret-value" in snippet


def test_menu_offers_the_mcp_entry():
    labels = [label for _sentinel, label in cli._home_actions()]

    assert any("MCP" in label for label in labels)


def test_menu_row_uses_the_mcp_sentinel():
    sentinels = [s for s, _label in cli._home_actions()]

    assert cli._MCP_SENTINEL in sentinels


def test_mcp_sentinel_is_wired_to_a_handler():
    """A sentinel with no handler falls silently through to the open-file path.

    The dispatch table is local to _handle_home_action, so this reads the
    source rather than the dict — enough to catch the row being added without
    its handler, which is the mistake worth guarding.
    """
    import inspect

    source = inspect.getsource(cli)

    assert "_MCP_SENTINEL: _run_mcp_connect_interactive" in source
    assert callable(cli._run_mcp_connect_interactive)


# ── what the menu actually prints ─────────────────────────────────────────────
#
# The endpoint, token and snippet are the whole point of the entry, so the output
# is asserted rather than left to a `# pragma: no cover`.


def _printed(*, copied: bool) -> str:
    endpoint, snippet = cli.mcp_connection_info("http://127.0.0.1:8765", "tok-xyz")
    with cli.console.capture() as captured:
        cli._print_mcp_connection(endpoint, "tok-xyz", snippet, copied)
    return captured.get()


def test_output_shows_the_endpoint_and_auth_header():
    out = _printed(copied=True)

    assert "http://127.0.0.1:8765/mcp" in out
    assert "Authorization: Bearer tok-xyz" in out


def test_output_includes_the_config_snippet():
    out = _printed(copied=True)

    assert "mcpServers" in out
    assert '"type": "http"' in out


def test_output_offers_a_client_example_without_privileging_it():
    """`claude mcp add` is shown as one example; the snippet is the general way."""
    out = _printed(copied=True)

    assert "claude mcp add" in out
    assert "MCP-capable" in out


def test_output_confirms_a_successful_copy():
    assert "copied to clipboard" in _printed(copied=True)


def test_output_warns_when_the_clipboard_is_unreachable():
    """Over SSH or on a bare container the copy silently fails; say so."""
    out = _printed(copied=False)

    assert "could not reach the clipboard" in out
    assert "copied to clipboard" not in out
