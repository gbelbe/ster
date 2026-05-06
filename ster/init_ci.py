"""Scaffold a GitHub Actions CI workflow into a taxonomy / ontology project."""

from __future__ import annotations

import importlib.resources
from collections.abc import Callable
from pathlib import Path

_WORKFLOW_REL = Path(".github") / "workflows" / "taxonomy-ci.yml"
_ONTOLOGY_PATTERNS = ("*.ttl", "*.owl", "*.rdf", "*.n3", "*.jsonld")


def _read_template(name: str) -> str:
    ref = importlib.resources.files("ster") / "templates" / name
    return ref.read_text(encoding="utf-8")  # type: ignore[attr-defined]


def needs_ci(root: Path) -> bool:
    """Return True when *root* is a git-backed ontology project with no CI workflows at all."""
    if not (root / ".git").exists():
        return False
    if not any(p for pat in _ONTOLOGY_PATTERNS for p in root.glob(pat)):
        return False
    workflows_dir = root / ".github" / "workflows"
    return not (workflows_dir.exists() and any(workflows_dir.glob("*.yml")))


def scaffold(
    dest: Path,
    *,
    force: bool = False,
    include_config: bool = True,
) -> tuple[bool, bool]:
    """Write CI files into *dest* (the project root).

    Returns (workflow_written, config_written).
    If the workflow already exists and *force* is False, workflow_written is False.
    """
    workflow_path = dest / _WORKFLOW_REL
    config_path = dest / "onto-ci.yml"

    workflow_written = False
    if force or not workflow_path.exists():
        workflow_path.parent.mkdir(parents=True, exist_ok=True)
        workflow_path.write_text(_read_template("taxonomy-ci.yml"), encoding="utf-8")
        workflow_written = True

    config_written = False
    if include_config and (force or not config_path.exists()):
        config_path.write_text(_read_template("onto-ci.yml"), encoding="utf-8")
        config_written = True

    return workflow_written, config_written


def prompt_if_missing(
    root: Path,
    ask_fn: Callable[[str], bool] | None = None,
) -> bool:
    """Prompt to scaffold CI if it is missing. Returns True if files were created.

    *ask_fn* receives the prompt message and returns a bool (True = confirmed).
    Defaults to Rich's Confirm.ask with default=True.
    """
    if not needs_ci(root):
        return False

    if ask_fn is None:
        from rich.prompt import Confirm

        ask_fn = lambda msg: Confirm.ask(msg, default=True)  # noqa: E731

    if ask_fn("No taxonomy CI workflow found — add it now?"):
        scaffold(root)
        return True
    return False
