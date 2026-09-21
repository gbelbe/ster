"""Unit tests for the working-file switch sequence (``ster.working_file.switch``).

Every way this operation goes wrong is an ordering mistake, so these tests are
mostly about *when* each side effect runs, not what it returns. The side
effects are injected, which is what makes the order observable at all — the
editor drives the same function from a background worker, where the same
assertions could only be made by racing it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ster.working_file import MissingWorkingFile, UnknownWorkingFile, switch


class _Recorder:
    """Records the order of flush / load / apply, with the arguments each saw."""

    def __init__(self, taxonomy: object = "reloaded-model") -> None:
        self.calls: list[str] = []
        self.taxonomy = taxonomy
        self.loaded_with: tuple[Path, list[Path]] | None = None
        self.applied_with: tuple[object, Path, list[Path]] | None = None

    def flush(self) -> None:
        self.calls.append("flush")

    def load(self, editable: Path, context: list[Path]) -> object:
        self.calls.append("load")
        self.loaded_with = (editable, context)
        return self.taxonomy

    def apply(self, taxonomy: object, editable: Path, context: list[Path]) -> None:
        self.calls.append("apply")
        self.applied_with = (taxonomy, editable, context)


@pytest.fixture
def files(tmp_path: Path) -> dict[str, Path]:
    gear = tmp_path / "gear.ttl"
    places = tmp_path / "places.ttl"
    meta = tmp_path / "meta.ttl"
    for path in (gear, places, meta):
        path.write_text("", encoding="utf-8")
    return {"gear": gear, "places": places, "meta": meta}


def _switch(chosen: Path, files: dict[str, Path], rec: _Recorder, current: str = "gear"):
    return switch(
        chosen,
        current=files[current],
        loaded=[files["gear"], files["places"], files["meta"]],
        flush=rec.flush,
        load=rec.load,
        apply=rec.apply,
    )


# ── the happy path ────────────────────────────────────────────────────────────


def test_switch_reloads_with_roles_swapped(files):
    rec = _Recorder()
    outcome = _switch(files["places"], files, rec)

    assert outcome.editable == files["places"]
    assert outcome.context == [files["gear"], files["meta"]]
    assert outcome.reloaded is True


def test_switch_loads_the_chosen_file_against_the_others(files):
    rec = _Recorder()
    _switch(files["places"], files, rec)

    assert rec.loaded_with == (files["places"], [files["gear"], files["meta"]])


def test_switch_applies_the_freshly_loaded_model(files):
    rec = _Recorder()
    _switch(files["places"], files, rec)

    assert rec.applied_with == (
        "reloaded-model",
        files["places"],
        [files["gear"], files["meta"]],
    )


# ── ordering: the regressions ─────────────────────────────────────────────────


def test_switch_flushes_before_loading_regression(files):
    """Root cause: the editor saves on a debounced background worker that reads
    ``self.tax`` and ``self._path`` together. Flushing after the roles moved
    pairs the old model with the new path — one ontology written into another
    ontology's file."""
    rec = _Recorder()
    _switch(files["places"], files, rec)

    assert rec.calls == ["flush", "load", "apply"]


def test_switch_applies_only_after_a_successful_load(files):
    """A parse failure must leave the session on its previous model rather than
    half-switched."""
    rec = _Recorder()

    def boom(editable: Path, context: list[Path]) -> object:
        rec.calls.append("load")
        raise OSError("unparseable")

    with pytest.raises(OSError, match="unparseable"):
        switch(
            files["places"],
            current=files["gear"],
            loaded=list(files.values()),
            flush=rec.flush,
            load=boom,
            apply=rec.apply,
        )

    assert "apply" not in rec.calls


# ── the no-op ─────────────────────────────────────────────────────────────────


def test_switch_to_current_file_reports_no_reload(files):
    rec = _Recorder()
    outcome = _switch(files["gear"], files, rec)

    assert outcome.reloaded is False


def test_switch_to_current_file_touches_nothing(files):
    """Re-parsing a large ontology because someone reopened the menu and picked
    the row it was already on is a freeze with nothing to show for it."""
    rec = _Recorder()
    _switch(files["gear"], files, rec)

    assert rec.calls == []


# ── refusals ──────────────────────────────────────────────────────────────────


def test_switch_to_unknown_file_raises(files, tmp_path):
    rec = _Recorder()
    with pytest.raises(UnknownWorkingFile):
        _switch(tmp_path / "stranger.ttl", files, rec)


def test_switch_to_deleted_file_raises_naming_it(files):
    rec = _Recorder()
    files["places"].unlink()

    with pytest.raises(MissingWorkingFile, match="places.ttl"):
        _switch(files["places"], files, rec)


def test_a_refused_switch_changes_nothing(files):
    """Nothing may be flushed or parsed on behalf of a switch that is not going
    to happen — a refusal must leave the session exactly as it was."""
    rec = _Recorder()
    files["places"].unlink()

    with pytest.raises(MissingWorkingFile):
        _switch(files["places"], files, rec)

    assert rec.calls == []
