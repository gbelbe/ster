"""Unit tests for the fixed API server port and kai extension default URL."""

from __future__ import annotations

from pathlib import Path

from ster.viz_vowl import API_PORT

_EXTENSION_DIR = Path(__file__).parent.parent.parent / "kai-extension"


def test_api_port_is_8765():
    assert API_PORT == 8765


def test_api_port_is_int():
    assert isinstance(API_PORT, int)


def test_server_url_format():
    assert f"http://127.0.0.1:{API_PORT}/" == "http://127.0.0.1:8765/"


def test_extension_default_api_url():
    src = (_EXTENSION_DIR / "popup.js").read_text()
    assert 'const DEFAULT_API_URL = "http://127.0.0.1:8765"' in src


def test_extension_placeholder_contains_port():
    html = (_EXTENSION_DIR / "popup.html").read_text()
    assert "8765" in html
