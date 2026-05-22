"""Unit tests for server config persistence (load/save URL+port)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ster.api_server import load_server_config, save_server_config
from ster.viz_vowl import API_PORT

_CONFIG_FILE = Path.home() / ".config" / "ster" / "server_config.json"


@pytest.fixture(autouse=True)
def _clean_config(tmp_path, monkeypatch):
    """Redirect config file to a temp dir for each test."""
    import ster.api_server as _mod

    fake = tmp_path / "server_config.json"
    monkeypatch.setattr(_mod, "_SERVER_CONFIG_FILE", fake)
    yield fake


def test_load_defaults_when_no_file():
    url, port = load_server_config()
    assert url == "http://127.0.0.1"
    assert port == 8765


def test_default_url_is_localhost():
    url, _ = load_server_config()
    assert url == "http://127.0.0.1"


def test_default_port_equals_api_port_constant():
    _, port = load_server_config()
    assert port == API_PORT


def test_save_and_reload_url():
    save_server_config("http://192.168.1.10", 8765)
    url, _ = load_server_config()
    assert url == "http://192.168.1.10"


def test_save_and_reload_port():
    save_server_config("http://127.0.0.1", 9000)
    _, port = load_server_config()
    assert port == 9000


def test_port_saved_as_int():
    save_server_config("http://127.0.0.1", 9000)
    _, port = load_server_config()
    assert isinstance(port, int)
