"""The shared inline-script reader, and the spellings a regex kept missing.

CodeQL flagged the original pattern three times as a bad HTML filter
(py/bad-tag-filter) — upper-case `<SCRIPT>`, then `</script >`, then
`</script\t\n bar>`. Each fix handled the variant named and left the next,
which is how you know the approach is wrong rather than incomplete: HTML end
tags take arbitrary whitespace *and* ignored attributes.

The danger is specifically silence. A pattern that stops matching does not
fail; the test passes while checking no code at all. So these cases are kept as
tests even though a spec parser now makes them uninteresting — they are the
record of what went wrong.
"""

from __future__ import annotations

from tests._rendered_page import inline_scripts, main_inline_script


def test_an_upper_case_script_tag_is_still_found():
    """The failure CodeQL named: silently matching nothing."""
    assert inline_scripts("<SCRIPT>let a=1;</SCRIPT>") == ["let a=1;"]


def test_mixed_case_too():
    assert inline_scripts("<Script>let a=1;</Script>") == ["let a=1;"]


def test_a_sourced_script_is_not_inline():
    """A `src` block is a library the page loads, not code the page generated —
    parsing a vendored bundle is not what these tests are for."""
    assert inline_scripts('<script src="cytoscape.js"></script>') == []


def test_attributes_do_not_prevent_a_match():
    assert inline_scripts('<script type="module">let a=1;</script>') == ["let a=1;"]


def test_blocks_come_back_in_document_order():
    page = "<script>first</script><script>second</script>"

    assert inline_scripts(page) == ["first", "second"]


def test_the_main_script_is_the_largest():
    """Pages carry small bootstrap blocks alongside the generated code; the
    interesting one is the big one."""
    page = "<script>let a=1;</script><script>let bbbbbbbbbb=2;</script>"

    assert main_inline_script(page, "test") == "let bbbbbbbbbb=2;"


def test_a_page_with_no_inline_script_says_which_page():
    """The assertion message is the whole value of the wrapper when it fails."""
    try:
        main_inline_script("<html></html>", "timeline")
    except AssertionError as exc:
        assert "timeline" in str(exc)
    else:
        raise AssertionError("expected an AssertionError")


def test_a_spaced_closing_tag_is_still_the_end_of_the_script():
    """HTML permits `</script >`, and CodeQL names it specifically. Same
    failure mode as the case one: the pattern stops matching and the test
    passes while checking nothing."""
    assert inline_scripts("<script>let a=1;</script >") == ["let a=1;"]
    assert inline_scripts("<script>let a=1;</script\t>") == ["let a=1;"]


def test_the_variant_that_finally_forced_a_parser():
    """`</script\t\n bar>`: HTML end tags accept whitespace and then ignored
    attributes. No regex anyone wrote by hand caught this one, and CodeQL was
    right to keep asking."""
    assert inline_scripts("<script>let a=1;</script\t\n bar>") == ["let a=1;"]
