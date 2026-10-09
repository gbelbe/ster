"""``ster cache clear`` removes the saved merged graphs and nothing else."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from ster.cli import app
from ster.store import _cache

TEXT = "utf-8"


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(_cache, "_bin_cache_dir", lambda: tmp_path / "bin_cache")
    (tmp_path / "bin_cache").mkdir()
    return tmp_path / "bin_cache"


def _clear():
    return CliRunner().invoke(app, ["cache", "clear"])


def test_cache_clear_removes_snapshots_and_their_manifests(cache_dir):
    for name in ("one_1.pickle", "merged-two_2.pickle", "merged-two_2.manifest.json"):
        (cache_dir / name).write_text("x", encoding=TEXT)
    result = _clear()
    assert result.exit_code == 0
    assert list(cache_dir.iterdir()) == []


def test_cache_clear_keeps_downloaded_assets(cache_dir):
    asset = cache_dir.parent / "cytoscape-3.min.js"
    asset.write_text("lib", encoding=TEXT)
    (cache_dir / "one_1.pickle").write_text("x", encoding=TEXT)
    _clear()
    assert asset.exists()


def test_cache_clear_on_empty_cache_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(_cache, "_bin_cache_dir", lambda: tmp_path / "missing")
    assert _clear().exit_code == 0
