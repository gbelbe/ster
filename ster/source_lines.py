"""Where each subject starts a statement in an RDF text file.

The source pane shows ``L42`` beside a statement so the reader can find it in
the file and fix it there. rdflib keeps no positions, so the file's own text is
read once more, line by line. Only the first line of a statement is recorded:
that is where the reader goes, and the lines after it follow from there.

A statement starts where the previous one ended — after ``.``, a TriG ``{`` or
``}``, a prefix declaration, or the top of the file — and its first token is
the subject, written with *this file's* prefixes or as a full ``<IRI>``. Lines
inside a multi-line string and commented-out lines never count. Anything that
does not match cleanly is left out: a missing number costs the reader a search,
a wrong one sends them to the wrong place.

Line-based formats only (Turtle, TriG, N-Triples, N3). RDF/XML and JSON-LD have
no "statement per line" to point at, so they yield nothing.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_LINE_FORMATS: Final = frozenset({".ttl", ".trig", ".nt", ".n3"})
_PREFIX = re.compile(r"^\s*(?:@prefix|PREFIX)\s+([\w.-]*):\s*<([^>]*)>", re.IGNORECASE)
_DIRECTIVE = re.compile(r"^\s*(?:@prefix|@base|PREFIX|BASE)\b", re.IGNORECASE)
# What a statement's first token can be: a full IRI, or a prefixed name.
_SUBJECT = re.compile(r"^\s*(?:<([^>\s]*)>|([\w.-]*):([^\s;,.(){}\[\]]*))")
# Strings and IRIs, removed before looking for a comment or the line's end —
# a `#` inside `<http://…#>` or a `.` inside "a. b" is neither.
_OPAQUE = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|<[^>\s]*>')
_LONG_QUOTES: Final = ('"""', "'''")


@dataclass(frozen=True)
class SourceLines:
    """The 1-based lines on which each subject IRI starts a statement."""

    _starts: dict[str, list[int]]

    @classmethod
    def from_file(cls, path: Path) -> SourceLines | None:
        """Read *path*; None for a format with no lines to point at, or no file."""
        if path.suffix.lower() not in _LINE_FORMATS:
            return None
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        return cls(_scan(text.splitlines()))

    def starts(self, uri: str) -> list[int]:
        """Every line on which *uri* starts a statement, in file order."""
        return list(self._starts.get(uri, ()))


def _code(line: str) -> str:
    """*line* without its strings, IRIs and trailing comment — what is left is syntax."""
    return _OPAQUE.sub(" ", line).split("#", 1)[0].strip()


def _toggles_long_string(line: str) -> bool:
    """Whether *line* opens or closes a multi-line string (an odd count of triple quotes)."""
    return any(line.count(quote) % 2 for quote in _LONG_QUOTES)


def subject_iri(line: str, prefixes: dict[str, str]) -> str | None:
    """The IRI of *line*'s first token, if it is one this file can spell out."""
    match = _SUBJECT.match(line)
    if match is None:
        return None
    iri, prefix, local = match.groups()
    if iri is not None:
        return iri
    namespace = prefixes.get(prefix)
    return namespace + local if namespace is not None else None


def _scan(lines: list[str]) -> dict[str, list[int]]:
    starts: dict[str, list[int]] = defaultdict(list)
    prefixes: dict[str, str] = {}
    in_long_string = False
    at_start = True  # the top of a file starts a statement
    for number, line in enumerate(lines, start=1):
        if in_long_string:
            in_long_string = not _toggles_long_string(line)
            at_start = in_long_string is False and _code(line.rsplit('"""', 1)[-1]).endswith(".")
            continue
        code = _code(line)
        if not code:
            continue  # blank or comment: changes nothing
        declared = _PREFIX.match(line)
        if declared:
            prefixes[declared.group(1)] = declared.group(2)
        elif at_start and not code.endswith("{"):  # a TriG graph name is not a statement
            subject = subject_iri(line, prefixes)
            if subject is not None:
                starts[subject].append(number)
        in_long_string = _toggles_long_string(line)
        at_start = not in_long_string and (
            bool(_DIRECTIVE.match(line)) or code.endswith((".", "{", "}"))
        )
    return dict(starts)
