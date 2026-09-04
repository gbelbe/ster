"""Git integration for ster — version-control taxonomy files automatically.

Session lifecycle
─────────────────
  setup()          — first-time: detect/init/clone/link repo; ask branch strategy
  pre_edit_check() — fetch remote; pull if behind; show what changed
  stage_file()     — git add <taxonomy_file>  (called after every save)
  commit_and_push() — prompt for message; commit; push direct or via PR

Config
──────
  Per-file settings are stored in ~/.config/ster/git_repos.json, keyed by the
  absolute path of the taxonomy file.  This means one user can work on many
  different taxonomy files across different repos simultaneously with no
  cross-contamination.

  GitHub tokens are NOT persisted here.  We first try ``gh auth token``
  (GitHub CLI) and, for one-time use, prompt the user; saving is opt-in with a
  plaintext warning.

A single stateful ``GitManager`` class doesn't split into free functions the
way a flat-function module does, so — like ``ster.tui.app`` and
``ster.tui.config_modal`` — this package composes it from mixin classes, one
per business concern (config/state, first-time setup, fetch/pull sync,
staging, commit+push, PR creation, release tagging); see ``_state.py`` for the
typing-only surface that lets one mixin's methods reference attributes/methods
owned by a sibling mixin. ``GitManager`` is a plain Python class (not a
Textual widget), so none of the ``@on(...)``/reactive/BINDINGS concerns the
Textual splits had to work around apply here.

The module-level helpers the original file also defined (``file_activity``,
``render_diff``, the ``_git``/``_git_available`` subprocess wrapper, the
``console``/``err`` Rich consoles, and the global-config load/save pair) each
got their own small home by concern: ``_activity.py``, ``_diff.py``,
``_subprocess.py``, ``_console.py``, ``_config_store.py``. Every mixin reaches
these through a module-qualified attribute access (``_subprocess._git(...)``,
not a bare ``_git(...)`` copied in via ``from ._subprocess import _git``) —
this is what lets a test's ``patch("ster.git.manager._subprocess._git", ...)``
intercept a call made from *any* mixin: a bare imported name is a separate
reference captured at import time and would miss a patch applied to the
submodule's own attribute. The many pre-existing tests that patched
``ster.git.manager._git``/``_git_available`` and ``monkeypatch.setattr``'d
``console``/``CONFIG_FILE``/``CONFIG_DIR`` on the flat module were retargeted
to their new submodule-qualified homes (``ster.git.manager._subprocess.*``,
``ster.git.manager._console.*``, ``ster.git.manager._config_store.*``) for the
same reason.
"""

from __future__ import annotations

from ._activity import file_activity as file_activity
from ._commit import _CommitMixin
from ._config import _ConfigMixin
from ._config_store import CONFIG_DIR as CONFIG_DIR
from ._config_store import CONFIG_FILE as CONFIG_FILE
from ._diff import render_diff as render_diff
from ._push import _PushMixin
from ._release import _ReleaseMixin
from ._setup import _SetupMixin
from ._staging import _StagingMixin
from ._sync import _SyncMixin

__all__ = [
    "CONFIG_DIR",
    "CONFIG_FILE",
    "GitManager",
    "file_activity",
    "render_diff",
]


class GitManager(  # type: ignore[misc]
    _ConfigMixin,
    _SetupMixin,
    _SyncMixin,
    _StagingMixin,
    _CommitMixin,
    _PushMixin,
    _ReleaseMixin,
):
    """Manages git operations for a single taxonomy file.

    Each instance is bound to one taxonomy file path.  All config for this
    file is stored under ``self._cfg`` and persisted to the global JSON.
    """
