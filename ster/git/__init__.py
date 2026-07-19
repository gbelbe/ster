"""Git integration for ster — version-control for the taxonomy workspace."""

from .manager import GitManager, render_diff

__all__ = [
    "GitManager",
    "render_diff",
]
