"""A backgrounded save that never completes must not look like a completed one.

Edits are persisted on a background worker and the app flushes any pending save
on quit. That safety net only works while the dirty flag still says an edit is
outstanding — so the flag must not be cleared until the bytes are on disk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ster import store
from ster.tui.app import OntologyApp

TTL = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <https://example.org/t#> .
ex:Scheme a skos:ConceptScheme .
ex:Tent a skos:Concept ; skos:prefLabel "Tent"@en ; skos:inScheme ex:Scheme .
"""


@pytest.fixture
def app(tmp_path, monkeypatch):
    path = tmp_path / "o.ttl"
    path.write_text(TTL, encoding="utf-8")
    application = OntologyApp(store.load(path), source="o.ttl", path=path)
    # _save_worker clears its spinner through the UI thread; there is no running
    # app here and the spinner is not what these tests are about.
    monkeypatch.setattr(type(application), "call_from_thread", lambda self, fn, *a: None)
    return application, path


def test_a_failed_save_leaves_the_edit_marked_dirty(app, monkeypatch):
    """The flag is the only record that an edit is unpersisted.

    run_worker(exclusive=True) cancels a running save when another is scheduled,
    and store.save can raise. Clearing the flag first meant either case left the
    app believing it was clean, so the quit-time flush wrote nothing and the edit
    was lost with no error.
    """
    application, _path = app
    application._save_dirty = True

    def boom(_tax, _path):
        raise OSError("disk went away mid-write")

    monkeypatch.setattr(store, "save", boom)

    with pytest.raises(OSError):
        application._save_worker()

    assert application._save_dirty, "a save that did not land must stay outstanding"


def test_a_successful_save_clears_the_flag(app, monkeypatch):
    application, _path = app
    application._save_dirty = True
    monkeypatch.setattr(store, "save", lambda _t, _p: None)

    application._save_worker()

    assert not application._save_dirty


def test_an_edit_arriving_mid_save_stays_outstanding(app, monkeypatch):
    """The reason the flag was cleared early — do not regress it.

    If an edit lands while the write is in flight, the taxonomy it produced has
    not been written, so the flag has to survive this save and be picked up by
    the next one.
    """
    application, path = app
    application._save_dirty = True

    def save_then_edit(_tax, _path):
        # a new edit swaps in a fresh authority while the write is happening
        application.tax = store.load(path)

    monkeypatch.setattr(store, "save", save_then_edit)

    application._save_worker()

    assert application._save_dirty, "the newer edit is still unwritten"


def test_flush_writes_when_a_save_was_left_outstanding(app, monkeypatch):
    """on_unmount's flush is the safety net; it must actually fire."""
    application, _path = app
    application._save_dirty = True
    written: list[Path] = []
    monkeypatch.setattr(store, "save", lambda _t, p: written.append(p))

    application._flush_save()

    assert written, "quit-time flush must persist an outstanding edit"
    assert not application._save_dirty
