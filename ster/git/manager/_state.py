"""Static-typing surface shared by every ``GitManager`` mixin: declares every
attribute/method a mixin may borrow from a sibling mixin, so mypy can check
cross-mixin ``self.foo()`` calls inside one mixin's methods even though that
mixin doesn't itself define ``foo`` — some sibling mixin does, once they're all
composed into the real ``GitManager`` class (see ``__init__.py``).

This is a typing-only construct, generated from (and kept behaviour-identical
to) the original monolithic class's signatures and instance attributes. The
``TYPE_CHECKING`` branch is what mypy sees; the runtime branch is a bare, empty
class that changes nothing about any mixin's actual behaviour or MRO.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:

    class _ManagerState:
        """Every attribute/method a mixin may borrow from a sibling mixin, for
        mypy only — never instantiated, never a real base at runtime."""

        # set in GitManager.__init__ (_config.py)
        taxonomy_path: Path
        _cfg: dict
        _global_cfg: dict

        # owned by _config.py — read by nearly every other mixin
        def is_enabled(self) -> bool: ...
        def is_configured(self) -> bool: ...
        def _persist(self) -> None: ...
        def _repo(self) -> Path | None: ...

        # owned by _staging.py — read by _commit.py
        def has_staged_changes(self) -> bool: ...

        # owned by _push.py — read by _commit.py
        def _push_direct(self, repo: Path, branch: str) -> None: ...
        def _push_pr(self, repo: Path, main: str, commit_msg: str) -> None: ...

else:

    class _ManagerState:
        """Empty at runtime — a real base would shadow nothing, since every
        mixin already defines what it needs; this exists only so mixins can
        share one common ancestor for the ``TYPE_CHECKING`` surface above."""
