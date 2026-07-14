"""Pure URL/URN helpers shared by the Markdown editor and the detail renderer.

Auto-linking turns a bare ``https://…`` / ``urn:…`` into a Markdown link so it
renders formatted (and, in the detail pane, clickable) without the user having to
type the ``[text](url)`` brackets. Kept Textual-free so it is trivially testable.
"""

from __future__ import annotations

import re

# A single bare URL/URN (the whole string) → auto-wrap it as a Markdown link.
_URL_RE = re.compile(r"^(https?://|urn:)\S+$", re.IGNORECASE)
# A bare URL/URN inside text, not already the target/text of a link (…](url), <url>, [url…).
_BARE_URL_RE = re.compile(r"(?<![(<\[])\b(https?://[^\s)]+|urn:[^\s)]+)", re.IGNORECASE)


def is_url(text: str) -> bool:
    """True when *text* is a single bare URL / URN → auto-wrap it as a Markdown link."""
    return bool(_URL_RE.match(text.strip()))


def autolink_urls(text: str) -> str:
    """Rewrite every bare URL/URN in *text* as ``[url](url)``, leaving already-linked ones
    untouched (so it is safe to run on open/render and idempotent)."""
    return _BARE_URL_RE.sub(lambda m: f"[{m.group(1)}]({m.group(1)})", text)
