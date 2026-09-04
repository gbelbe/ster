"""The stdout/stderr Rich consoles every manager mixin prints through.

Reached via ``_console.console`` / ``_console.err`` (module-qualified) rather
than a bare imported name, for the same call-time-resolution reason as
``_subprocess.py`` — so a test's ``monkeypatch.setattr(_console, "console", ...)``
is observed no matter which mixin does the printing.
"""

from __future__ import annotations

from rich.console import Console

console = Console()
err = Console(stderr=True)
