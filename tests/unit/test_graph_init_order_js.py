"""A startup call must not read a `const` the graph app declares further down.

``graph_app.js`` runs top to bottom as one IIFE. A function declaration is
hoisted, so calling one early is fine, but a ``const`` is not: reading it before
its line has run throws a ReferenceError (the temporal dead zone), and the
exception abandons the rest of initialisation.

Root cause of the regression this guards: ``_wireStaleBanner()`` ran at line
~896 and reached ``_BUILD_CHECK_MS``, declared at line ~1730. The build check
only runs when the page is served with an API token, so the exported page was
fine and the TUI's graph view ("g") died on open with
``_watchForNewBuild@…`` in the error overlay.
"""

from __future__ import annotations

import re

from ster.viz_vowl import _app_js

_TOP_LEVEL_CONST = re.compile(r"^const ([A-Za-z_$][\w$]*)=", re.MULTILINE)
_TOP_LEVEL_FUNCTION = re.compile(r"^function ([A-Za-z_$][\w$]*)\(", re.MULTILINE)
_TOP_LEVEL_CALL = re.compile(r"^([A-Za-z_$][\w$]*)\(\);", re.MULTILINE)


def _function_bodies(js: str) -> dict[str, str]:
    """Each column-zero function's source, bounded by the next column-zero brace."""
    return {
        m.group(1): js[m.start() : js.index("\n}", m.start())]
        for m in _TOP_LEVEL_FUNCTION.finditer(js)
    }


def _reads_before_declaration(js: str) -> list[str]:
    """`call → const` pairs where a startup call reads a const declared later.

    Follows calls one level deep plus the functions those call, which is as far
    as the stale-banner chain went (_wireStaleBanner → _watchForNewBuild).
    """
    consts = {m.group(1): m.start() for m in _TOP_LEVEL_CONST.finditer(js)}
    bodies = _function_bodies(js)
    offenders = []
    for call in _TOP_LEVEL_CALL.finditer(js):
        body = bodies.get(call.group(1), "")
        reached = body + "".join(
            bodies[name] for name in bodies if re.search(rf"\b{re.escape(name)}\(", body)
        )
        offenders += [
            f"{call.group(1)}() → {name}"
            for name, declared_at in consts.items()
            if declared_at > call.start() and re.search(rf"\b{re.escape(name)}\b", reached)
        ]
    return offenders


def test_startup_calls_never_read_a_const_declared_later() -> None:
    assert _reads_before_declaration(_app_js()) == []


def test_stale_banner_interval_is_declared_before_it_is_wired_regression() -> None:
    """The specific case that broke the served graph view."""
    js = _app_js()

    assert js.index("const _BUILD_CHECK_MS=") < js.index("\n_wireStaleBanner();")


def test_the_check_catches_a_read_before_declaration() -> None:
    """Guards the general test against passing vacuously."""
    js = "function f(){\n  return g();\n}\nfunction g(){\n  return LATE;\n}\nf();\nconst LATE=1;\n"

    assert _reads_before_declaration(js) == ["f() → LATE"]


def test_the_check_allows_a_const_declared_first() -> None:
    js = "const EARLY=1;\nfunction f(){\n  return EARLY;\n}\nf();\n"

    assert _reads_before_declaration(js) == []
