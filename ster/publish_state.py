"""State file tracking for the ontology publication pipeline."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

STATE_FILE = ".ster-publish-state.json"
LAST_FILE = ".ster-publish-last.json"

ALL_STEPS = [
    "pre_flight",
    "lint",
    "patch_version",
    "write_artifacts",
    "git_commit",
    "git_tag",
    "git_push",
]


def init_state(
    work_dir: Path,
    channel: str,
    version: str,
    base_version: str,
    prior_version: str | None,
    file_path: str,
    publish_dir: str,
) -> dict:
    state: dict = {
        "status": "in_progress",
        "channel": channel,
        "version": version,
        "base_version": base_version,
        "prior_version": prior_version,
        "started_at": datetime.now(UTC).isoformat(),
        "file_path": file_path,
        "publish_dir": publish_dir,
        "steps": dict.fromkeys(ALL_STEPS, "pending"),
        "rollback": {
            "original_file_sha": None,
            "commit_sha": None,
            "repo_dir": None,
            "artifacts": [],
        },
    }
    _write_atomic(work_dir, state)
    return state


def record_step(work_dir: Path, state: dict, step: str, status: str) -> None:
    state["steps"][step] = status
    _write_atomic(work_dir, state)


def finalise_state(work_dir: Path, state: dict, commit_sha: str) -> None:
    state_path = work_dir / STATE_FILE
    last_path = work_dir / LAST_FILE
    receipt = {
        "status": "done",
        "channel": state["channel"],
        "version": state["version"],
        "base_version": state["base_version"],
        "finished_at": datetime.now(UTC).isoformat(),
        "commit_sha": commit_sha,
        "tag": f"v{state['base_version']}" if state["channel"] == "stable" else None,
        "artifacts": state["rollback"].get("artifacts", []),
    }
    last_path.write_text(json.dumps(receipt, indent=2))
    if state_path.exists():
        state_path.unlink()


def detect_state(work_dir: Path) -> tuple[str, dict | None]:
    state_path = work_dir / STATE_FILE
    if state_path.exists():
        try:
            data = json.loads(state_path.read_text())
            return data.get("status", "in_progress"), data
        except Exception:
            return "corrupt", None
    return "clean", None


def load_state(work_dir: Path) -> dict | None:
    state_path = work_dir / STATE_FILE
    if not state_path.exists():
        return None
    try:
        return json.loads(state_path.read_text())
    except Exception:
        return None


def resume_from(state: dict, steps: list[str]) -> list[str]:
    """Return only steps that are not yet 'done'."""
    done = {s for s, v in state["steps"].items() if v == "done"}
    return [s for s in steps if s not in done]


def rollback(work_dir: Path, state: dict) -> None:
    """Roll back completed steps in reverse order."""
    steps = state.get("steps", {})
    rollback_info = state.get("rollback", {})

    # Reverse order: git_tag → git_commit → write_artifacts → patch_version
    if steps.get("git_tag") == "done":
        base_version = state.get("base_version", "")
        repo_dir = rollback_info.get("repo_dir")
        if repo_dir and base_version:
            subprocess.run(
                ["git", "tag", "-d", f"v{base_version}"],
                cwd=repo_dir,
                capture_output=True,
            )

    if steps.get("git_commit") == "done":
        repo_dir = rollback_info.get("repo_dir")
        if repo_dir:
            subprocess.run(
                ["git", "reset", "--soft", "HEAD~1"],
                cwd=repo_dir,
                capture_output=True,
            )

    if steps.get("write_artifacts") == "done":
        publish_dir = state.get("publish_dir", "")
        base_version = state.get("base_version", "")
        if publish_dir and base_version:
            versioned = Path(publish_dir) / f"v{base_version}"
            if versioned.exists():
                shutil.rmtree(versioned)

    if steps.get("patch_version") == "done":
        repo_dir = rollback_info.get("repo_dir")
        file_path = state.get("file_path", "")
        if repo_dir and file_path:
            subprocess.run(
                ["git", "checkout", "HEAD", "--", file_path],
                cwd=repo_dir,
                capture_output=True,
            )

    state_path = work_dir / STATE_FILE
    if state_path.exists():
        state_path.unlink()


def _write_atomic(work_dir: Path, data: dict) -> None:
    tmp = work_dir / (STATE_FILE + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.rename(work_dir / STATE_FILE)
