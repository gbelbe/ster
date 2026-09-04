"""Path-construction helpers in :mod:`ster.nav.prefs`.

Every other test in the suite runs under the session-wide
``_isolate_prefs_globally`` autouse fixture (see ``tests/conftest.py``), which
replaces these ``_*_path()`` functions outright so tests never touch the
developer's real ``~/.config/ster``. That leaves their actual bodies —
building each file's path under the shared config directory — never
exercised. These tests undo that patch to check the real implementation.
"""

from __future__ import annotations

from ster.nav import prefs


def test_lang_prefs_path_is_under_the_shared_config_dir(monkeypatch) -> None:
    monkeypatch.undo()
    assert prefs._lang_prefs_path() == prefs._STER_CONFIG_DIR / "lang_prefs.json"


def test_configured_langs_path_is_under_the_shared_config_dir(monkeypatch) -> None:
    monkeypatch.undo()
    assert prefs._configured_langs_path() == prefs._STER_CONFIG_DIR / "configured_langs.json"


def test_metadata_props_path_is_under_the_shared_config_dir(monkeypatch) -> None:
    monkeypatch.undo()
    assert prefs._metadata_props_path() == prefs._STER_CONFIG_DIR / "metadata_props.json"


def test_entity_metadata_props_path_is_under_the_shared_config_dir(monkeypatch) -> None:
    monkeypatch.undo()
    assert (
        prefs._entity_metadata_props_path() == prefs._STER_CONFIG_DIR / "entity_metadata_props.json"
    )


def test_prefs_path_is_under_the_shared_config_dir(monkeypatch) -> None:
    monkeypatch.undo()
    assert prefs._prefs_path() == prefs._STER_CONFIG_DIR / "prefs.json"
