"""Unit tests for ster/publish_state.py — state file logic."""

from __future__ import annotations

import json
from pathlib import Path

from ster.publish_state import (
    LAST_FILE,
    STATE_FILE,
    detect_state,
    finalise_state,
    init_state,
    record_step,
)


def _make_state_file(tmp_path: Path, data: dict) -> None:
    (tmp_path / STATE_FILE).write_text(json.dumps(data))


# ── init + record ─────────────────────────────────────────────────────────────


def test_state_written_atomically(tmp_path: Path) -> None:
    init_state(tmp_path, "stable", "1.2.0+20260528.abc1234", "1.2.0", None, "onto.ttl", "ontology")
    assert (tmp_path / STATE_FILE).exists()
    data = json.loads((tmp_path / STATE_FILE).read_text())
    assert data["status"] == "in_progress"


def test_state_records_done_step(tmp_path: Path) -> None:
    state = init_state(
        tmp_path, "stable", "1.2.0+20260528.abc1234", "1.2.0", None, "onto.ttl", "ontology"
    )
    record_step(tmp_path, state, "patch_version", "done")
    data = json.loads((tmp_path / STATE_FILE).read_text())
    assert data["steps"]["patch_version"] == "done"


def test_state_records_failed_step(tmp_path: Path) -> None:
    state = init_state(
        tmp_path, "stable", "1.2.0+20260528.abc1234", "1.2.0", None, "onto.ttl", "ontology"
    )
    record_step(tmp_path, state, "git_tag", "failed")
    data = json.loads((tmp_path / STATE_FILE).read_text())
    assert data["steps"]["git_tag"] == "failed"


# ── finalise ──────────────────────────────────────────────────────────────────


def test_state_renamed_to_last_on_success(tmp_path: Path) -> None:
    state = init_state(
        tmp_path, "stable", "1.2.0+20260528.abc1234", "1.2.0", None, "onto.ttl", "ontology"
    )
    finalise_state(tmp_path, state, commit_sha="abc123")
    assert not (tmp_path / STATE_FILE).exists()
    assert (tmp_path / LAST_FILE).exists()


def test_last_json_has_status_done(tmp_path: Path) -> None:
    state = init_state(
        tmp_path, "stable", "1.2.0+20260528.abc1234", "1.2.0", None, "onto.ttl", "ontology"
    )
    finalise_state(tmp_path, state, commit_sha="abc123")
    data = json.loads((tmp_path / LAST_FILE).read_text())
    assert data["status"] == "done"


def test_last_json_has_commit_sha(tmp_path: Path) -> None:
    state = init_state(
        tmp_path, "stable", "1.2.0+20260528.abc1234", "1.2.0", None, "onto.ttl", "ontology"
    )
    finalise_state(tmp_path, state, commit_sha="def5678")
    data = json.loads((tmp_path / LAST_FILE).read_text())
    assert data["commit_sha"] == "def5678"


def test_last_json_has_channel(tmp_path: Path) -> None:
    state = init_state(
        tmp_path, "stable", "1.2.0+20260528.abc1234", "1.2.0", None, "onto.ttl", "ontology"
    )
    finalise_state(tmp_path, state, commit_sha="abc123")
    data = json.loads((tmp_path / LAST_FILE).read_text())
    assert data["channel"] == "stable"


# ── detect_state ──────────────────────────────────────────────────────────────


def test_detect_in_progress_state(tmp_path: Path) -> None:
    _make_state_file(
        tmp_path,
        {
            "status": "in_progress",
            "channel": "stable",
            "version": "1.2.0+20260528.abc1234",
            "steps": {},
        },
    )
    status, _ = detect_state(tmp_path)
    assert status == "in_progress"


def test_detect_clean_state_no_file(tmp_path: Path) -> None:
    status, _ = detect_state(tmp_path)
    assert status == "clean"


def test_detect_clean_state_last_only(tmp_path: Path) -> None:
    (tmp_path / LAST_FILE).write_text(json.dumps({"status": "done"}))
    status, _ = detect_state(tmp_path)
    assert status == "clean"


# ── resume ────────────────────────────────────────────────────────────────────


def test_resume_skips_completed_steps(tmp_path: Path) -> None:
    state = init_state(
        tmp_path, "stable", "1.2.0+20260528.abc1234", "1.2.0", None, "onto.ttl", "ontology"
    )
    record_step(tmp_path, state, "pre_flight", "done")
    record_step(tmp_path, state, "lint", "done")

    from ster.publish_state import resume_from

    remaining = resume_from(state, ["pre_flight", "lint", "patch_version"])
    assert "pre_flight" not in remaining
    assert "lint" not in remaining
    assert "patch_version" in remaining
