"""Shared fixtures for all test modules."""

from __future__ import annotations

from pathlib import Path

import pytest

from ster import store
from ster.model import Concept, ConceptScheme, Definition, Label, Taxonomy

BASE = "https://example.org/test/"


@pytest.fixture(autouse=True)
def _isolate_analysis_cache(tmp_path_factory, monkeypatch):
    """Redirect the on-disk analysis cache to a per-test tmp dir and disable binary cache.

    Without this, tests read/write the developer's real
    ~/.cache/ster/analysis_cache.json: every viewer-save test re-serialised the
    real home cache, causing both disk I/O noise and potential cross-pollination.
    Isolating it keeps the suite fast and side-effect-free.
    See tests/unit/test_analysis_cache_isolation.py.
    """
    monkeypatch.setenv("STER_NO_CACHE", "1")
    cache = tmp_path_factory.mktemp("ster-analysis-cache") / "analysis_cache.json"
    monkeypatch.setattr("ster.analysis_cache._cache_path", lambda: cache)
    # Also isolate the binary cache directory
    bin_cache_dir = tmp_path_factory.mktemp("ster-bin-cache")
    monkeypatch.setattr("ster.store._bin_cache_dir", lambda: bin_cache_dir)


# Modules that test server startup itself, and so must reach the real function.
_SERVER_OWN_TESTS = frozenset(
    {
        "tests.unit.test_server_startup",
        "tests.unit.test_api_server_background",
        "tests.step_defs.test_server_startup",
    }
)


@pytest.fixture(autouse=True)
def _no_background_api_server(request, monkeypatch):
    """Keep unit tests off the network — the TUI opens a real socket otherwise.

    Opening a file makes OntologyApp start the MCP context server on a daemon
    thread, and that binds the *configured* port — 8765 by default. Under
    ``-n auto`` every TUI test races for it: the worker that loses gets
    "address already in use", the app never reaches ready, and the failure
    surfaces somewhere unrelated as a missing widget. It cost a red CI run on a
    branch whose tree was byte-identical to a green one.

    No unit test needs that socket. Returning False is the documented
    best-effort path — "no MCP this session" — which must never stop the editor
    opening, so this exercises a real code path rather than faking one. Tests
    marked ``integration`` are left alone, as are the modules whose subject *is*
    the server: they are the ones that mean it.
    """
    if "integration" in request.keywords or request.module.__name__ in _SERVER_OWN_TESTS:
        return

    from ster import api_server

    monkeypatch.setattr(api_server, "start_background", lambda *args, **kwargs: False)


@pytest.fixture(autouse=True)
def _disable_version_check(request, monkeypatch):
    """Prevent tests from spawning background threads to check PyPI.

    This avoids non-deterministic cache updates and network noise.
    We skip this for the tests that specifically test the version check logic.
    """
    if request.module.__name__ in ("tests.test_cli", "tests.test_version"):
        return

    from ster import _version as version_module
    from ster import cli

    # Mock the high-level functions that trigger the check
    monkeypatch.setattr(cli, "_check_new_version", lambda: None)
    monkeypatch.setattr(version_module, "check_update", lambda: None)


@pytest.fixture(autouse=True)
def _isolate_prefs_globally(tmp_path_factory, monkeypatch):
    """Redirect every on-disk preference file to a per-test tmp dir.

    Without this, tests read (and *write*) the developer's real
    ~/.config/ster/*.json — theme, configured languages, the metadata-property
    catalogs, the plugin config. That both pollutes real config and makes tests
    order-dependent: e.g. the annotation picker's options come from
    ``load_metadata_props()``, so a leaked catalog changes what predicates are
    offered. Isolating the prefs makes every test see the clean defaults.

    The name is deliberately *not* ``_isolate_prefs``: several modules define a
    local autouse fixture by that name, which would shadow this one and silently
    re-expose whatever paths the local version forgets to patch. Keeping the
    names distinct makes both run, so the full set is always covered.
    """
    from ster.nav import prefs
    from ster.plugins.semanticlint import config as sl_config

    d = tmp_path_factory.mktemp("ster-prefs")
    for attr in (
        "_prefs_path",
        "_lang_prefs_path",
        "_configured_langs_path",
        "_metadata_props_path",
        "_entity_metadata_props_path",
    ):
        monkeypatch.setattr(prefs, attr, lambda a=attr: d / f"{a}.json")
    monkeypatch.setattr(sl_config, "_config_path", lambda: d / "quality.json")


MINIMAL_TURTLE = """\
@prefix skos:    <http://www.w3.org/2004/02/skos/core#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix t:       <https://example.org/test/> .

t:Scheme a skos:ConceptScheme ;
    dcterms:title "Test Taxonomy"@en , "Taxonomie de Test"@fr ;
    skos:hasTopConcept t:Top .

t:Top a skos:Concept ;
    skos:inScheme t:Scheme ;
    skos:topConceptOf t:Scheme ;
    skos:prefLabel "Top Concept"@en , "Concept Principal"@fr ;
    skos:definition "The root concept."@en ;
    skos:narrower t:Child1 , t:Child2 .

t:Child1 a skos:Concept ;
    skos:inScheme t:Scheme ;
    skos:prefLabel "Child One"@en , "Enfant Un"@fr ;
    skos:broader t:Top ;
    skos:narrower t:Grandchild .

t:Child2 a skos:Concept ;
    skos:inScheme t:Scheme ;
    skos:prefLabel "Child Two"@en , "Enfant Deux"@fr ;
    skos:altLabel "Second child"@en ;
    skos:broader t:Top .

t:Grandchild a skos:Concept ;
    skos:inScheme t:Scheme ;
    skos:prefLabel "Grandchild"@en ;
    skos:broader t:Child1 .
"""


@pytest.fixture
def minimal_turtle() -> str:
    return MINIMAL_TURTLE


@pytest.fixture
def tmp_ttl(tmp_path: Path, minimal_turtle: str) -> Path:
    """Write minimal turtle to a temp file and return the path."""
    p = tmp_path / "test.ttl"
    p.write_text(minimal_turtle, encoding="utf-8")
    return p


@pytest.fixture
def taxonomy(tmp_ttl: Path) -> Taxonomy:
    """Load the minimal taxonomy from disk."""
    return store.load(tmp_ttl)


@pytest.fixture
def simple_taxonomy() -> Taxonomy:
    """Build a minimal Taxonomy in memory (no disk I/O)."""
    t = Taxonomy()
    scheme = ConceptScheme(
        uri=BASE + "Scheme",
        labels=[Label(lang="en", value="Test Taxonomy")],
        top_concepts=[BASE + "Top"],
        base_uri=BASE,
    )
    top = Concept(
        uri=BASE + "Top",
        labels=[
            Label(lang="en", value="Top Concept"),
            Label(lang="fr", value="Concept Principal"),
        ],
        definitions=[Definition(lang="en", value="The root.")],
        narrower=[BASE + "Child1", BASE + "Child2"],
        top_concept_of=BASE + "Scheme",
    )
    child1 = Concept(
        uri=BASE + "Child1",
        labels=[Label(lang="en", value="Child One")],
        broader=[BASE + "Top"],
        narrower=[BASE + "Grandchild"],
    )
    child2 = Concept(
        uri=BASE + "Child2",
        labels=[Label(lang="en", value="Child Two")],
        broader=[BASE + "Top"],
    )
    grandchild = Concept(
        uri=BASE + "Grandchild",
        labels=[Label(lang="en", value="Grandchild")],
        broader=[BASE + "Child1"],
    )
    t.schemes[scheme.uri] = scheme
    for c in (top, child1, child2, grandchild):
        t.concepts[c.uri] = c
    from ster.handles import assign_handles

    assign_handles(t)
    return t


@pytest.fixture
def settle():
    """Wait for a Textual condition on a wall clock, not a turn count.

    ``pilot.pause()`` yields one event-loop turn, so a fixed number of pauses
    bounds the wait in *turns* while the work being waited on — a lint scan, a
    worker thread, a timer — takes *time*. Under ``-n auto`` the workers compete
    for CPU and a turn-bounded wait can expire before the work lands, which made
    the scan-on-open tests fail intermittently in CI while passing in isolation.

    A deadline holds regardless of how loaded the machine is; a passing test
    still returns as soon as the predicate is true, so this costs nothing when
    things are fast.
    """
    import asyncio
    import time

    async def _settle(pilot, predicate, *, timeout: float = 15.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            await pilot.pause()
            await asyncio.sleep(0.01)
        return predicate()

    return _settle
