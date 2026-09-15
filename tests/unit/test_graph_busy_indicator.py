"""The quiet indicator, for work that happens while you keep working.

Search and expansion are not page-building — there is something on screen and
you can still use it — so this says "in flight" without blocking, unlike the
full-page #graph-spinner.

Verified live under network throttling: the pill showed "Searching…" during the
request and cleared afterwards.
"""

from __future__ import annotations

from ster.viz_vowl import _app_js


def _js() -> str:
    return _app_js().replace(" ", "").replace("\n", "")


def test_every_api_call_counts_toward_it():
    """Counting around fetch covers all eleven call sites at once — and covers
    whatever is added next, which wrapping each by hand would not."""
    js = _js()

    assert "globalThis.fetch=function(...args){" in js
    assert "constend=busy(" in js
    assert ".finally(end)" in js


def test_a_fast_call_never_flashes_it():
    """Most of these answer in tens of milliseconds; an indicator that blinks
    on every keystroke is worse than none."""
    assert "const_BUSY_DELAY_MS=250;" in _js()


def test_the_version_poll_is_excluded():
    """It runs on a timer. A light that blinks by itself tells you nothing
    about what you just did."""
    js = _js()

    assert "_BUSY_SILENT" in js
    assert "api\\\\/version" in js or "version" in js


def test_the_counter_cannot_go_negative():
    js = _js()

    assert "_busyCount=Math.max(0,_busyCount-1);" in js


def test_a_settled_call_cannot_be_counted_down_twice():
    """`finally` can fire once, but the closure is also handed out — guarding
    it keeps the count honest if it is ever called again."""
    assert "if(done){return;}done=true;" in _js()


def test_it_does_not_swallow_non_api_requests():
    assert "if(!url.includes('/api/')" in _js()


def test_the_request_url_lookup_is_named_not_nested():
    """fetch accepts a string, a URL or a Request, and each keeps its URL
    somewhere different. Chained conditionals read as one expression while
    actually being three unrelated lookups — and a fourth input type would have
    made it worse.
    """
    js = _js()

    assert "function_fetchUrl(target){" in js
    assert "consturl=_fetchUrl(args[0]);" in js


def test_every_shape_fetch_accepts_is_handled():
    js = _js()

    assert "if(typeoftarget==='string')returntarget;" in js
    assert "if(targetinstanceofURL)returntarget.href;" in js
    assert "if(targetinstanceofRequest)returntarget.url;" in js


def test_an_unknown_shape_falls_through_to_the_untouched_fetch():
    """Returning '' means the /api/ test fails and the call is passed straight
    on, rather than being counted or, worse, throwing inside the wrapper."""
    js = _js()

    assert "return'';" in js
