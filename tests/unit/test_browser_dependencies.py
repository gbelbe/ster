"""Every browser library ster loads is declared, at the version the code pins.

ster ships three kinds of dependency and, until this test, watched one. The
Python tree is in pyproject.toml and scanned by pip-audit in CI. The ten
JavaScript libraries the views load were pinned only in Python constants —
absent from every manifest, so invisible to pip-audit (which reads Python) and
to npm audit (which reads package.json, and they were not in it). A CVE in
Cytoscape or Leaflet would have gone unnoticed until somebody read about it
elsewhere.

package.json is now the manifest of record for them. That only means something
if the two places cannot drift, which is what this test enforces: the version in
package.json and the version in the source must agree, and a library the code
loads must be declared at all. A Dependabot PR bumping package.json therefore
fails here until the constant moves with it — which is the point. The failure is
the reminder.

The URLs are read from the *resolved* module constants rather than by regexing
the source, so an f-string, a split literal and a plain URL are all handled the
same way, and a new spelling cannot slip past the scanner.
"""

from __future__ import annotations

import json
import re
from importlib import import_module
from pathlib import Path

import pytest

# Modules that name a CDN URL, and how they say it: module-level constants
# ending in _CDN, plus page templates that hard-code a <script src>.
_MODULES_WITH_CDN_CONSTANTS = (
    "ster.viz_vowl._js_assets",
    "ster.timeline_html",
)
_MODULES_WITH_INLINE_URLS = ("ster/geo_map_html.py",)

_CDN_HOSTS = ("cdnjs.cloudflare.com", "cdn.jsdelivr.net", "unpkg.com")

# name@version — jsdelivr's /npm/ paths and unpkg's root paths.
_NPM_STYLE = re.compile(
    r"(?:/npm/|unpkg\.com/)(@?[a-z0-9][a-z0-9._-]*(?:/[a-z0-9._-]+)?)@([0-9][^/]*)/"
)
# cdnjs keeps the version in its own path segment.
_CDNJS_STYLE = re.compile(r"/ajax/libs/([a-z0-9][a-z0-9._-]*)/([0-9][^/]*)/")
# Any absolute URL to one of the hosts, already free of format placeholders.
_URL = re.compile(
    r"https://(?:" + "|".join(h.replace(".", r"\.") for h in _CDN_HOSTS) + r")/[^\s\"']+"
)


def _urls_from_constants() -> set[str]:
    found: set[str] = set()
    for dotted in _MODULES_WITH_CDN_CONSTANTS:
        module = import_module(dotted)
        for name in dir(module):
            if not name.endswith("_CDN"):
                continue
            value = getattr(module, name)
            if isinstance(value, str) and value.startswith("https://"):
                found.add(value)
    return found


def _urls_from_templates() -> set[str]:
    root = Path(__file__).resolve().parents[2]
    found: set[str] = set()
    for relative in _MODULES_WITH_INLINE_URLS:
        text = (root / relative).read_text(encoding="utf-8")
        found.update(url for url in _URL.findall(text) if "{" not in url)
    return found


def _library_and_version(url: str) -> tuple[str, str] | None:
    for pattern in (_NPM_STYLE, _CDNJS_STYLE):
        match = pattern.search(url)
        if match:
            return match.group(1), match.group(2)
    return None


def _loaded_libraries() -> dict[str, str]:
    """{package name: version} for every browser library the code loads."""
    libraries: dict[str, str] = {}
    for url in _urls_from_constants() | _urls_from_templates():
        parsed = _library_and_version(url)
        assert parsed is not None, f"cannot read a library and version out of {url}"
        name, version = parsed
        libraries[name] = version
    return libraries


def _declared() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    return json.loads((root / "package.json").read_text(encoding="utf-8")).get("dependencies", {})


def test_the_scanner_finds_the_libraries_at_all() -> None:
    """A guard on the guard: a scanner that silently finds nothing passes every
    other test in this file."""
    assert len(_loaded_libraries()) >= 8


@pytest.mark.parametrize("name", sorted(_loaded_libraries()))
def test_every_loaded_library_is_declared(name: str) -> None:
    assert name in _declared(), (
        f"{name} is loaded from a CDN but absent from package.json — "
        "declare it so npm audit and Dependabot can see it"
    )


@pytest.mark.parametrize(("name", "version"), sorted(_loaded_libraries().items()))
def test_the_declared_version_is_the_pinned_one(name: str, version: str) -> None:
    declared = _declared().get(name)
    assert declared == version, (
        f"{name}: package.json says {declared!r}, the source pins {version!r} — "
        "bump both, or the manifest describes a version nobody loads"
    )


def test_declared_versions_are_exact() -> None:
    """A range would make the manifest a wish rather than a record: the code
    loads one version, and that is the one to audit."""
    for name, spec in _declared().items():
        assert re.fullmatch(r"[0-9][0-9a-zA-Z.\-+]*", spec), (
            f"{name} is declared as {spec!r}; pin it exactly, since the source does"
        )


def test_nothing_is_declared_that_the_code_does_not_load() -> None:
    """The other direction: a leftover entry keeps a library on the audit list
    long after the view that used it stopped loading it."""
    loaded = set(_loaded_libraries())
    for name in _declared():
        assert name in loaded, (
            f"{name} is declared in package.json but no view loads it — remove it"
        )


# ── where the lockfile fetches from ──────────────────────────────────────────
#
# Dependabot resolves through whatever registry it is configured with, and
# writes *that* host into package-lock.json. When it is a private proxy, CI
# runners have no credentials for it and `npm ci` fails hard on a 401 — not on
# the bumped package, on the whole install. That reached main once (#229) and
# turned `Lint JS` red on every branch cut from it afterwards.
#
# It is invisible locally: npm serves the tarball from its content-addressed
# cache, keyed by integrity, without touching the network — so the developer
# who has built once sees nothing wrong. This test is the seam that does not
# depend on a warm cache, and it runs in the Python job, which is the one that
# still runs on a Dependabot PR.

_PUBLIC_REGISTRY = "https://registry.npmjs.org/"


def _resolved_urls() -> list[str]:
    root = Path(__file__).resolve().parents[2]
    lock = json.loads((root / "package-lock.json").read_text(encoding="utf-8"))
    return [
        entry["resolved"]
        for entry in lock.get("packages", {}).values()
        if isinstance(entry, dict) and "resolved" in entry
    ]


def test_every_lockfile_entry_comes_from_the_public_registry() -> None:
    """A private-proxy URL here is a 401 on every CI runner, for the whole install."""
    foreign = sorted({u for u in _resolved_urls() if not u.startswith(_PUBLIC_REGISTRY)})
    assert not foreign, (
        "package-lock.json resolves from a registry CI cannot authenticate to:\n  "
        + "\n  ".join(foreign)
        + f"\n\nRewrite the host to {_PUBLIC_REGISTRY} — the tarball is the same package, "
        "so the integrity hash already in the lockfile still matches. The lasting fix is "
        "the private-registry setting above the repository."
    )
