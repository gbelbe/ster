"""Link validation shared by the detail renderer (open a link) and the editors
(create / update a value): a malformed Markdown link is caught instead of the
misleading "Opening link…" that ``webbrowser.open`` produces on a broken URL.
"""

from __future__ import annotations

from ster.tui.urls import is_openable_url, link_kind, malformed_markdown_links


def test_openable_urls_are_web_links() -> None:
    for good in (
        "http://example.org",
        "https://example.org/path?q=1#frag",
        "https://sub.domain.co.uk",
        "mailto:alice@example.org",
    ):
        assert is_openable_url(good), good
        assert link_kind(good) == "web"


def test_malformed_urls_are_rejected() -> None:
    for bad in (
        "example.org",  # no scheme
        "htp://typo.example",  # typo'd scheme
        "http://",  # no host
        "https://",  # no host
        "javascript:alert(1)",  # unsupported / unsafe scheme
        "file:///etc/passwd",  # not a web link
        "just some text",
        "",
        "ftp://example.org",  # not in the openable set
    ):
        assert not is_openable_url(bad), bad
        assert link_kind(bad) == "malformed", bad


def test_urn_is_a_valid_identifier_not_malformed() -> None:
    """ster auto-links URNs; they are valid but not browser-openable — never 'malformed'."""
    assert link_kind("urn:isbn:9780306406157") == "urn"
    assert not is_openable_url("urn:isbn:9780306406157")
    assert malformed_markdown_links("see [book](urn:isbn:123)") == []


def test_malformed_markdown_links_flags_only_broken_targets() -> None:
    text = (
        "ok [site](https://example.org), "
        "id [ref](urn:x:1), "
        "broken [oops](htp://nope) and [rel](/local/path)"
    )
    assert malformed_markdown_links(text) == ["htp://nope", "/local/path"]


def test_value_without_markdown_links_is_clean() -> None:
    assert malformed_markdown_links("a plain comment with no links") == []
    # a bare URL (not [text](url) syntax) isn't inspected here — autolinking handles it
    assert malformed_markdown_links("a bare https://example.org on its own") == []


# ── integration: the two consumers (open a link, create/update a value) ─────────

import asyncio  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import patch  # noqa: E402

import pytest  # noqa: E402

from ster import store  # noqa: E402
from ster.tui.app import OntologyApp  # noqa: E402

DEMO = Path(__file__).resolve().parents[2] / "ster" / "tui" / "demo.ttl"


@pytest.fixture(autouse=True)
def _isolate_prefs(tmp_path, monkeypatch):
    from ster import api_server
    from ster.nav import prefs

    monkeypatch.setattr(prefs, "_prefs_path", lambda: tmp_path / "prefs.json")
    monkeypatch.setattr(api_server, "_SERVER_CONFIG_FILE", tmp_path / "server_config.json")
    monkeypatch.setattr(api_server, "_TOKEN_FILE", tmp_path / "api_token")


def test_clicking_a_link_errors_on_malformed_and_opens_a_web_link() -> None:
    """Regression: a malformed link showed "Opening link…" but opened nothing. Now it
    errors; a URN is surfaced (not opened); a real web link opens."""

    async def scenario() -> None:
        from ster.tui.detail_view import DetailRow

        app = OntologyApp(store.load(DEMO), source="demo.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            row = next(iter(app.query(DetailRow)))
            calls: list = []
            app.notify = lambda *a, **k: calls.append((a, k))  # type: ignore[method-assign]

            with patch("ster.tui.detail_view.webbrowser.open") as wb:
                row._open_link("htp://typo.nope")  # malformed
            wb.assert_not_called()
            assert calls[-1][1].get("severity") == "error"

            calls.clear()
            with patch("ster.tui.detail_view.webbrowser.open") as wb:
                row._open_link("urn:isbn:9780306406157")  # valid identifier, not openable
            wb.assert_not_called()
            assert calls[-1][1].get("severity") is None  # info toast, not an error

            calls.clear()
            with patch("ster.tui.detail_view.webbrowser.open", return_value=True) as wb:
                row._open_link("https://example.org")  # real web link → opens
            wb.assert_called_once()

    asyncio.run(scenario())


def test_editing_a_value_warns_about_a_malformed_link() -> None:
    async def scenario() -> None:
        app = OntologyApp(store.load(DEMO), source="demo.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            calls: list = []
            app.notify = lambda *a, **k: calls.append((a, k))  # type: ignore[method-assign]

            app._warn_malformed_links("see [oops](htp://broken)")  # malformed → warn
            assert calls[-1][1].get("severity") == "warning"

            calls.clear()
            app._warn_malformed_links("[site](https://ok.org) and [id](urn:x:1)")  # all valid
            assert calls == []  # no warning

    asyncio.run(scenario())
