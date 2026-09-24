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
    body = json.dumps({"overview": {"file": "/tax.ttl"}}).encode()
    with patch("urllib.request.urlopen", return_value=_FakeResponse(body)) as urlopen:
        overview = cli._publish._probe_server_session("http://127.0.0.1:8765", "tok")

    assert overview == {"file": "/tax.ttl"}
    request = urlopen.call_args.args[0]
    assert request.full_url == "http://127.0.0.1:8765/api/session"
    assert request.headers["Authorization"] == "Bearer tok"


def test_probe_returns_none_when_the_port_holder_is_not_ster():
    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        assert cli._publish._probe_server_session("http://127.0.0.1:8765", "tok") is None


def test_probe_returns_none_on_a_malformed_body():
    with patch("urllib.request.urlopen", return_value=_FakeResponse(b"not json")):
        assert cli._publish._probe_server_session("http://127.0.0.1:8765", "tok") is None


def test_probe_returns_none_when_overview_is_missing_or_not_an_object():
    body = json.dumps({"focused": None}).encode()
    with patch("urllib.request.urlopen", return_value=_FakeResponse(body)):
        assert cli._publish._probe_server_session("http://127.0.0.1:8765", "tok") is None


def test_report_unavailable_prints_the_shared_reason(monkeypatch):
    import ster.viz_vowl as viz

    monkeypatch.setattr(viz, "unavailable_reason", lambda host, port: f"{host}:{port} is stuck")

    with cli._app.err.capture() as captured:
        cli._publish._report_unavailable("127.0.0.1", 8765)

    assert "127.0.0.1:8765 is stuck" in captured.get()


def _conflict(monkeypatch, *, served: str | None, holder_kind: str, confirm: bool, freed: bool):
    """Wire the collaborators _resolve_port_conflict reads, and call it once."""
    import ster.api_server as api_server
    import ster.viz_vowl as viz

    monkeypatch.setattr(api_server, "load_token", lambda: "tok")
    monkeypatch.setattr(
        cli._publish,
        "_probe_server_session",
        lambda *_a, **_kw: {"file": served} if served is not None else None,
    )
    monkeypatch.setattr(viz, "holder_kind", lambda _command: holder_kind)
    monkeypatch.setattr(viz, "free_port", lambda *_a, **_kw: freed)
    with patch("rich.prompt.Confirm.ask", return_value=confirm):
        return cli._publish._resolve_port_conflict(
            Path("/project/tax.ttl"),
            (321, "ster serve tax.ttl"),
            "http://127.0.0.1:8765",
            "127.0.0.1",
            8765,
        )


def test_a_healthy_server_already_on_the_requested_file_is_reused(monkeypatch):
    with cli.console.capture() as captured:
        result = _conflict(
            monkeypatch,
            served=str(Path("/project/tax.ttl").resolve()),
            holder_kind="server",
            confirm=False,
            freed=False,
        )

    assert result == "http://127.0.0.1:8765"
    assert "reusing" in captured.get()
    assert "tax.ttl" in captured.get()


def test_a_holder_that_does_not_answer_as_ster_is_left_alone(monkeypatch):
    reported: list[tuple[str, int]] = []
    monkeypatch.setattr(
        cli._publish, "_report_unavailable", lambda host, port: reported.append((host, port))
    )

    result = _conflict(monkeypatch, served=None, holder_kind="foreign", confirm=True, freed=True)

    assert result is None
    assert reported == [("127.0.0.1", 8765)]


def test_a_foreign_process_on_a_different_file_is_never_offered_a_restart(monkeypatch):
    """holder_kind FOREIGN (or EDITOR) must not even reach the confirm prompt —
    restarting someone's open TUI or an unrelated process is never ours to do."""
    reported: list[tuple[str, int]] = []
    monkeypatch.setattr(
        cli._publish, "_report_unavailable", lambda host, port: reported.append((host, port))
    )

    with patch("rich.prompt.Confirm.ask") as confirm_ask:
        result = _conflict(
            monkeypatch, served="/other.ttl", holder_kind="editor", confirm=True, freed=True
        )
    confirm_ask.assert_not_called()

    assert result is None
    assert reported == [("127.0.0.1", 8765)]


def test_declining_the_restart_leaves_the_other_server_running(monkeypatch):
    import ster.viz_vowl as viz

    freed_calls: list[int] = []
    monkeypatch.setattr(viz, "free_port", lambda pid, *_a, **_kw: freed_calls.append(pid) or True)

    result = _conflict(
        monkeypatch, served="/other.ttl", holder_kind="server", confirm=False, freed=True
    )

    assert result is None
    assert freed_calls == []  # never even tried — the user said no


def test_accepting_the_restart_frees_the_port_then_signals_a_fresh_start(monkeypatch):
    result = _conflict(
        monkeypatch, served="/other.ttl", holder_kind="server", confirm=True, freed=True
    )

    assert result is cli._publish._PORT_FREED


def test_a_restart_that_fails_to_free_the_port_gives_up(monkeypatch):
    result = _conflict(
        monkeypatch, served="/other.ttl", holder_kind="server", confirm=True, freed=False
    )

    assert result is None
