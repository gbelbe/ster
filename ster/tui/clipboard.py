"""Best-effort write to the local OS clipboard, complementing Textual's OSC 52.

``App.copy_to_clipboard`` emits the OSC 52 escape sequence, which many terminals ignore
(Terminal.app, tmux without ``set-clipboard on``, …) — so a copy silently never reaches the
system clipboard. This writes to the *local* clipboard via the platform tool (pbcopy /
wl-copy / xclip / xsel / clip) so the copy lands even when OSC 52 is unsupported. It is the
single seam the rest of the app uses for the OS clipboard (see the external-dependency rule).
"""

from __future__ import annotations

import shutil
import subprocess
import sys

# platform → ordered candidate commands; the first one found on PATH wins.
_CLIPBOARD_COMMANDS: dict[str, list[list[str]]] = {
    "darwin": [["pbcopy"]],
    "win32": [["clip"]],
}
_LINUX_COMMANDS: list[list[str]] = [
    ["wl-copy"],  # Wayland
    ["xclip", "-selection", "clipboard"],  # X11
    ["xsel", "--clipboard", "--input"],  # X11 (alt)
]


def copy_to_system_clipboard(text: str) -> bool:
    """Write *text* to the local OS clipboard. Returns True on success; False when no tool is
    available or the write fails. Never raises — copy is a convenience, not a critical path."""
    for cmd in _CLIPBOARD_COMMANDS.get(sys.platform, _LINUX_COMMANDS):
        if shutil.which(cmd[0]) is None:
            continue
        try:
            subprocess.run(
                cmd,
                input=text.encode("utf-8"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=2,
            )
            return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False
