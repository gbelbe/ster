"""A page notices when the server under it has been replaced by another build.

"I updated ster and the graph view is still old" was true and had two causes.
One was a second install serving its own build (#209 put the build on the page
so that is now visible). The other is this: a tab left open while ster is updated
and restarted keeps showing the previous build's output, which looks perfectly
fine and is not.

The page bakes in the build that drew it; /api/version reports the build
answering now. Different means stale.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from ster import store
from ster._version import __version__
from ster.api import SSEBroadcaster, create_app
from ster.viz_vowl import _app_js
from ster.viz_vowl._html_template import _HTML_TEMPLATE

TOKEN = "T"


def _js() -> str:
    return _app_js().replace(" ", "").replace("\n", "")


def _client() -> TestClient:
    taxonomy = store.load("ster/tui/demo.ttl")
    return TestClient(create_app(taxonomy, TOKEN, SSEBroadcaster(), lambda _t: None))


def test_the_version_endpoint_reports_the_build():
    response = _client().get("/api/version", headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.json()["ster"] == __version__


def test_it_reports_the_build_on_a_read_only_session_too():
    """A read-only session still wants to know its page is stale."""
    body = _client().get("/api/version", headers={"Authorization": f"Bearer {TOKEN}"}).json()

    assert body["editable"] is False
    assert body["ster"] == __version__


def test_the_page_compares_the_build_it_was_drawn_by():
    js = _js()

    assert "globalThis.__STER_GRAPH__.sterVersion" in js
    assert "if(d?.ster&&d.ster!==mine)_showStaleBuild(mine,d.ster);" in js


def test_the_check_repeats_because_the_swap_happens_after_load():
    """Checked once at load it could never fire: the server is replaced later,
    or there would be nothing to notice."""
    js = _js()

    assert "const_BUILD_CHECK_MS=30000;" in js
    assert "setInterval(" in js


def test_a_session_that_cannot_ask_does_not_pretend_to_know():
    """No token, no check — and no false reassurance either.

    Asserted on this function's own guard rather than on the bare string
    `if(!API_TOKEN)return;`, which appears elsewhere in the file: after the
    guards were folded together that assertion still passed while testing
    somebody else's line.
    """
    js = _js()

    assert "constmine=API_TOKEN&&globalThis.__STER_GRAPH__.sterVersion;" in js
    assert "if(!mine)return;" in js


def test_the_banner_offers_the_fix_rather_than_only_the_news():
    assert '<div id="stale">' in _HTML_TEMPLATE
    assert 'id="stale-reload"' in _HTML_TEMPLATE
    assert "location.reload()" in _app_js()


def test_the_banner_is_hidden_until_it_has_something_to_say():
    assert "#stale{" in _HTML_TEMPLATE
    assert "display:none" in _HTML_TEMPLATE.split("#stale{")[1][:200]
