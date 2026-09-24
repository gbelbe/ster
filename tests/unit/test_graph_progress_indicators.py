"""The full-page spinner, shown while the graph is being built.

Before it existed the page was simply blank for the seconds a large ontology
spends parsing its payload and running fcose — indistinguishable from a page
that had failed. There is nothing to interact with yet, so veiling is right
here; the lighter #busy indicator covers work that happens while you keep
working.

Verified live under a 12x CPU throttle: it appeared at t+1.3s and came down at
t+36.1s when the layout settled.
"""

from __future__ import annotations

from ster.viz_vowl import _app_js
from ster.viz_vowl._html_template import _HTML_TEMPLATE


def _js() -> str:
    return _app_js().replace(" ", "").replace("\n", "")


def test_the_page_is_veiled_from_first_paint():
    """Not added by script: markup that arrives already showing is the only
    version that covers the seconds before the script itself has parsed."""
    assert '<div id="graph-spinner">' in _HTML_TEMPLATE
    assert "hidden" not in _HTML_TEMPLATE.split('<div id="graph-spinner">')[1][:40]


def test_the_veil_lifts_when_the_first_layout_settles():
    assert "l.one('layoutstop',()=>{_saveLayout();hideSpinner();});" in _js()


def test_the_veil_lifts_immediately_when_positions_were_restored():
    """There was no layout to wait for, so waiting for one would hang it
    behind the veil for the full 20-second backstop."""
    assert "if(newcomers.empty()){cy.fit(undefined,30);hideSpinner();return;}" in _js()


def test_the_veil_cannot_outlast_a_layout_that_never_reports():
    """fcose does not always emit layoutstop."""
    assert "setTimeout(hideSpinner,20000);" in _js()


def test_show_all_raises_the_veil_before_it_navigates():
    """The unscoped graph is the slowest thing the view can be asked for; the
    button used to appear to do nothing for several seconds."""
    from ster.viz_vowl._render import _SHOW_ALL_BTN_HTML

    assert "showSpinner" in _SHOW_ALL_BTN_HTML
