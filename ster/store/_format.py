"""RDF serialisation format detection: extension mapping, content sniffing, and
mismatch/parse-error reporting."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Final

_LIT_JSON_LD: Final = "json-ld"


_SNIFF_BYTES = 512
_FORMAT_MAP = {
    ".ttl": "turtle",
    ".nt": "nt",
    ".rdf": "xml",
    ".xml": "xml",
    ".owl": "xml",
    ".n3": "n3",
    ".jsonld": _LIT_JSON_LD,
    ".json": _LIT_JSON_LD,
    ".trig": "trig",
}
_RDFXML_EXTENSIONS = {".rdf", ".xml", ".owl"}


def _detect_format(path: Path) -> str:
    fmt = _FORMAT_MAP.get(path.suffix.lower())
    if fmt is None:
        raise ValueError(
            f"Unsupported file extension {path.suffix!r}. Use one of: {', '.join(_FORMAT_MAP)}"
        )
    return fmt


def is_rdfxml_path(path: Path) -> bool:
    """Return True if *path* has an RDF/XML file extension."""
    return path.suffix.lower() in _RDFXML_EXTENSIONS


def _sniff_format(path: Path) -> str | None:
    """Guess RDF serialisation format from the first bytes of *path*."""
    try:
        head = path.read_bytes()[:_SNIFF_BYTES].lstrip()
    except OSError:
        return None
    if head.startswith((b"<?xml", b"<rdf:RDF", b"<owl:")):
        return "xml"
    text = head.decode("utf-8", errors="replace").lstrip()
    if text.startswith(("@prefix", "@base", "PREFIX")):
        return "turtle"
    if text.startswith(("{", "[")):
        return _LIT_JSON_LD
    return None


def detect_format_mismatch(path: Path) -> tuple[str, str] | None:
    """Return (declared_fmt, actual_fmt) if content format differs from extension, else None."""
    declared = _FORMAT_MAP.get(path.suffix.lower())
    if declared is None:
        return None
    actual = _sniff_format(path)
    if actual and actual != declared:
        return declared, actual
    return None


def file_hash(path: Path) -> str:
    """Return an MD5 hex digest of *path*'s content (for change detection)."""
    return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()


_LINE_RE = re.compile(r"\bline\s+(\d+)\b", re.IGNORECASE)
_EXCERPT_PREFIX = "  → "
_MAX_LINE_LEN = 120 - len(_EXCERPT_PREFIX)  # 116


def format_parse_error(exc: Exception, path: Path) -> str:
    """Return a human-readable description of a parse error, including the bad line.

    Extracts the line number from the exception message (rdflib, lxml, and most
    other RDF parsers embed "line N" in their error text), reads that line from
    *path*, and formats a three-line message:

        Syntax error in <filename> at line N
          → <content of the offending line, trimmed to 120 chars>
          <original exception text>
    """
    msg = str(exc)
    match = _LINE_RE.search(msg)
    line_no: int | None = int(match.group(1)) if match else None

    line_content: str | None = None
    if line_no is not None:
        try:
            file_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            if 1 <= line_no <= len(file_lines):
                raw = file_lines[line_no - 1]
                line_content = raw if len(raw) <= _MAX_LINE_LEN else raw[: _MAX_LINE_LEN - 1] + "…"
        except OSError:
            pass

    parts: list[str] = []
    if line_no is not None:
        parts.append(f"Syntax error in {path.name} at line {line_no}")
    else:
        parts.append(f"Cannot load {path.name}")
    if line_content is not None:
        parts.append(f"  → {line_content}")
    parts.append(f"  {msg}")
    return "\n".join(parts)
