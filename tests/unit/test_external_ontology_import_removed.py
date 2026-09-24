"""The "Import External Ontology" feature is gone, and stays gone.

It fetched external vocabularies into ``~/.cache/ster/ontologies`` and bound
their namespaces from a home-menu screen. Removed with its module, its menu
entry and its cache; ``owl:imports`` headers and ``--context-files`` are other
features and are untouched.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from ster.cli import _home, _home_actions

REPO = Path(__file__).resolve().parents[2]


def test_the_import_modules_no_longer_exist():
    for module in ("ster.ontology_imports", "ster.ext_ontologies_ui"):
        assert importlib.util.find_spec(module) is None, f"{module} is back"


def test_no_module_imports_the_removed_import_modules():
    offenders = [
        path.relative_to(REPO)
        for path in (REPO / "ster").rglob("*.py")
        if "ontology_imports" in (text := path.read_text(encoding="utf-8"))
        or "ext_ontologies_ui" in text
    ]
    assert offenders == []


def test_home_menu_no_longer_offers_import_external_ontology():
    labels = [label for _, label in _home_actions()]

    assert labels, "the home menu should still offer its other actions"
    assert not any("External Ontology" in label for label in labels)


def test_the_retired_download_cache_is_cleared_on_start(tmp_path, monkeypatch):
    cache = tmp_path / "ontologies"
    cache.mkdir()
    (cache / "xmlns.com_foaf_0.1_4ab5914a.ttl").write_text("# cached", encoding="utf-8")
    monkeypatch.setattr(_home, "_RETIRED_CACHE", cache)

    _home._clear_retired_cache()

    assert not cache.exists()


def test_clearing_a_cache_that_is_not_there_is_a_no_op(tmp_path, monkeypatch):
    monkeypatch.setattr(_home, "_RETIRED_CACHE", tmp_path / "never-created")

    _home._clear_retired_cache()  # must not raise

    assert not (tmp_path / "never-created").exists()


def test_the_cache_is_cleared_by_every_start(monkeypatch):
    """Cleared on the path every ster launch takes: `main` → `_dispatch`."""
    import inspect

    assert "_dispatch()" in inspect.getsource(_home.main)
    assert "_clear_retired_cache()" in inspect.getsource(_home._dispatch)
