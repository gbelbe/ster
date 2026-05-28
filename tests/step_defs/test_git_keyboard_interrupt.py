"""BDD step definitions for tests/features/git/keyboard_interrupt.feature."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pytest_bdd import given, scenarios, then, when

from ster.git.manager import GitManager

scenarios("../features/git/keyboard_interrupt.feature")


@pytest.fixture()
def ctx(tmp_path: Path) -> dict[str, Any]:
    taxonomy = tmp_path / "test.ttl"
    taxonomy.touch()
    m = GitManager(taxonomy)
    m._cfg = {
        "repo_path": str(tmp_path),
        "remote_url": "https://example.com/repo.git",
        "main_branch": "main",
    }
    return {"mgr": m, "result": "NOT_SET", "raised": False}


@given("a configured GitManager")
def configured_manager(ctx: dict[str, Any]) -> None:
    pass  # fixture already sets this up


@when("subprocess is interrupted during check_and_pull")
def interrupt_check_and_pull(ctx: dict[str, Any]) -> None:
    with patch("ster.git.manager._git", side_effect=KeyboardInterrupt):
        ctx["result"] = ctx["mgr"].check_and_pull()


@when("subprocess is interrupted during pre_edit_check")
def interrupt_pre_edit_check(ctx: dict[str, Any]) -> None:
    with patch("ster.git.manager._git", side_effect=KeyboardInterrupt):
        ctx["result"] = ctx["mgr"].pre_edit_check()


@when("subprocess is interrupted during fetch_remote")
def interrupt_fetch_remote(ctx: dict[str, Any]) -> None:
    with patch("ster.git.manager._git", side_effect=KeyboardInterrupt):
        ctx["mgr"].fetch_remote()
        ctx["result"] = None


@then("check_and_pull returns None without raising")
def check_and_pull_none(ctx: dict[str, Any]) -> None:
    assert ctx["result"] is None


@then("pre_edit_check returns None without raising")
def pre_edit_check_none(ctx: dict[str, Any]) -> None:
    assert ctx["result"] is None


@then("fetch_remote returns None without raising")
def fetch_remote_none(ctx: dict[str, Any]) -> None:
    assert ctx["result"] is None
