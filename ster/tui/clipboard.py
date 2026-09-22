"""Best-effort read/write of the local OS clipboard, complementing Textual's OSC 52.

``App.copy_to_clipboard`` emits the OSC 52 escape sequence, which many terminals ignore
(Terminal.app, tmux without ``set-clipboard on``, …) — so a copy silently never reaches the
system clipboard. This writes to the *local* clipboard via the platform tool (pbcopy /
wl-copy / xclip / xsel / clip) so the copy lands even when OSC 52 is unsupported. It is the
single seam the rest of the app uses for the OS clipboard (see the external-dependency rule).

Reading matters for the same reason writing does. ``App.clipboard`` holds only what was
copied *inside* the app — it is Textual's own record, not the OS's — so a paste binding
served from it can never see text copied from anywhere else. Both directions go through
the platform tool here.
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

# The read direction, same ordering and the same first-on-PATH-wins rule.
_PASTE_COMMANDS: dict[str, list[list[str]]] = {
    "darwin": [["pbpaste"]],
    "win32": [["powershell", "-NoProfile", "-Command", "Get-Clipboard"]],
}
_LINUX_PASTE_COMMANDS: list[list[str]] = [
    ["wl-paste", "--no-newline"],
    ["xclip", "-selection", "clipboard", "-o"],
    ["xsel", "--clipboard", "--output"],
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


def paste_from_system_clipboard() -> str | None:
    """The local OS clipboard's text, or None when it cannot be read.

    None and "" are deliberately different: the first means "no clipboard tool
    here, use whatever Textual has", the second means the clipboard is genuinely
    empty and a paste should insert nothing.
    """
    for cmd in _PASTE_COMMANDS.get(sys.platform, _LINUX_PASTE_COMMANDS):
        if shutil.which(cmd[0]) is None:
            continue
        try:
            done = subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                check=True,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        return done.stdout.decode("utf-8", errors="replace")
    return None
