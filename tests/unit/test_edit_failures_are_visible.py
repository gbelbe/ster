"""A refused edit tells the user why, and a stale one is refused at all.

Two gaps in the panel's editing, both invisible rather than loud:

  * Removing a relation caught its error into ``console.debug``. The × button
    re-enabled itself, the relation stayed on screen, and nothing said why —
    which reads as a broken button rather than a refused edit. The add forms
    beside it had always shown the server's message.
  * Every edit was sent with no version, so ``TaxonomyService``'s stale-read
    check short-circuited and the last writer won silently.

Structural assertions on graph_app.js's source, per the project's established
pattern for JS behaviour it cannot drive through a browser.
"""

from __future__ import annotations

from ster.viz_vowl import _app_js


def _remove_btn() -> str:
    js = _app_js()
    start = js.index("function _relationRemoveBtn(")
    return js[start : js.index("\n}", start)]


def test_a_refused_removal_reaches_the_user_not_the_console():
    body = _remove_btn()

    assert "console.debug" not in body, "the removal error is still being swallowed"
    assert "errEl.textContent" in body


def test_the_removal_error_shows_what_the_server_said():
    """_postJson already unwraps FastAPI's `detail`; it must not be discarded."""
    assert "err.message" in _remove_btn()


def test_the_remove_button_is_re_enabled_so_the_user_can_retry():
    assert "btn.disabled=false" in _remove_btn()


def test_every_relation_row_carries_its_own_error_line():
    """One shared element would show a failure against the wrong relation."""
    js = _app_js()
    start = js.index("function detailRelationsNodes(")
    body = js[start : js.index("\n}", start)]

    assert "const relErr=" in body
    assert body.count("relErr))") == 2, "both remove call sites must pass the error element"


def test_edits_carry_the_version_they_were_built_on():
    js = _app_js()

    assert "base_version:_docVersion" in js.replace(" ", "")


def test_the_version_is_read_from_the_api_at_startup():
    js = _app_js()

    assert "/api/version" in js
    assert "_initDocVersion()" in js


def test_a_session_with_no_version_still_edits():
    """Read-only or pre-fetch, a null version must mean "no check", not a crash."""
    js = _app_js().replace(" ", "")

    assert "_docVersion===null?body:" in js


def test_a_conflict_tells_the_user_to_reload():
    js = _app_js()

    assert "r.status===409" in js.replace(" ", "")
    assert "Reload the page" in js
