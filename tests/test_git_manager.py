"""Tests for git_manager — config, subprocess helpers, GitManager public API."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import ster.git_manager as gm
from ster.git_manager import (
    GitManager,
    _git_available,
    _load_global_config,
    _save_global_config,
    render_diff,
)

# ── config helpers ────────────────────────────────────────────────────────────


def test_load_global_config_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(gm, "CONFIG_FILE", tmp_path / "nonexistent.json")
    assert _load_global_config() == {}


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(gm, "CONFIG_FILE", tmp_path / "cfg.json")
    monkeypatch.setattr(gm, "CONFIG_DIR", tmp_path)
    data = {"/some/path.ttl": {"repo_path": "/repo", "git_enabled": True}}
    _save_global_config(data)
    loaded = _load_global_config()
    assert loaded == data


def test_load_global_config_corrupted_json(tmp_path, monkeypatch):
    cfg = tmp_path / "bad.json"
    cfg.write_text("not json!!!")
    monkeypatch.setattr(gm, "CONFIG_FILE", cfg)
    assert _load_global_config() == {}


# ── _git_available ────────────────────────────────────────────────────────────


def test_git_available_true():
    result = _git_available()
    assert isinstance(result, bool)


def test_git_available_false_when_not_found(monkeypatch):
    def raise_fnf(*a, **kw):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", raise_fnf)
    assert _git_available() is False


# ── render_diff ───────────────────────────────────────────────────────────────


def test_render_diff_addition(capsys):
    render_diff("+added line\n")
    # No crash; output produced by rich console, just verify it runs


def test_render_diff_deletion(capsys):
    render_diff("-removed line\n")


def test_render_diff_hunk_header(capsys):
    render_diff("@@ -1,3 +1,4 @@ context\n")


def test_render_diff_context_line(capsys):
    render_diff(" unchanged line\n")


def test_render_diff_truncation(capsys):
    # Build a diff longer than max_lines (default 60)
    lines = "\n".join(f"+line{i}" for i in range(80))
    render_diff(lines, max_lines=60)  # should not crash


def test_render_diff_ignores_plus_plus_plus():
    render_diff("+++ b/file.txt\n")  # header, not addition — no crash


def test_render_diff_ignores_minus_minus_minus():
    render_diff("--- a/file.txt\n")  # header — no crash


# ── GitManager construction and basic properties ──────────────────────────────


def _make_manager(tmp_path: Path, cfg: dict | None = None) -> GitManager:
    taxonomy = tmp_path / "tax.ttl"
    taxonomy.write_text("")
    mgr = GitManager(taxonomy)
    if cfg is not None:
        mgr._cfg = cfg
    return mgr


def test_is_enabled_default(tmp_path):
    mgr = _make_manager(tmp_path)
    assert mgr.is_enabled() is True


def test_is_enabled_false_when_disabled(tmp_path):
    mgr = _make_manager(tmp_path, {"git_enabled": False})
    assert mgr.is_enabled() is False


def test_is_configured_without_repo_path(tmp_path):
    mgr = _make_manager(tmp_path, {})
    assert mgr.is_configured() is False


def test_is_configured_with_repo_path(tmp_path):
    mgr = _make_manager(tmp_path, {"repo_path": str(tmp_path)})
    assert mgr.is_configured() is True


# ── _repo ─────────────────────────────────────────────────────────────────────


def test_repo_returns_none_when_no_config(tmp_path):
    mgr = _make_manager(tmp_path, {})
    assert mgr._repo() is None


def test_repo_returns_path_when_exists(tmp_path):
    mgr = _make_manager(tmp_path, {"repo_path": str(tmp_path)})
    assert mgr._repo() == tmp_path


def test_repo_returns_none_when_path_missing(tmp_path):
    mgr = _make_manager(tmp_path, {"repo_path": str(tmp_path / "gone")})
    assert mgr._repo() is None


# ── stage_file / stage_path ───────────────────────────────────────────────────


def test_stage_file_calls_git_add(tmp_path):
    mgr = _make_manager(tmp_path, {"repo_path": str(tmp_path)})
    with patch("ster.git_manager._git") as mock_git:
        mock_git.return_value = MagicMock(returncode=0)
        mgr.stage_file()
    mock_git.assert_called_once_with("add", str(mgr.taxonomy_path), cwd=tmp_path)


def test_stage_file_skips_when_no_repo(tmp_path):
    mgr = _make_manager(tmp_path, {})
    with patch("ster.git_manager._git") as mock_git:
        mgr.stage_file()
    mock_git.assert_not_called()


def test_stage_path_calls_git_add(tmp_path):
    mgr = _make_manager(tmp_path, {"repo_path": str(tmp_path)})
    some_file = tmp_path / "other.ttl"
    with patch("ster.git_manager._git") as mock_git:
        mock_git.return_value = MagicMock(returncode=0)
        mgr.stage_path(some_file)
    mock_git.assert_called_once_with("add", str(some_file), cwd=tmp_path)


def test_stage_path_skips_when_no_repo(tmp_path):
    mgr = _make_manager(tmp_path, {})
    with patch("ster.git_manager._git") as mock_git:
        mgr.stage_path(tmp_path / "x.ttl")
    mock_git.assert_not_called()


# ── has_staged_changes ────────────────────────────────────────────────────────


def test_has_staged_changes_true(tmp_path):
    mgr = _make_manager(tmp_path, {"repo_path": str(tmp_path)})
    mock_result = MagicMock(returncode=0, stdout="tax.ttl\n")
    with patch("ster.git_manager._git", return_value=mock_result):
        assert mgr.has_staged_changes() is True


def test_has_staged_changes_false_empty(tmp_path):
    mgr = _make_manager(tmp_path, {"repo_path": str(tmp_path)})
    mock_result = MagicMock(returncode=0, stdout="")
    with patch("ster.git_manager._git", return_value=mock_result):
        assert mgr.has_staged_changes() is False


def test_has_staged_changes_false_no_repo(tmp_path):
    mgr = _make_manager(tmp_path, {})
    assert mgr.has_staged_changes() is False


def test_has_staged_changes_false_on_error(tmp_path):
    mgr = _make_manager(tmp_path, {"repo_path": str(tmp_path)})
    mock_result = MagicMock(returncode=128, stdout="")
    with patch("ster.git_manager._git", return_value=mock_result):
        assert mgr.has_staged_changes() is False


# ── record_head ───────────────────────────────────────────────────────────────


def test_record_head_saves_sha(tmp_path, monkeypatch):
    monkeypatch.setattr(gm, "CONFIG_FILE", tmp_path / "cfg.json")
    monkeypatch.setattr(gm, "CONFIG_DIR", tmp_path)
    mgr = _make_manager(tmp_path, {"repo_path": str(tmp_path)})
    mock_result = MagicMock(returncode=0, stdout="abc123\n")
    with patch("ster.git_manager._git", return_value=mock_result):
        mgr.record_head()
    assert mgr._cfg.get("last_commit") == "abc123"


def test_record_head_skips_on_failure(tmp_path):
    mgr = _make_manager(tmp_path, {"repo_path": str(tmp_path)})
    mock_result = MagicMock(returncode=1, stdout="")
    with patch("ster.git_manager._git", return_value=mock_result):
        mgr.record_head()
    assert "last_commit" not in mgr._cfg


def test_record_head_no_repo(tmp_path):
    mgr = _make_manager(tmp_path, {})
    with patch("ster.git_manager._git") as mock_git:
        mgr.record_head()
    mock_git.assert_not_called()


# ── pre_edit_check ────────────────────────────────────────────────────────────


def test_pre_edit_check_not_configured(tmp_path):
    mgr = _make_manager(tmp_path, {})
    assert mgr.pre_edit_check() is None


def test_pre_edit_check_no_remote(tmp_path):
    mgr = _make_manager(tmp_path, {"repo_path": str(tmp_path)})
    assert mgr.pre_edit_check() is None


def test_pre_edit_check_up_to_date(tmp_path):
    mgr = _make_manager(tmp_path, {"repo_path": str(tmp_path), "remote_url": "https://x.com/r"})

    def git_side(*args, **kwargs):
        if args[0] == "fetch":
            return MagicMock(returncode=0, stdout="")
        if args[0] == "rev-list":
            return MagicMock(returncode=0, stdout="0\n")
        return MagicMock(returncode=0, stdout="")

    with patch("ster.git_manager._git", side_effect=git_side):
        result = mgr.pre_edit_check()
    assert result is None


def test_pre_edit_check_rev_list_error(tmp_path):
    mgr = _make_manager(tmp_path, {"repo_path": str(tmp_path), "remote_url": "https://x.com/r"})

    def git_side(*args, **kwargs):
        return MagicMock(returncode=1, stdout="")

    with patch("ster.git_manager._git", side_effect=git_side):
        result = mgr.pre_edit_check()
    assert result is None


# ── commit_new_taxonomy ───────────────────────────────────────────────────────


def test_commit_new_taxonomy_success(tmp_path, monkeypatch):
    monkeypatch.setattr(gm, "CONFIG_FILE", tmp_path / "cfg.json")
    monkeypatch.setattr(gm, "CONFIG_DIR", tmp_path)
    mgr = _make_manager(tmp_path, {"repo_path": str(tmp_path)})

    def git_side(*args, **kwargs):
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("ster.git_manager._git", side_effect=git_side):
        mgr.commit_new_taxonomy("Initial commit")


def test_commit_new_taxonomy_nothing_to_commit(tmp_path):
    mgr = _make_manager(tmp_path, {"repo_path": str(tmp_path)})

    def git_side(*args, **kwargs):
        if args[0] == "commit":
            return MagicMock(returncode=1, stdout="nothing to commit", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("ster.git_manager._git", side_effect=git_side):
        mgr.commit_new_taxonomy("Initial commit")  # no crash


def test_commit_new_taxonomy_commit_error(tmp_path):
    mgr = _make_manager(tmp_path, {"repo_path": str(tmp_path)})

    def git_side(*args, **kwargs):
        if args[0] == "commit":
            return MagicMock(returncode=1, stdout="", stderr="some error")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("ster.git_manager._git", side_effect=git_side):
        mgr.commit_new_taxonomy("Initial commit")  # no crash


def test_commit_new_taxonomy_no_repo(tmp_path):
    mgr = _make_manager(tmp_path, {})
    with patch("ster.git_manager._git") as mock_git:
        mgr.commit_new_taxonomy("msg")
    mock_git.assert_not_called()


# ── _push_direct ─────────────────────────────────────────────────────────────


def test_push_direct_success(tmp_path):
    mgr = _make_manager(tmp_path)
    with patch("ster.git_manager._git", return_value=MagicMock(returncode=0, stderr="")):
        mgr._push_direct(tmp_path, "main")


def test_push_direct_failure(tmp_path):
    mgr = _make_manager(tmp_path)
    with patch("ster.git_manager._git", return_value=MagicMock(returncode=1, stderr="rejected")):
        mgr._push_direct(tmp_path, "main")  # no crash, prints error


# ── _parse_github_owner_repo ──────────────────────────────────────────────────


def test_parse_github_https():
    result = GitManager._parse_github_owner_repo("https://github.com/alice/myrepo")
    assert result == ("alice", "myrepo")


def test_parse_github_https_dot_git():
    result = GitManager._parse_github_owner_repo("https://github.com/alice/myrepo.git")
    assert result == ("alice", "myrepo")


def test_parse_github_ssh():
    result = GitManager._parse_github_owner_repo("git@github.com:alice/myrepo.git")
    assert result == ("alice", "myrepo")


def test_parse_non_github_returns_none():
    result = GitManager._parse_github_owner_repo("https://gitlab.com/alice/myrepo")
    assert result is None


def test_parse_empty_returns_none():
    result = GitManager._parse_github_owner_repo("")
    assert result is None


# ── _get_remote_url ───────────────────────────────────────────────────────────


def test_get_remote_url_success(tmp_path):
    mgr = _make_manager(tmp_path)
    mock = MagicMock(returncode=0, stdout="https://github.com/u/r\n")
    with patch("ster.git_manager._git", return_value=mock):
        url = mgr._get_remote_url(tmp_path)
    assert url == "https://github.com/u/r"


def test_get_remote_url_none_on_error(tmp_path):
    mgr = _make_manager(tmp_path)
    mock = MagicMock(returncode=128, stdout="")
    with patch("ster.git_manager._git", return_value=mock):
        url = mgr._get_remote_url(tmp_path)
    assert url is None


# ── _detect_main_branch ───────────────────────────────────────────────────────


def test_detect_main_branch_main(tmp_path):
    mgr = _make_manager(tmp_path, {})

    def git_side(*args, **kwargs):
        if "main" in args:
            return MagicMock(returncode=0, stdout="main\n")
        return MagicMock(returncode=1, stdout="")

    with patch("ster.git_manager._git", side_effect=git_side):
        mgr._detect_main_branch(tmp_path)
    assert mgr._cfg.get("main_branch") == "main"


def test_detect_main_branch_master(tmp_path):
    mgr = _make_manager(tmp_path, {})

    def git_side(*args, **kwargs):
        if "master" in args:
            return MagicMock(returncode=0, stdout="master\n")
        return MagicMock(returncode=1, stdout="")

    with patch("ster.git_manager._git", side_effect=git_side):
        mgr._detect_main_branch(tmp_path)
    assert mgr._cfg.get("main_branch") == "master"


def test_detect_main_branch_fallback(tmp_path):
    mgr = _make_manager(tmp_path, {})

    def git_side(*args, **kwargs):
        if args[0] == "branch":
            return MagicMock(returncode=0, stdout="develop\n")
        return MagicMock(returncode=1, stdout="")

    with patch("ster.git_manager._git", side_effect=git_side):
        mgr._detect_main_branch(tmp_path)
    # Should fall through to branch --show-current
    assert mgr._cfg.get("main_branch") in ("develop", "main")


# ── _find_repo_root ───────────────────────────────────────────────────────────


def test_find_repo_root_found(tmp_path):
    mgr = _make_manager(tmp_path)
    mock = MagicMock(returncode=0, stdout=str(tmp_path) + "\n")
    with patch("ster.git_manager._git", return_value=mock):
        result = mgr._find_repo_root()
    assert result == tmp_path


def test_find_repo_root_not_found(tmp_path):
    mgr = _make_manager(tmp_path)
    mock = MagicMock(returncode=128, stdout="")
    with patch("ster.git_manager._git", return_value=mock):
        result = mgr._find_repo_root()
    assert result is None


# ── _persist ──────────────────────────────────────────────────────────────────


def test_persist_saves_config(tmp_path, monkeypatch):
    monkeypatch.setattr(gm, "CONFIG_FILE", tmp_path / "cfg.json")
    monkeypatch.setattr(gm, "CONFIG_DIR", tmp_path)
    mgr = _make_manager(tmp_path, {"repo_path": str(tmp_path)})
    mgr._persist()
    saved = json.loads((tmp_path / "cfg.json").read_text())
    assert str(mgr.taxonomy_path) in saved


# ── _link_existing_repo ───────────────────────────────────────────────────────


def test_link_existing_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(gm, "CONFIG_FILE", tmp_path / "cfg.json")
    monkeypatch.setattr(gm, "CONFIG_DIR", tmp_path)
    mgr = _make_manager(tmp_path, {})

    def git_side(*args, **kwargs):
        if args[0] == "remote" and "get-url" in args:
            return MagicMock(returncode=0, stdout="https://github.com/u/r\n")
        if args[0] == "rev-parse":
            return MagicMock(returncode=0, stdout="main\n")
        return MagicMock(returncode=1, stdout="")

    with patch("ster.git_manager._git", side_effect=git_side):
        mgr._link_existing_repo(tmp_path)

    assert mgr._cfg["repo_path"] == str(tmp_path)
    assert mgr._cfg["remote_url"] == "https://github.com/u/r"


# ── _ensure_on_branch ────────────────────────────────────────────────────────


def test_ensure_on_branch_already_current(tmp_path):
    calls = []

    def git_side(*args, **kwargs):
        calls.append(args[0])
        return MagicMock(returncode=0, stdout="main\n")

    with patch("ster.git_manager._git", side_effect=git_side):
        GitManager._ensure_on_branch(tmp_path, "main")
    # Only one git call (branch --show-current); no checkout
    assert "checkout" not in calls


def test_ensure_on_branch_exists_checks_out(tmp_path):
    calls = []

    def git_side(*args, **kwargs):
        calls.append(args)
        if args[0] == "branch":
            return MagicMock(returncode=0, stdout="dev\n")
        if args[0] == "rev-parse":
            return MagicMock(returncode=0, stdout="")
        return MagicMock(returncode=0, stdout="")

    with patch("ster.git_manager._git", side_effect=git_side):
        GitManager._ensure_on_branch(tmp_path, "main")
    assert any(a[0] == "checkout" and "-b" not in a for a in calls)


def test_ensure_on_branch_creates_new(tmp_path):
    calls = []

    def git_side(*args, **kwargs):
        calls.append(args)
        if args[0] == "branch":
            return MagicMock(returncode=0, stdout="dev\n")
        if args[0] == "rev-parse":
            return MagicMock(returncode=1, stdout="")
        return MagicMock(returncode=0, stdout="")

    with patch("ster.git_manager._git", side_effect=git_side):
        GitManager._ensure_on_branch(tmp_path, "main")
    assert any(a[0] == "checkout" and "-b" in a for a in calls)


# ── _detect_remote_default_branch ────────────────────────────────────────────


def test_detect_remote_default_branch_from_show(tmp_path):
    mgr = _make_manager(tmp_path, {})

    def git_side(*args, **kwargs):
        if args[0] == "remote" and "show" in args:
            return MagicMock(returncode=0, stdout="  HEAD branch: develop\n")
        return MagicMock(returncode=1, stdout="")

    with patch("ster.git_manager._git", side_effect=git_side):
        result = mgr._detect_remote_default_branch(tmp_path)
    assert result == "develop"


def test_detect_remote_default_branch_fallback_main(tmp_path):
    mgr = _make_manager(tmp_path, {})

    def git_side(*args, **kwargs):
        if args[0] == "remote":
            return MagicMock(returncode=0, stdout="no HEAD info\n")
        if args[0] == "rev-parse" and "main" in str(args):
            return MagicMock(returncode=0, stdout="")
        return MagicMock(returncode=1, stdout="")

    with patch("ster.git_manager._git", side_effect=git_side):
        result = mgr._detect_remote_default_branch(tmp_path)
    assert result == "main"


def test_detect_remote_default_branch_final_fallback(tmp_path):
    mgr = _make_manager(tmp_path, {})
    with patch("ster.git_manager._git", return_value=MagicMock(returncode=1, stdout="")):
        result = mgr._detect_remote_default_branch(tmp_path)
    assert result == "main"


# ── _local_branch ────────────────────────────────────────────────────────────


def test_local_branch_returns_current(tmp_path):
    with patch("ster.git_manager._git", return_value=MagicMock(returncode=0, stdout="feature\n")):
        result = GitManager._local_branch(tmp_path)
    assert result == "feature"


def test_local_branch_fallback_main_when_empty(tmp_path):
    with patch("ster.git_manager._git", return_value=MagicMock(returncode=0, stdout="")):
        result = GitManager._local_branch(tmp_path)
    assert result == "main"


# ── _create_pr ────────────────────────────────────────────────────────────────


def test_create_pr_gh_cli_success(tmp_path):
    mgr = _make_manager(tmp_path, {"repo_path": str(tmp_path)})
    mock_result = MagicMock(returncode=0, stdout="https://github.com/u/r/pull/1\n")
    with patch("subprocess.run", return_value=mock_result):
        url = mgr._create_pr(tmp_path, "feat", "main", "My PR", "body")
    assert url == "https://github.com/u/r/pull/1"


def test_create_pr_gh_cli_fail_no_token(tmp_path):
    mgr = _make_manager(tmp_path, {"repo_path": str(tmp_path), "remote_url": ""})
    mock_fail = MagicMock(returncode=1, stdout="")
    with (
        patch("subprocess.run", return_value=mock_fail),
        patch.object(mgr, "_get_github_token", return_value=None),
    ):
        url = mgr._create_pr(tmp_path, "feat", "main", "My PR", "body")
    assert url is None


def test_create_pr_gh_cli_fail_no_github_owner(tmp_path):
    mgr = _make_manager(
        tmp_path, {"repo_path": str(tmp_path), "remote_url": "https://gitlab.com/u/r"}
    )
    mock_fail = MagicMock(returncode=1, stdout="")
    with (
        patch("subprocess.run", return_value=mock_fail),
        patch.object(mgr, "_get_github_token", return_value="tok"),
    ):
        url = mgr._create_pr(tmp_path, "feat", "main", "My PR", "body")
    assert url is None


# ── pre_edit_check — pull path ────────────────────────────────────────────────


def test_pre_edit_check_user_declines_pull(tmp_path, monkeypatch):
    mgr = _make_manager(
        tmp_path,
        {"repo_path": str(tmp_path), "remote_url": "https://github.com/u/r", "main_branch": "main"},
    )

    def git_side(*args, **kwargs):
        if "fetch" in args:
            return MagicMock(returncode=0, stdout="")
        if "rev-list" in args:
            return MagicMock(returncode=0, stdout="1\n")
        return MagicMock(returncode=0, stdout="")

    monkeypatch.setattr(gm, "_git", git_side)
    monkeypatch.setattr("rich.prompt.Confirm.ask", lambda *a, **kw: False)
    assert mgr.pre_edit_check() is None


def test_pre_edit_check_pulls_and_returns_diff(tmp_path, monkeypatch):
    mgr = _make_manager(
        tmp_path,
        {"repo_path": str(tmp_path), "remote_url": "https://github.com/u/r", "main_branch": "main"},
    )

    def git_side(*args, **kwargs):
        if "fetch" in args:
            return MagicMock(returncode=0, stdout="")
        if "rev-list" in args:
            return MagicMock(returncode=0, stdout="2\n")
        if "rev-parse" in args:
            return MagicMock(returncode=0, stdout="abc123\n")
        if "pull" in args:
            return MagicMock(returncode=0, stdout="")
        if "diff" in args:
            return MagicMock(returncode=0, stdout="+added line\n")
        return MagicMock(returncode=0, stdout="")

    monkeypatch.setattr(gm, "_git", git_side)
    monkeypatch.setattr("rich.prompt.Confirm.ask", lambda *a, **kw: True)
    result = mgr.pre_edit_check()
    assert result is not None
    assert "added" in result


def test_pre_edit_check_pull_fails(tmp_path, monkeypatch):
    mgr = _make_manager(
        tmp_path,
        {"repo_path": str(tmp_path), "remote_url": "https://github.com/u/r", "main_branch": "main"},
    )

    def git_side(*args, **kwargs):
        if "fetch" in args:
            return MagicMock(returncode=0, stdout="")
        if "rev-list" in args:
            return MagicMock(returncode=0, stdout="1\n")
        if "rev-parse" in args:
            return MagicMock(returncode=0, stdout="abc\n")
        if "pull" in args:
            return MagicMock(returncode=1, stderr="conflict")
        return MagicMock(returncode=0, stdout="")

    monkeypatch.setattr(gm, "_git", git_side)
    monkeypatch.setattr("rich.prompt.Confirm.ask", lambda *a, **kw: True)
    assert mgr.pre_edit_check() is None


def test_pre_edit_check_invalid_behind_count(tmp_path, monkeypatch):
    mgr = _make_manager(
        tmp_path,
        {"repo_path": str(tmp_path), "remote_url": "https://github.com/u/r", "main_branch": "main"},
    )

    def git_side(*args, **kwargs):
        if "fetch" in args:
            return MagicMock(returncode=0, stdout="")
        if "rev-list" in args:
            return MagicMock(returncode=0, stdout="not-a-number\n")
        return MagicMock(returncode=0, stdout="")

    monkeypatch.setattr(gm, "_git", git_side)
    assert mgr.pre_edit_check() is None


# ── _git direct call (line 59) ────────────────────────────────────────────────


def test_git_function_runs_subprocess(tmp_path):
    from ster.git_manager import _git

    r = _git("rev-parse", "--show-toplevel", cwd=tmp_path)
    assert hasattr(r, "returncode")
    assert hasattr(r, "stdout")


# ── setup() early returns ─────────────────────────────────────────────────────


def test_setup_git_not_available(tmp_path):
    mgr = _make_manager(tmp_path)
    with patch("ster.git_manager._git_available", return_value=False):
        result = mgr.setup()
    assert result is False


def test_setup_not_enabled(tmp_path):
    mgr = _make_manager(tmp_path, {"git_enabled": False})
    with patch("ster.git_manager._git_available", return_value=True):
        result = mgr.setup()
    assert result is False


def test_setup_auto_links_existing_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(gm, "CONFIG_FILE", tmp_path / "cfg.json")
    monkeypatch.setattr(gm, "CONFIG_DIR", tmp_path)
    mgr = _make_manager(tmp_path, {})

    with (
        patch("ster.git_manager._git_available", return_value=True),
        patch.object(mgr, "_find_repo_root", return_value=tmp_path),
        patch.object(mgr, "_link_existing_repo"),
        patch.object(mgr, "_ask_branch_strategy"),
    ):
        mgr._cfg["branch_strategy"] = "direct"  # skip _ask_branch_strategy
        result = mgr.setup()
    assert result is True


def test_setup_auto_links_asks_strategy_if_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(gm, "CONFIG_FILE", tmp_path / "cfg.json")
    monkeypatch.setattr(gm, "CONFIG_DIR", tmp_path)
    mgr = _make_manager(tmp_path, {})

    asked = []

    with (
        patch("ster.git_manager._git_available", return_value=True),
        patch.object(mgr, "_find_repo_root", return_value=tmp_path),
        patch.object(mgr, "_link_existing_repo"),
        patch.object(mgr, "_ask_branch_strategy", side_effect=lambda: asked.append(1)),
    ):
        result = mgr.setup()
    assert result is True
    assert asked  # _ask_branch_strategy was called


# ── pre_edit_check — repo path missing ────────────────────────────────────────


def test_pre_edit_check_repo_path_nonexistent(tmp_path):
    """Configured but repo directory has been deleted — hits the `not repo` return."""
    mgr = _make_manager(tmp_path, {"repo_path": str(tmp_path / "gone"), "remote_url": "x"})
    assert mgr.pre_edit_check() is None


# ── pre_edit_check — pull succeeds with no diff output ────────────────────────


def test_pre_edit_check_pull_succeeds_no_diff(tmp_path, monkeypatch):
    mgr = _make_manager(
        tmp_path,
        {"repo_path": str(tmp_path), "remote_url": "https://x.com/r", "main_branch": "main"},
    )

    def git_side(*args, **kwargs):
        if "fetch" in args:
            return MagicMock(returncode=0, stdout="")
        if "rev-list" in args:
            return MagicMock(returncode=0, stdout="1\n")
        if "rev-parse" in args:
            return MagicMock(returncode=0, stdout="abc\n")
        if "pull" in args:
            return MagicMock(returncode=0, stdout="")
        if "diff" in args:
            return MagicMock(returncode=0, stdout="")  # empty diff
        return MagicMock(returncode=0, stdout="")

    monkeypatch.setattr(gm, "_git", git_side)
    monkeypatch.setattr("rich.prompt.Confirm.ask", lambda *a, **kw: True)
    result = mgr.pre_edit_check()
    assert result is None  # empty diff → returns None at line 223


# ── commit_and_push() early returns ───────────────────────────────────────────


def test_commit_and_push_not_configured(tmp_path):
    mgr = _make_manager(tmp_path, {})
    with patch("ster.git_manager._git") as mock_git:
        mgr.commit_and_push()
    mock_git.assert_not_called()


def test_commit_and_push_no_staged_changes(tmp_path):
    mgr = _make_manager(tmp_path, {"repo_path": str(tmp_path)})
    with patch.object(mgr, "has_staged_changes", return_value=False):
        mgr.commit_and_push()  # should return silently


def test_commit_and_push_commit_fails(tmp_path, monkeypatch):
    mgr = _make_manager(tmp_path, {"repo_path": str(tmp_path), "remote_url": "https://x.com/r"})
    monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **kw: kw.get("default", "msg"))

    def git_side(*args, **kwargs):
        if args[0] == "commit":
            return MagicMock(returncode=1, stdout="", stderr="lock")
        return MagicMock(returncode=0, stdout="", stderr="")

    with (
        patch.object(mgr, "has_staged_changes", return_value=True),
        patch("ster.git_manager._git", side_effect=git_side),
    ):
        mgr.commit_and_push()  # no crash


def test_commit_and_push_direct_no_remote(tmp_path, monkeypatch):
    mgr = _make_manager(tmp_path, {"repo_path": str(tmp_path)})
    monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **kw: kw.get("default", "msg"))

    def git_side(*args, **kwargs):
        return MagicMock(returncode=0, stdout="", stderr="")

    with (
        patch.object(mgr, "has_staged_changes", return_value=True),
        patch("ster.git_manager._git", side_effect=git_side),
    ):
        mgr.commit_and_push()  # commits locally; no push


def test_commit_and_push_direct_push(tmp_path, monkeypatch):
    push_called = []
    mgr = _make_manager(
        tmp_path,
        {
            "repo_path": str(tmp_path),
            "remote_url": "https://x.com/r",
            "main_branch": "main",
            "branch_strategy": "direct",
        },
    )
    monkeypatch.setattr(gm, "CONFIG_FILE", tmp_path / "cfg.json")
    monkeypatch.setattr(gm, "CONFIG_DIR", tmp_path)

    def git_side(*args, **kwargs):
        if args[0] == "push":
            push_called.append(args)
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **kw: "1")

    with (
        patch.object(mgr, "has_staged_changes", return_value=True),
        patch("ster.git_manager._git", side_effect=git_side),
    ):
        mgr.commit_and_push()
    assert push_called


# ── _pull_remote_into_dir ─────────────────────────────────────────────────────


def test_pull_remote_into_dir_branch_not_exists(tmp_path):
    mgr = _make_manager(tmp_path, {})
    calls = []

    def git_side(*args, **kwargs):
        calls.append(args)
        if args[0] == "rev-parse":  # branch --verify
            return MagicMock(returncode=1, stdout="")
        return MagicMock(returncode=0, stdout="")

    with patch("ster.git_manager._git", side_effect=git_side):
        result = mgr._pull_remote_into_dir(tmp_path, "main")
    assert result is True
    assert any("-b" in a for a in calls)


def test_pull_remote_into_dir_branch_exists_ff_ok(tmp_path):
    mgr = _make_manager(tmp_path, {})
    calls = []

    def git_side(*args, **kwargs):
        calls.append(args)
        if args[0] == "rev-parse":
            return MagicMock(returncode=0, stdout="")
        return MagicMock(returncode=0, stdout="")

    with patch("ster.git_manager._git", side_effect=git_side):
        result = mgr._pull_remote_into_dir(tmp_path, "main")
    assert result is True
    assert any("--ff-only" in a for a in calls)


def test_pull_remote_into_dir_ff_fails_fallback(tmp_path):
    mgr = _make_manager(tmp_path, {})
    calls = []

    def git_side(*args, **kwargs):
        calls.append(args)
        if args[0] == "rev-parse":
            return MagicMock(returncode=0, stdout="")
        if args[0] == "pull" and "--ff-only" in args:
            return MagicMock(returncode=1, stdout="", stderr="diverged")
        return MagicMock(returncode=0, stdout="")

    with patch("ster.git_manager._git", side_effect=git_side):
        result = mgr._pull_remote_into_dir(tmp_path, "main")
    assert result is True
    assert any("--allow-unrelated-histories" in a for a in calls)


def test_pull_remote_into_dir_all_pull_fail(tmp_path):
    mgr = _make_manager(tmp_path, {})

    def git_side(*args, **kwargs):
        if args[0] == "rev-parse":
            return MagicMock(returncode=0, stdout="")
        if args[0] == "pull":
            return MagicMock(returncode=1, stdout="", stderr="err")
        return MagicMock(returncode=0, stdout="")

    with patch("ster.git_manager._git", side_effect=git_side):
        result = mgr._pull_remote_into_dir(tmp_path, "main")
    assert result is False


# ── _push_local_to_remote ─────────────────────────────────────────────────────


def test_push_local_to_remote_success_no_staged(tmp_path):
    mgr = _make_manager(tmp_path, {})
    calls = []

    def git_side(*args, **kwargs):
        calls.append(args)
        if args[0] == "diff":
            return MagicMock(returncode=0, stdout="")  # nothing staged
        return MagicMock(returncode=0, stdout="main\n")

    with patch("ster.git_manager._git", side_effect=git_side):
        result = mgr._push_local_to_remote(tmp_path, "main", force=False)
    assert result is True
    assert any("push" in a for a in calls)


def test_push_local_to_remote_success_with_staged(tmp_path):
    mgr = _make_manager(tmp_path, {})
    calls = []

    def git_side(*args, **kwargs):
        calls.append(args)
        if args[0] == "diff":
            return MagicMock(returncode=0, stdout="file.ttl\n")  # staged
        return MagicMock(returncode=0, stdout="main\n")

    with patch("ster.git_manager._git", side_effect=git_side):
        result = mgr._push_local_to_remote(tmp_path, "main", force=False)
    assert result is True
    assert any(a[0] == "commit" for a in calls)


def test_push_local_to_remote_force(tmp_path):
    mgr = _make_manager(tmp_path, {})
    calls = []

    def git_side(*args, **kwargs):
        calls.append(args)
        if args[0] == "diff":
            return MagicMock(returncode=0, stdout="")
        return MagicMock(returncode=0, stdout="main\n")

    with patch("ster.git_manager._git", side_effect=git_side):
        result = mgr._push_local_to_remote(tmp_path, "main", force=True)
    assert result is True
    assert any("--force" in a for a in calls)


def test_push_local_to_remote_push_fails(tmp_path):
    mgr = _make_manager(tmp_path, {})

    def git_side(*args, **kwargs):
        if args[0] == "diff":
            return MagicMock(returncode=0, stdout="")
        if args[0] == "branch":
            return MagicMock(returncode=0, stdout="main\n")
        if args[0] == "push":
            return MagicMock(returncode=1, stdout="", stderr="rejected")
        return MagicMock(returncode=0, stdout="main\n")

    with (
        patch("ster.git_manager._git", side_effect=git_side),
        patch("rich.prompt.Confirm.ask", return_value=False),
    ):
        result = mgr._push_local_to_remote(tmp_path, "main", force=False)
    assert result is False


# ── _ask_branch_strategy ──────────────────────────────────────────────────────


def test_ask_branch_strategy_direct(tmp_path, monkeypatch):
    monkeypatch.setattr(gm, "CONFIG_FILE", tmp_path / "cfg.json")
    monkeypatch.setattr(gm, "CONFIG_DIR", tmp_path)
    mgr = _make_manager(tmp_path, {})
    monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **kw: "1")
    mgr._ask_branch_strategy()
    assert mgr._cfg["branch_strategy"] == "direct"


def test_ask_branch_strategy_pr(tmp_path, monkeypatch):
    monkeypatch.setattr(gm, "CONFIG_FILE", tmp_path / "cfg.json")
    monkeypatch.setattr(gm, "CONFIG_DIR", tmp_path)
    mgr = _make_manager(tmp_path, {})
    monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **kw: "2")
    mgr._ask_branch_strategy()
    assert mgr._cfg["branch_strategy"] == "pr"


# ── _create_pr REST API path ──────────────────────────────────────────────────


def test_create_pr_rest_api_success(tmp_path):
    mgr = _make_manager(
        tmp_path, {"repo_path": str(tmp_path), "remote_url": "https://github.com/alice/repo"}
    )
    mock_fail = MagicMock(returncode=1, stdout="")
    fake_response = MagicMock()
    fake_response.__enter__ = lambda s: s
    fake_response.__exit__ = MagicMock(return_value=False)
    fake_response.read.return_value = b'{"html_url": "https://github.com/alice/repo/pull/42"}'

    with (
        patch("subprocess.run", return_value=mock_fail),
        patch.object(mgr, "_get_github_token", return_value="tok"),
        patch("urllib.request.urlopen", return_value=fake_response),
    ):
        url = mgr._create_pr(tmp_path, "feat", "main", "My PR", "body")
    assert url == "https://github.com/alice/repo/pull/42"


def test_create_pr_rest_api_http_error(tmp_path):
    import urllib.error

    mgr = _make_manager(
        tmp_path, {"repo_path": str(tmp_path), "remote_url": "https://github.com/alice/repo"}
    )
    mock_fail = MagicMock(returncode=1, stdout="")

    with (
        patch("subprocess.run", return_value=mock_fail),
        patch.object(mgr, "_get_github_token", return_value="tok"),
        patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(None, 422, "Unprocessable", {}, None),
        ),
    ):
        url = mgr._create_pr(tmp_path, "feat", "main", "My PR", "body")
    assert url is None


def test_create_pr_rest_api_generic_exception(tmp_path):
    mgr = _make_manager(
        tmp_path, {"repo_path": str(tmp_path), "remote_url": "https://github.com/alice/repo"}
    )
    mock_fail = MagicMock(returncode=1, stdout="")

    with (
        patch("subprocess.run", return_value=mock_fail),
        patch.object(mgr, "_get_github_token", return_value="tok"),
        patch("urllib.request.urlopen", side_effect=OSError("network")),
    ):
        url = mgr._create_pr(tmp_path, "feat", "main", "My PR", "body")
    assert url is None


# ── _get_github_token ─────────────────────────────────────────────────────────


def test_get_github_token_from_gh_cli(tmp_path):
    mgr = _make_manager(tmp_path, {})
    with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="ghp_abc\n")):
        token = mgr._get_github_token()
    assert token == "ghp_abc"


def test_get_github_token_from_stored(tmp_path):
    mgr = _make_manager(tmp_path, {"github_token": "stored_tok"})
    with patch("subprocess.run", return_value=MagicMock(returncode=1, stdout="")):
        token = mgr._get_github_token()
    assert token == "stored_tok"


def test_get_github_token_none_when_skipped(tmp_path, monkeypatch):
    mgr = _make_manager(tmp_path, {})
    monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **kw: "")
    with patch("subprocess.run", return_value=MagicMock(returncode=1, stdout="")):
        token = mgr._get_github_token()
    assert token is None


# ── commit_new_taxonomy — remote push ─────────────────────────────────────────


def test_commit_new_taxonomy_pushes_with_remote(tmp_path, monkeypatch):
    mgr = _make_manager(
        tmp_path,
        {
            "repo_path": str(tmp_path),
            "remote_url": "https://github.com/u/r",
            "main_branch": "main",
        },
    )

    push_called = []

    def git_side(*args, **kwargs):
        if args[0] == "add":
            return MagicMock(returncode=0, stdout="")
        if args[0] == "commit":
            return MagicMock(returncode=0, stdout="", stderr="")
        if args[0] == "push":
            push_called.append(args)
            return MagicMock(returncode=0, stdout="")
        return MagicMock(returncode=0, stdout="")

    monkeypatch.setattr(gm, "_git", git_side)
    mgr.commit_new_taxonomy("chore: add taxonomy")
    assert push_called, "push should have been called when remote_url is set"
