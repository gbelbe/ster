"""The update prompt fires only when PyPI is genuinely ahead.

`_newer` split a version on dots and called int() on every part, so a local
build — 0.22.1.dev14+g3c6ac5c3a — raised on "dev14+g3c6ac5c3a" and fell back to
(0,). Every PyPI release then compared as newer, and anyone working from a
checkout was told on each launch to "upgrade" to a version years behind their
own. On a private repo that publishes to PyPI only occasionally, that prompt is
wrong on every single launch.

PEP 440 gets the cases that matter: a dev build is ahead of an older release and
behind its own final — which is exactly when its owner should hear about one.
"""

from __future__ import annotations

import pytest

from ster.cli._app import _newer


@pytest.mark.parametrize(
    ("pypi", "local"),
    [
        ("0.10.0", "0.22.1.dev14+g3c6ac5c3a"),  # the reported case
        ("0.10.0", "0.22.1"),
        ("0.22.1.dev1+gabc", "0.22.1"),  # a dev build is behind its own final
        ("0.22.1", "0.22.1"),
    ],
)
def test_no_prompt_when_pypi_is_not_ahead(pypi, local):
    assert _newer(pypi, local) is False


@pytest.mark.parametrize(
    ("pypi", "local"),
    [
        ("0.23.0", "0.22.1.dev14+gabc"),
        ("0.22.1", "0.22.1.dev14+gabc"),  # the release your dev build precedes
        ("1.0.0", "0.22.1"),
    ],
)
def test_prompt_when_pypi_really_is_ahead(pypi, local):
    assert _newer(pypi, local) is True


def test_an_unparseable_version_is_not_grounds_for_nagging():
    assert _newer("not-a-version", "0.1.0") is False
    assert _newer("0.1.0", "not-a-version") is False
