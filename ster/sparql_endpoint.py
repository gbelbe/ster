"""Reading an ontology from a SPARQL endpoint (GraphDB, Fuseki, …), read-only.

The one place that speaks HTTP to an endpoint, so the rest of ster sees only a
:class:`Snapshot`. A snapshot is a copy: one CONSTRUCT is sent, its triples come
back as Turtle and become an ordinary in-memory taxonomy with no file behind it,
so every view works and editing is refused for want of somewhere to save.

Three sources are supported — the default graph, one named graph, or the
reader's own CONSTRUCT query. The row limit exists because an endpoint can hold
millions of triples and the model lives in memory; it is applied to the two
generated queries and reported when it is reached. A query written by the reader
is sent as written, since rewriting someone's SPARQL to add a limit would mean
parsing it.
"""

from __future__ import annotations

import http.client
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .model import Taxonomy

DEFAULT_LIMIT: Final = 100_000
_ACCEPT: Final = "text/turtle"
_ENCODING: Final = "utf-8"
DEFAULT_TIMEOUT: Final = 600.0
_CHUNK_BYTES: Final = 64 * 1024
_MAX_ANSWER_MB: Final = 512
_MAX_ANSWER_BYTES: Final = _MAX_ANSWER_MB * 1024 * 1024
_ERROR_BODY_BYTES: Final = 400
_ERROR_BODY_CHARS: Final = 200
_REDIRECT_CODES: Final = range(300, 400)
_AUTH_CODES: Final = (401, 403)
_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
_CONFIG_FILE = Path.home() / ".config" / "ster" / "endpoint.json"

# A prologue declaration the query form may follow (comments are skipped line by line,
# since a "#" inside an IRI such as <https://e#> is not a comment).
_DECLARATION = re.compile(r"(?:PREFIX\s+[^\s:]*:\s*<[^>]*>|BASE\s+<[^>]*>)", re.I)
_CONSTRUCT_FORM = re.compile(r"(?:CONSTRUCT|DESCRIBE)\b", re.I)

Progress = Callable[[int, str], None]
# What a session that is not a file hands the TUI: call it (off the UI thread, with a
# progress callback or None) for the model and an optional notice to show once it is up.
SourceLoader = Callable[[Progress | None], tuple[Taxonomy, str | None]]


class EndpointError(Exception):
    """The endpoint could not give us a graph; the message says why, in plain words."""


class NotRdfError(EndpointError):
    """The endpoint answered, but not with RDF ster can read (a login page, an empty reply)."""


def display_url(url: str) -> str:
    """*url* without credentials, query string or fragment: safe to print or log.

    A token in the query string or a user:password@ prefix must not end up in an
    error message, a status line or a CI log.
    """
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return "<invalid URL>"
    if not parts.netloc:
        return url.partition("?")[0].partition("#")[0].rpartition("@")[2]
    return f"{parts.scheme}://{parts.netloc.rpartition('@')[2]}{parts.path}"


def _check_url(url: str) -> None:
    """Refuse a URL no HTTP client could send, before any request is made."""
    try:
        parts = urllib.parse.urlsplit(url)
        parts.port  # noqa: B018 — raises ValueError for a port that is not a number
    except ValueError:
        raise EndpointError("The endpoint URL is not valid (check the host and port).") from None
    shown = display_url(url)
    if parts.scheme not in ("http", "https"):
        raise EndpointError(f"{shown!r} is not an http(s) SPARQL endpoint URL.")
    if not parts.hostname:
        raise EndpointError(f"{shown!r} has no host name.")
    if parts.username is not None or parts.password is not None:
        raise EndpointError(
            "The URL must not carry a user name or password; "
            "send credentials with --header 'Authorization: …'."
        )
    if not url.isascii() or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        raise EndpointError(
            f"{shown!r} must not contain spaces, control or non-ASCII characters "
            "(percent-encode them)."
        )


def _check_header(name: str, value: str) -> None:
    """Refuse a header that would break the request (or smuggle another one in)."""
    if not _HEADER_NAME.fullmatch(name):
        raise EndpointError(f"{name!r} is not a valid HTTP header name.")
    try:
        value.encode("latin-1")
    except UnicodeEncodeError:
        raise EndpointError(f"The value of header {name!r} must be Latin-1 text.") from None
    if any(c in value for c in "\r\n\0"):
        raise EndpointError(f"The value of header {name!r} must not contain line breaks.")


@dataclass(frozen=True)
class EndpointSource:
    """Where to read from and what to ask for.

    *headers* (e.g. an Authorization header) are sent as given and never stored,
    logged or repeated in an error message.
    """

    url: str
    graph: str | None = None
    query: str | None = None
    limit: int = DEFAULT_LIMIT
    headers: tuple[tuple[str, str], ...] = ()
    timeout: float = DEFAULT_TIMEOUT

    def __post_init__(self) -> None:
        _check_url(self.url)
        for name, value in self.headers:
            _check_header(name, value)
        if self.timeout <= 0:
            raise EndpointError("The timeout must be more than 0 seconds.")
        if self.graph and self.query:
            raise EndpointError("Give either a named graph or a query, not both.")
        if self.limit < 1:
            raise EndpointError("The row limit must be at least 1.")
        if self.query is not None and not _is_construct(self.query):
            raise EndpointError(
                "The query must be a CONSTRUCT (or DESCRIBE): ster builds its model from triples."
            )

    @property
    def shown(self) -> str:
        """The URL as safe to print: no credentials, no query string."""
        return display_url(self.url)

    @property
    def limited(self) -> bool:
        """True when the row limit is part of the query sent (not for a custom query)."""
        return self.query is None


@dataclass(frozen=True)
class Snapshot:
    """What an endpoint answered: the taxonomy, how many triples, and whether the limit cut it."""

    taxonomy: Taxonomy
    triples: int
    truncated: bool

    @property
    def empty(self) -> bool:
        """True when the endpoint answered with no triples at all."""
        return self.triples == 0


def _is_construct(query: str) -> bool:
    """True when *query*, past its comments and PREFIX/BASE declarations, is a CONSTRUCT or DESCRIBE."""
    rest = query
    while True:
        rest = rest.lstrip()
        if rest.startswith("#"):
            rest = rest.partition("\n")[2]
            continue
        declaration = _DECLARATION.match(rest)
        if declaration is None:
            break
        rest = rest[declaration.end() :]
    return _CONSTRUCT_FORM.match(rest) is not None


def build_query(source: EndpointSource) -> str:
    """The query to send: the reader's own, else the default or named graph, limited."""
    if source.query is not None:
        return source.query
    pattern = "?s ?p ?o"
    if source.graph:
        pattern = f"GRAPH <{source.graph}> {{ {pattern} }}"
    return f"CONSTRUCT {{ ?s ?p ?o }} WHERE {{ {pattern} }} LIMIT {source.limit}"


def _request(source: EndpointSource) -> urllib.request.Request:
    body = urllib.parse.urlencode({"query": build_query(source)}).encode(_ENCODING)
    request = urllib.request.Request(  # noqa: S310 — scheme checked in EndpointSource
        source.url,
        data=body,
        headers={"Accept": _ACCEPT, "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    for name, value in source.headers:
        request.add_header(name, value)
    return request


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: it would turn the POST into a bodiless GET and send
    the caller's headers (an Authorization token) on to whichever host it names."""

    def redirect_request(self, *_args, **_kwargs):  # noqa: V105
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def fetch(source: EndpointSource, progress: Progress | None = None) -> bytes:
    """The endpoint's Turtle answer to :func:`build_query`, or an :class:`EndpointError`.

    ``source.timeout`` bounds the wait for each reply *and* the whole transfer, so a
    server that trickles bytes cannot hold the caller for longer than it.
    """
    _say(progress, 5, "Contacting the endpoint")
    deadline = time.monotonic() + source.timeout
    try:
        with _OPENER.open(_request(source), timeout=source.timeout) as response:
            _say(progress, 30, "Receiving triples")
            return _read_answer(response, source, deadline)
    except urllib.error.HTTPError as exc:
        raise EndpointError(_http_message(source, exc)) from None
    except http.client.HTTPException as exc:
        raise EndpointError(
            f"{source.shown} closed the connection before the answer was complete "
            f"({type(exc).__name__})."
        ) from None
    except OSError as exc:  # URLError is an OSError
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, TimeoutError):
            raise EndpointError(
                f"{source.shown} did not answer within {source.timeout:g} s."
            ) from None
        raise EndpointError(f"Could not reach {source.shown}: {reason}") from None


def _read_answer(response, source: EndpointSource, deadline: float) -> bytes:
    """The whole body, within the deadline and the size cap, and never silently cut short."""
    chunks: list[bytes] = []
    size = 0
    while chunk := response.read1(_CHUNK_BYTES):
        size += len(chunk)
        if size > _MAX_ANSWER_BYTES:
            raise EndpointError(
                f"The answer from {source.shown} is over {_MAX_ANSWER_MB} MB; "
                "ask for less (a LIMIT in your query)."
            )
        if time.monotonic() > deadline:
            raise EndpointError(
                f"{source.shown} was still sending after {source.timeout:g} s; gave up."
            )
        chunks.append(chunk)
    if response.length:  # the server promised more bytes than it sent
        raise http.client.IncompleteRead(b"".join(chunks), response.length)
    return b"".join(chunks)


def _http_message(source: EndpointSource, exc: urllib.error.HTTPError) -> str:
    """Why the endpoint refused: its status, what it said, and what to try."""
    message = f"{source.shown} answered {exc.code} {exc.reason}"
    if exc.code in _REDIRECT_CODES:
        where = exc.headers.get("Location")
        if not where:
            return f"{message}."
        target = display_url(urllib.parse.urljoin(source.url, where))
        return f"{message}, redirecting to {target}. Use that URL (ster does not follow redirects)."
    detail = _error_detail(exc)
    message = f"{message}: {detail}" if detail else message
    if not message.endswith("."):
        message += "."
    if exc.code in _AUTH_CODES:
        message += " Send credentials with --header 'Authorization: …'."
    return message


def _error_detail(exc: urllib.error.HTTPError) -> str:
    """The first line of the error body (GraphDB puts its SPARQL parse error there)."""
    try:
        body = exc.read(_ERROR_BODY_BYTES).decode(_ENCODING, errors="replace")
    except (OSError, http.client.HTTPException):
        return ""
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if not lines or lines[0].startswith("<"):  # an HTML error page says nothing useful
        return ""
    return lines[0][:_ERROR_BODY_CHARS]


def _say(progress: Progress | None, percent: int, message: str) -> None:
    if progress is not None:
        progress(percent, message)


def load(source: EndpointSource, progress: Progress | None = None) -> Snapshot:
    """Fetch *source* and build the read-only taxonomy for it."""
    from . import store  # noqa: PLC0415

    data = fetch(source, progress)
    _say(progress, 60, "Building the model")
    try:
        taxonomy = store.taxonomy_from_bytes(data)
    except Exception as exc:  # noqa: BLE001 — any parser's complaint means "not RDF"
        raise NotRdfError(f"{source.shown} did not return RDF ({_gist(exc)}).") from None
    _say(progress, 90, "Preparing the query engine")
    triples = store.attach_query_store(taxonomy, data) or 0
    truncated = source.limited and triples >= source.limit
    return Snapshot(taxonomy, triples, truncated)


def loader_for(source: EndpointSource) -> SourceLoader:
    """The TUI's loader for *source*: the model, plus a notice when the limit cut it short."""

    def _load(progress: Progress | None) -> tuple[Taxonomy, str | None]:
        snapshot = load(source, progress)
        notice = None
        if snapshot.empty:
            notice = "The endpoint answered, but with no triples."
        elif snapshot.truncated:
            notice = (
                f"Showing the first {snapshot.triples:,} triples: the row limit "
                f"({source.limit:,}) was reached. Raise it with --limit and press R to re-fetch."
            )
        return snapshot.taxonomy, notice

    return _load


def _gist(exc: Exception) -> str:
    return str(exc).strip().splitlines()[0][:120] if str(exc).strip() else type(exc).__name__


# ── the remembered row limit ──────────────────────────────────────────────────


def saved_limit() -> int:
    """The row limit last chosen in the menu, else :data:`DEFAULT_LIMIT`."""
    try:
        value = json.loads(_CONFIG_FILE.read_text(encoding=_ENCODING)).get("limit")
    except (OSError, ValueError, AttributeError):
        return DEFAULT_LIMIT
    return value if isinstance(value, int) and value >= 1 else DEFAULT_LIMIT


def save_limit(limit: int) -> None:
    """Remember *limit* as the default for the next endpoint. Best-effort."""
    try:
        _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CONFIG_FILE.write_text(json.dumps({"limit": limit}), encoding=_ENCODING)
    except OSError:
        pass
