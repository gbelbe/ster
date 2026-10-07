"""``ster serve`` settles a held port itself instead of crashing in uvicorn."""

from __future__ import annotations

from pathlib import Path

import pytest
import typer

from ster.cli import _serve
from ster.cli._exit import ExitCode
from ster.viz_vowl import _claim
from ster.viz_vowl._claim import BLOCKED, FREE, REUSE, Claim

TAX = Path("/project/tax.ttl")


def _claims(monkeypatch, claim: Claim) -> list:
    seen: list = []

    def _claim_port(taxonomy_file, confirm=None, host=None, port=None):
        seen.append((taxonomy_file, confirm, host, port))
        return claim

    monkeypatch.setattr("ster.viz_vowl.claim_port", _claim_port)
    return seen


def test_serve_proceeds_on_a_usable_port(monkeypatch):
    _claims(monkeypatch, Claim(FREE))

    _serve._claim_serve_port(TAX, None, 9999)  # returns, does not exit


def test_serve_asks_before_replacing_and_passes_the_port(monkeypatch):
    from ster.cli._publish import _confirm_replace

    seen = _claims(monkeypatch, Claim(FREE))

    _serve._claim_serve_port(TAX, "127.0.0.1", 9999)

    assert seen == [(TAX, _confirm_replace, "127.0.0.1", 9999)]


def test_serve_refuses_when_a_tui_holds_the_port(monkeypatch):
    """Regression: this used to be an uvicorn 'address in use' traceback."""
    _claims(monkeypatch, Claim(BLOCKED, "another ster session is open (x). Please close it first."))

    with pytest.raises(typer.Exit) as exit_info:
        _serve._claim_serve_port(TAX, None, None)

    assert exit_info.value.exit_code == ExitCode.UNEXPECTED


def test_serve_points_at_a_server_already_showing_the_file(monkeypatch):
    _claims(monkeypatch, Claim(REUSE, url="http://127.0.0.1:8765"))

    with pytest.raises(typer.Exit) as exit_info:
        _serve._claim_serve_port(TAX, None, None)

    assert exit_info.value.exit_code == ExitCode.OK


def test_claim_module_is_the_one_the_cli_imports():
    assert _claim.claim_port is __import__("ster.viz_vowl", fromlist=["claim_port"]).claim_port
