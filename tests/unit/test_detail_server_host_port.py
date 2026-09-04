"""Unit tests for _detail._server_host_port."""

from __future__ import annotations

from unittest.mock import patch

from ster.viz_vowl._detail import _server_host_port


def test_server_host_port_returns_given_values_when_both_supplied():
    assert _server_host_port("example.org", 9999) == ("example.org", 9999)


def test_server_host_port_falls_back_to_saved_config_when_missing():
    """When host or port is omitted, it's filled in from the saved server config."""
    with patch(
        "ster.api_server.load_server_config",
        return_value=("http://127.0.0.1:8765", 8765),
    ):
        assert _server_host_port(None, None) == ("127.0.0.1:8765", 8765)
        assert _server_host_port("custom.host", None) == ("custom.host", 8765)
        assert _server_host_port(None, 1234) == ("127.0.0.1:8765", 1234)
