"""Tests for check_update() in ster/_version.py."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import ster._version as version_module
from ster._version import check_update


def _write_cache(path, latest: str, age_hours: float = 1.0) -> None:
    checked = (datetime.now() - timedelta(hours=age_hours)).isoformat()
    path.write_text(json.dumps({"checked": checked, "latest": latest}))


# ── no cache ──────────────────────────────────────────────────────────────────


def test_no_cache_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(version_module, "_VERSION_CACHE", tmp_path / "cache.json")
    monkeypatch.setattr(version_module, "__version__", "0.3.5")
    assert check_update() is None


# ── up to date ────────────────────────────────────────────────────────────────


def test_up_to_date_returns_none(tmp_path, monkeypatch):
    cache = tmp_path / "cache.json"
    _write_cache(cache, "0.3.5")
    monkeypatch.setattr(version_module, "_VERSION_CACHE", cache)
    monkeypatch.setattr(version_module, "__version__", "0.3.5")
    assert check_update() is None


def test_installed_newer_than_cache_returns_none(tmp_path, monkeypatch):
    cache = tmp_path / "cache.json"
    _write_cache(cache, "0.3.4")
    monkeypatch.setattr(version_module, "_VERSION_CACHE", cache)
    monkeypatch.setattr(version_module, "__version__", "0.3.5")
    assert check_update() is None


# ── update available ──────────────────────────────────────────────────────────


def test_newer_available_returns_version_string(tmp_path, monkeypatch):
    cache = tmp_path / "cache.json"
    _write_cache(cache, "0.4.0")
    monkeypatch.setattr(version_module, "_VERSION_CACHE", cache)
    monkeypatch.setattr(version_module, "__version__", "0.3.5")
    assert check_update() == "0.4.0"


def test_newer_minor_returns_version(tmp_path, monkeypatch):
    cache = tmp_path / "cache.json"
    _write_cache(cache, "0.3.6")
    monkeypatch.setattr(version_module, "_VERSION_CACHE", cache)
    monkeypatch.setattr(version_module, "__version__", "0.3.5")
    assert check_update() == "0.3.6"


# ── stale / corrupt cache ─────────────────────────────────────────────────────


def test_expired_cache_returns_none(tmp_path, monkeypatch):
    cache = tmp_path / "cache.json"
    _write_cache(cache, "0.4.0", age_hours=13.0)  # older than 12-h TTL
    monkeypatch.setattr(version_module, "_VERSION_CACHE", cache)
    monkeypatch.setattr(version_module, "__version__", "0.3.5")
    assert check_update() is None


def test_malformed_cache_returns_none(tmp_path, monkeypatch):
    cache = tmp_path / "cache.json"
    cache.write_text("not-json{{{")
    monkeypatch.setattr(version_module, "_VERSION_CACHE", cache)
    monkeypatch.setattr(version_module, "__version__", "0.3.5")
    assert check_update() is None
