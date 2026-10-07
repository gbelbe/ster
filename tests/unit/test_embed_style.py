"""The shared helper that hides a page's own chrome when it is shown inside another page."""

from __future__ import annotations

from ster.viz_shared import EMBED_STYLE_ID, embed_style


def test_the_style_hides_every_selector_it_is_given() -> None:
    style = embed_style(("header", "#panel"))
    assert style == '<style id="ster-embed">header,#panel{display:none !important}</style>'


def test_the_style_has_the_id_the_pages_and_tests_look_for() -> None:
    assert EMBED_STYLE_ID == "ster-embed"
    assert f'id="{EMBED_STYLE_ID}"' in embed_style(("header",))


def test_important_so_a_pages_own_rules_cannot_bring_the_chrome_back() -> None:
    assert "!important" in embed_style(("header",))


def test_one_selector_needs_no_comma() -> None:
    assert embed_style(("aside",)).count(",") == 0
