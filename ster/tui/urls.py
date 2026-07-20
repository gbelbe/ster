"""Pure URL/URN helpers shared by the Markdown editor and the detail renderer.

Auto-linking turns a bare ``https://…`` / ``urn:…`` into a Markdown link so it
renders formatted (and, in the detail pane, clickable) without the user having to
type the ``[text](url)`` brackets. Kept Textual-free so it is trivially testable.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# A single bare URL/URN (the whole string) → auto-wrap it as a Markdown link.
_URL_RE = re.compile(r"^(https?://|urn:)\S+$", re.IGNORECASE)
# A bare URL/URN inside text, not already the target/text of a link (…](url), <url>, [url…).
_BARE_URL_RE = re.compile(r"(?<![(<\[])\b(https?://[^\s)]+|urn:[^\s)]+)", re.IGNORECASE)
# The target of a Markdown link: [text](url) → capture url.
_MD_LINK_RE = re.compile(r"\[[^\]]*\]\(\s*([^)\s]+)\s*\)")


def is_openable_url(url: str) -> bool:
    """True when *url* is a well-formed link a browser can actually open: ``http``/``https``
    with a host, or ``mailto:`` with an address. A missing/typo'd scheme or a host-less URL
    returns False (``webbrowser.open`` would 'succeed' on those yet open nothing)."""
    parsed = urlparse(url.strip())
    if parsed.scheme in ("http", "https"):
        return bool(parsed.netloc)
    if parsed.scheme == "mailto":
        return bool(parsed.path)
    return False


def link_kind(url: str) -> str:
    """Classify a link target: ``"web"`` (browser-openable), ``"urn"`` (a valid identifier
    that ster auto-links but a browser cannot open), or ``"malformed"`` (broken — a missing
    or typo'd scheme, a host-less URL, an unsupported scheme; it won't resolve anywhere)."""
    stripped = url.strip()
    if is_openable_url(stripped):
        return "web"
    parsed = urlparse(stripped)
    if parsed.scheme == "urn" and parsed.path:
        return "urn"
    return "malformed"


def malformed_markdown_links(text: str) -> list[str]:
    """The target URL of every Markdown ``[text](url)`` link in *text* that is malformed
    (see :func:`link_kind`). Empty when every link is a real web link or a valid URN — so
    it is safe to run on any value and flags only links that would never resolve."""
    return [target for target in _MD_LINK_RE.findall(text) if link_kind(target) == "malformed"]


def is_url(text: str) -> bool:
    """True when *text* is a single bare URL / URN → auto-wrap it as a Markdown link."""
    return bool(_URL_RE.match(text.strip()))


def autolink_urls(text: str) -> str:
    """Rewrite every bare URL/URN in *text* as ``[url](url)``, leaving already-linked ones
    untouched (so it is safe to run on open/render and idempotent)."""
    return _BARE_URL_RE.sub(lambda m: f"[{m.group(1)}]({m.group(1)})", text)
