"""Git integration for ster — version-control and history browsing."""

from .log import GitLogViewer, launch_git_log
from .log_logic import (
    ConceptChange,
    FieldDiff,
    LogEntry,
    _parse_log,
    build_diff_taxonomy,
    compute_auto_fold,
    compute_taxonomy_diff,
)
from .manager import GitManager, render_diff

__all__ = [
    # manager
    "GitManager",
    "render_diff",
    # log
    "GitLogViewer",
    "launch_git_log",
    # log_logic
    "LogEntry",
    "FieldDiff",
    "ConceptChange",
    "_parse_log",
    "build_diff_taxonomy",
    "compute_auto_fold",
    "compute_taxonomy_diff",
]
