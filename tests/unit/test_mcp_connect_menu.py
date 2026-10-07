"""The home menu's "Connect AI Agent (MCP)" entry.

The endpoint only exists while the server runs and its token is generated per
install, so the friction is never the protocol — it is finding the URL and the
bearer token. The menu starts the server, prints both, and copies the endpoint.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from ster import cli
from ster.viz_vowl._claim import server_overview


def test_endpoint_is_the_mcp_path_on_the_running_server():
    endpoint, _snippet = cli._publish.mcp_connection_info("http://127.0.0.1:8765", "tok")

    assert endpoint == "http://127.0.0.1:8765/mcp"


def test_endpoint_does_not_double_the_slash():
    endpoint, _snippet = cli._publish.mcp_connection_info("http://127.0.0.1:8765/", "tok")

    assert endpoint == "http://127.0.0.1:8765/mcp"


def test_snippet_is_the_vendor_neutral_mcp_servers_object():
    """Every MCP-capable client reads this shape; nothing here is Claude-specific."""
    _endpoint, snippet = cli._publish.mcp_connection_info("http://127.0.0.1:8765", "tok")

    config = json.loads(snippet)

    assert config["mcpServers"]["ster"] == {
        "type": "http",
        "url": "http://127.0.0.1:8765/mcp",
        "headers": {"Authorization": "Bearer tok"},
    }


def test_snippet_carries_the_live_token():
    """The token is per-install, so a copied snippet has to be usable as-is."""
    _endpoint, snippet = cli._publish.mcp_connection_info("http://127.0.0.1:8765", "secret-value")

    assert "Bearer secret-value" in snippet


def test_menu_offers_the_mcp_entry():
    labels = [label for _sentinel, label in cli._workspace_ui._home_actions()]

    assert any("MCP" in label for label in labels)


def test_menu_row_uses_the_mcp_sentinel():
    sentinels = [s for s, _label in cli._workspace_ui._home_actions()]

    assert cli._constants._MCP_SENTINEL in sentinels


def test_mcp_sentinel_is_wired_to_a_handler():
    """A sentinel with no handler falls silently through to the open-file path.

    The dispatch table is local to _handle_home_action, so this reads the
    source rather than the dict — enough to catch the row being added without
    its handler, which is the mistake worth guarding.
    """
    import inspect

    source = inspect.getsource(cli._query_launcher)

    assert "_MCP_SENTINEL: _publish._run_mcp_connect_interactive" in source
    assert callable(cli._publish._run_mcp_connect_interactive)


# ── what the menu actually prints ─────────────────────────────────────────────
#
# The endpoint, token and snippet are the whole point of the entry, so the output
# is asserted rather than left to a `# pragma: no cover`.


def _printed(*, copied: bool) -> str:
    endpoint, snippet = cli._publish.mcp_connection_info("http://127.0.0.1:8765", "tok-xyz")
    with cli.console.capture() as captured:
        cli._publish._print_mcp_connection(endpoint, "tok-xyz", snippet, copied)
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


# ── the example command has to survive a copy-paste ───────────────────────────


def test_no_markup_tag_leaks_into_the_output():
    """Regression: the reader saw a literal "[/dim]" in the command.

    Rich treats ``\\[`` as the escape for a literal bracket. The example command
    ends in a shell line-continuation backslash, which landed immediately before
    ``[/dim]`` — so Rich read the pair as "print a [", swallowed the backslash and
    emitted the closing tag as text.
    """
    out = _printed(copied=True)

    for tag in ("[/dim]", "[dim]", "[/bold]", "[bold]", "[/cyan]", "[cyan]"):
        assert tag not in out, f"unrendered markup in output: {tag}"


def test_the_example_command_keeps_its_line_continuation():
    """Without the trailing backslash the two printed lines are two broken commands."""
    out = _printed(copied=True)

    command_line = next(line for line in out.splitlines() if "claude mcp add" in line)
    assert command_line.rstrip().endswith("\\"), command_line


def test_the_example_command_pastes_as_one_runnable_line():
    """Join on the continuation and the result must be the command we meant to show."""
    out = _printed(copied=True)
    lines = out.splitlines()
    start = next(i for i, line in enumerate(lines) if "claude mcp add" in line)
    joined = " ".join(line.strip().rstrip("\\").strip() for line in lines[start : start + 2])

    assert joined == (
        "claude mcp add --transport http ster http://127.0.0.1:8765/mcp "
        '--header "Authorization: Bearer $(cat ~/.config/ster/api_token)"'
    )


# ── the reader gets a chance to actually use what was printed ─────────────────


def test_the_menu_waits_before_redrawing_over_the_output():
    """Regression: the endpoint scrolled away before it could be read.

    Returning to the home menu reprints an 18-line banner and a 12-line action
    list right after these 25 lines, so on any terminal under 55 rows the whole
    thing was off-screen by the time the user looked at it.
    """
    prompted: list[str] = []

    cli._publish._pause_until_acknowledged(read=lambda msg: prompted.append(msg), is_tty=True)

    assert prompted, "must wait for the reader before the menu redraws"


def test_the_pause_is_skipped_when_there_is_no_terminal():
    """A piped or scripted run has nobody to press Enter — waiting would hang it."""
    prompted: list[str] = []

    cli._publish._pause_until_acknowledged(read=lambda msg: prompted.append(msg), is_tty=False)

    assert not prompted


def test_the_pause_survives_a_closed_stdin():
    """Ctrl-D at the prompt should return to the menu, not raise through the loop."""

    def closed(_msg: str) -> str:
        raise EOFError

    cli._publish._pause_until_acknowledged(read=closed, is_tty=True)  # must not raise


# ── reusing (or restarting) a server that already holds the port ──────────────
#
# A stray ster process — an earlier `ster serve`, or a previous interactive
# session that never exited — can already be bound to the configured port by
# the time "Connect AI Agent" runs. These cover how that is detected and
# handled, without needing a real second process or a real HTTP server.


class _FakeResponse:
    """A context-manager stand-in for ``urllib.request.urlopen``'s return value."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._payload


def test_probe_reads_the_overview_from_a_healthy_server():
    body = json.dumps({"file": "/tax.ttl"}).encode()
    with patch("urllib.request.urlopen", return_value=_FakeResponse(body)) as urlopen:
        overview = server_overview("http://127.0.0.1:8765", "tok")

    assert overview == {"file": "/tax.ttl"}
    request = urlopen.call_args.args[0]
    assert request.full_url == "http://127.0.0.1:8765/api/overview"
    assert request.headers["Authorization"] == "Bearer tok"


def test_probe_returns_none_when_the_port_holder_is_not_ster():
    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        assert server_overview("http://127.0.0.1:8765", "tok") is None


def test_probe_returns_none_when_the_connection_is_refused_as_a_urlerror():
    """urlopen raises URLError (an OSError) for a refused connection — still None."""
    import urllib.error

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        assert server_overview("http://127.0.0.1:8765", "tok") is None


def test_probe_returns_none_on_a_malformed_body():
    with patch("urllib.request.urlopen", return_value=_FakeResponse(b"not json")):
        assert server_overview("http://127.0.0.1:8765", "tok") is None


def test_probe_returns_none_when_the_body_is_not_an_object():
    body = json.dumps(["not", "an", "object"]).encode()
    with patch("urllib.request.urlopen", return_value=_FakeResponse(body)):
        assert server_overview("http://127.0.0.1:8765", "tok") is None


def test_report_unavailable_prints_the_shared_reason(monkeypatch):
    import ster.viz_vowl as viz

    monkeypatch.setattr(viz, "unavailable_reason", lambda host, port: f"{host}:{port} is stuck")

    with cli._app.err.capture() as captured:
        cli._publish._report_unavailable("127.0.0.1", 8765)

    assert "127.0.0.1:8765 is stuck" in captured.get()


def _conflict(monkeypatch, claim):
    """Stub claim_port with *claim* and call _resolve_port_conflict once.

    Returns ``(result, confirm_passed)`` — the confirm callable the CLI handed
    to claim_port, which is how "ask first" is wired.
    """
    import ster.viz_vowl as viz

    seen: list = []

    def _claim(taxonomy_file, confirm=None, host=None, port=None):
        seen.append(confirm)
        return claim

    monkeypatch.setattr(viz, "claim_port", _claim)
    result = cli._publish._resolve_port_conflict(
        Path("/project/tax.ttl"), "http://127.0.0.1:8765", "127.0.0.1", 8765
    )
    return result, seen[0]


def test_a_healthy_server_already_on_the_requested_file_is_reused(monkeypatch):
    from ster.viz_vowl._claim import REUSE, Claim

    with cli.console.capture() as captured:
        result, _ = _conflict(monkeypatch, Claim(REUSE, url="http://127.0.0.1:8765"))

    assert result == "http://127.0.0.1:8765"
    assert "reusing" in captured.get()
    assert "tax.ttl" in captured.get()


def test_a_blocked_port_prints_the_reason_and_gives_up(monkeypatch):
    from ster.viz_vowl._claim import BLOCKED, Claim

    with cli._app.err.capture() as captured:
        result, _ = _conflict(
            monkeypatch, Claim(BLOCKED, "another ster session is open (x) and holds port 8765.")
        )

    assert result is None
    assert "Another ster session is open" in captured.get()


def test_a_usable_port_signals_a_fresh_start(monkeypatch):
    from ster.viz_vowl._claim import FREE, Claim

    result, _ = _conflict(monkeypatch, Claim(FREE))

    assert result is cli._publish._START_FRESH


def test_the_cli_asks_before_replacing_another_server(monkeypatch):
    """Regression: the restart prompt must stay wired through claim_port — it is
    the only thing between `ster connect` and silently closing someone's view."""
    from ster.viz_vowl._claim import FREE, Claim

    _, confirm = _conflict(monkeypatch, Claim(FREE))

    assert confirm is cli._publish._confirm_replace
