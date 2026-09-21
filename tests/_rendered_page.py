"""Reading a rendered ster page back, for the tests that check what it emits.

Shared because both the map and the timeline page need it, identically, and a
fourth view would have made a third copy. That duplication had a cost beyond
tidiness: the extraction lived twice, so every fix to it had to be found twice.
"""

from __future__ import annotations

import html5lib


def inline_scripts(page: str) -> list[str]:
    """Every inline script in *page*, in document order.

    Parsed rather than matched. Three rounds of CodeQL on the regex this
    replaces — upper-case `<SCRIPT>`, then `</script >`, then
    `</script\t\n bar>` — each fixed the one variant it named and left the
    next. That is the shape of a losing game: HTML end tags accept arbitrary
    whitespace *and* ignored attributes, so a pattern is always one quirk from
    silently matching nothing. And silence is the danger here: the test does not
    fail, it passes while checking no code at all.

    html5lib follows the spec, so the question stops being "which spellings did
    we remember" and becomes "what does a browser see" — which is the question
    these tests were always asking.
    """
    document = html5lib.parse(page, namespaceHTMLElements=False)
    return [
        element.text
        for element in document.iter("script")
        if not element.get("src") and element.text
    ]


def main_inline_script(page: str, what: str) -> str:
    """The largest inline script in *page* — the page's own generated code.

    *what* names the page in the failure message: "carries no inline script" is
    only useful if it says which page did not.
    """
    blocks = inline_scripts(page)
    assert blocks, f"the {what} page carries no inline script"
    return max(blocks, key=len)
