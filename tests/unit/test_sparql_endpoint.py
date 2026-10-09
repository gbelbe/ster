"""The SPARQL-endpoint adapter, against a local fake that behaves like GraphDB.

The real endpoint is behind a corporate network, so these drive a stdlib HTTP
server that records the request it got and answers with canned Turtle.
"""

from __future__ import annotations

import time

import pytest

from ster import sparql_endpoint as ep
from ster.sparql_endpoint import EndpointError, EndpointSource, NotRdfError
from tests._fake_endpoint import DEAD_ENDPOINT, TTL, MisbehavingEndpoint
from tests._fake_endpoint import FakeEndpoint as _Fake


@pytest.fixture
def fake():
    servers: list[_Fake] = []

    def make(reply=(200, "text/turtle", TTL)) -> _Fake:
        servers.append(_Fake(reply))
        return servers[-1]

    yield make
    for server in servers:
        server.close()


@pytest.fixture
def misbehaving():
    servers: list[MisbehavingEndpoint] = []

    def make(behave) -> MisbehavingEndpoint:
        servers.append(MisbehavingEndpoint(behave))
        return servers[-1]

    yield make
    for server in servers:
        server.close()


TRIPLES_IN_TTL = 5  # two concepts: a type each, two labels and one broader link
CONCEPTS_IN_TTL = 2
REMEMBERED_LIMIT = 1234

# ── the query that is sent ────────────────────────────────────────────────────


def test_default_graph_query_has_the_limit():
    query = ep.build_query(EndpointSource("https://x/sparql", limit=50))

    assert query == "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o } LIMIT 50"


def test_named_graph_query_wraps_the_graph_clause():
    query = ep.build_query(EndpointSource("https://x/sparql", graph="https://g/1", limit=7))

    assert "GRAPH <https://g/1> { ?s ?p ?o }" in query
    assert query.endswith("LIMIT 7")


def test_custom_query_is_sent_verbatim_without_a_limit():
    own = "PREFIX ex: <https://e#> CONSTRUCT { ?s a ex:C } WHERE { ?s a ex:C }"

    assert ep.build_query(EndpointSource("https://x/sparql", query=own, limit=5)) == own


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * WHERE { ?s ?p ?o } LIMIT 10",
        "ASK { ?s ?p ?o }",
        "INSERT DATA { <a> <b> <c> }",
    ],
)
def test_rejects_a_non_construct_custom_query(query):
    with pytest.raises(EndpointError, match="CONSTRUCT"):
        EndpointSource("https://x/sparql", query=query)


@pytest.mark.parametrize(
    "query",
    [
        "construct { ?s ?p ?o } where { ?s ?p ?o }",
        "# comment\nPREFIX a: <https://a#>\nBASE <https://b/>\nCONSTRUCT { ?s ?p ?o } WHERE {}",
        "DESCRIBE <https://e#a>",
    ],
)
def test_accepts_construct_after_a_prologue_in_any_case(query):
    EndpointSource("https://x/sparql", query=query)


def test_a_hash_inside_an_iri_is_not_a_comment():
    EndpointSource(
        "https://x/sparql", query="PREFIX e: <https://e#> CONSTRUCT { ?s ?p ?o } WHERE {}"
    )


@pytest.mark.parametrize("query", ["", "   \n", "# only a comment", "PREFIX a: <https://a#>"])
def test_a_query_with_no_form_is_rejected(query):
    with pytest.raises(EndpointError, match="CONSTRUCT"):
        EndpointSource("https://x/sparql", query=query)


def test_graph_and_query_are_mutually_exclusive():
    with pytest.raises(EndpointError, match="not both"):
        EndpointSource("https://x/sparql", graph="https://g", query="CONSTRUCT {} WHERE {}")


@pytest.mark.parametrize("url", ["ftp://x/sparql", "file:///etc/passwd", "not a url"])
def test_only_http_urls_are_endpoints(url):
    with pytest.raises(EndpointError, match="http"):
        EndpointSource(url)


def test_limit_must_be_positive():
    with pytest.raises(EndpointError, match="at least 1"):
        EndpointSource("https://x/sparql", limit=0)


# ── the request and the answer ────────────────────────────────────────────────


def test_request_is_a_form_post_accepting_turtle(fake):
    server = fake()

    ep.load(EndpointSource(server.url, limit=10))

    sent = server.requests[0]
    assert sent["headers"]["Accept"] == "text/turtle"
    assert sent["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert sent["query"].startswith("CONSTRUCT")


def test_load_builds_a_read_only_taxonomy_from_the_answer(fake):
    snapshot = ep.load(EndpointSource(fake().url))

    taxonomy = snapshot.taxonomy
    assert set(taxonomy.concepts) == {"https://example.org/e#Tent", "https://example.org/e#Dome"}
    assert taxonomy.file_path is None  # nothing to save to
    assert (
        snapshot.triples == TRIPLES_IN_TTL
    )  # the two concepts' triples, counted from the query store


def test_headers_are_sent(fake):
    server = fake()

    ep.load(EndpointSource(server.url, headers=(("Authorization", "Bearer s3cret"),)))

    assert server.requests[0]["headers"]["Authorization"] == "Bearer s3cret"


def test_a_header_value_never_appears_in_an_error(fake):
    server = fake((401, "text/plain", b"nope"))
    source = EndpointSource(server.url, headers=(("Authorization", "Bearer s3cret"),))

    with pytest.raises(EndpointError) as raised:
        ep.load(source)

    assert "s3cret" not in str(raised.value)
    assert "401" in str(raised.value)


def test_truncation_is_flagged_when_the_limit_is_hit(fake):
    snapshot = ep.load(EndpointSource(fake().url, limit=5))

    assert snapshot.truncated is True


def test_no_truncation_below_the_limit(fake):
    assert ep.load(EndpointSource(fake().url, limit=1000)).truncated is False


def test_a_custom_query_is_never_reported_truncated(fake):
    own = "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }"

    assert ep.load(EndpointSource(fake().url, query=own, limit=1)).truncated is False


def test_http_error_names_the_status_and_url(fake):
    server = fake((500, "text/plain", b"boom"))

    with pytest.raises(EndpointError, match=r"answered 500"):
        ep.load(EndpointSource(server.url))


def test_unreachable_endpoint_is_a_clean_error():
    with pytest.raises(EndpointError, match="Could not reach"):
        ep.load(EndpointSource(DEAD_ENDPOINT))


def test_non_rdf_response_is_a_clean_error(fake):
    server = fake((200, "text/html", b"<html>login page</html>"))

    with pytest.raises(EndpointError, match="did not return RDF"):
        ep.load(EndpointSource(server.url))


def test_progress_reports_each_phase(fake):
    seen: list[tuple[int, str]] = []

    ep.load(EndpointSource(fake().url), progress=lambda pct, msg: seen.append((pct, msg)))

    assert [m for _p, m in seen] == [
        "Contacting the endpoint",
        "Receiving triples",
        "Building the model",
        "Preparing the query engine",
    ]
    assert [p for p, _m in seen] == sorted(p for p, _m in seen)


# ── the remembered limit ──────────────────────────────────────────────────────


def test_saved_limit_defaults_when_nothing_is_stored(tmp_path, monkeypatch):
    monkeypatch.setattr(ep, "_CONFIG_FILE", tmp_path / "endpoint.json")

    assert ep.saved_limit() == ep.DEFAULT_LIMIT


def test_saved_limit_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(ep, "_CONFIG_FILE", tmp_path / "sub" / "endpoint.json")

    ep.save_limit(REMEMBERED_LIMIT)

    assert ep.saved_limit() == REMEMBERED_LIMIT


@pytest.mark.parametrize("stored", ["not json", '{"limit": 0}', '{"limit": "x"}', "[]"])
def test_a_bad_stored_limit_falls_back_to_the_default(tmp_path, monkeypatch, stored):
    config = tmp_path / "endpoint.json"
    config.write_text(stored)
    monkeypatch.setattr(ep, "_CONFIG_FILE", config)

    assert ep.saved_limit() == ep.DEFAULT_LIMIT


# ── the bytes loader and the native parse ─────────────────────────────────────


def test_native_index_from_bytes_matches_rdflib():
    import io

    import rdflib

    from ster import store
    from ster.store._graph_io import _native_index_from_stream

    native = _native_index_from_stream(io.BytesIO(TTL), "TURTLE")
    assert native is not None
    (index, by_type, _refs), _prefixes = native
    graph = rdflib.Graph()
    graph.parse(data=TTL, format="turtle")
    ref_index, ref_by_type, _ref_refs = store._graph_index(graph)

    assert set(index) == set(ref_index)
    assert {k: sorted(v) for k, v in by_type.items()} == {
        k: sorted(v) for k, v in ref_by_type.items()
    }


def test_endpoint_snapshot_skips_residue(monkeypatch):
    """A read-only snapshot is never saved, so the rdflib parse that records what
    the model dropped (for a later save) must not run."""
    from ster import store
    from ster.store import _snapshot

    monkeypatch.setattr(
        _snapshot, "graph_to_taxonomy", lambda *_a: pytest.fail("rdflib path must not run")
    )

    taxonomy = store.taxonomy_from_bytes(TTL)

    assert len(taxonomy.concepts) == CONCEPTS_IN_TTL


def test_query_store_is_loaded_from_the_raw_bytes():
    """A triple the model has no field for is still queryable from the snapshot."""
    from ster import store
    from ster.sparql_query import run_query_on_taxonomy

    data = TTL + b'@prefix ex: <https://example.org/e#> .\nex:Tent ex:colour "green" .\n'
    taxonomy = store.taxonomy_from_bytes(data)
    store.attach_query_store(taxonomy, data)

    result = run_query_on_taxonomy(
        taxonomy,
        "SELECT ?c WHERE { <https://example.org/e#Tent> <https://example.org/e#colour> ?c }",
    )

    assert result.error == ""
    assert result.rows == [["green"]] or result.rows == [['"green"']]


def test_falls_back_to_rdflib_without_pyoxigraph(monkeypatch):
    from ster import store
    from ster.store import _snapshot

    monkeypatch.setattr(_snapshot, "_native_index_from_stream", lambda *_a: None)

    taxonomy = store.taxonomy_from_bytes(TTL)

    assert set(taxonomy.concepts) == {"https://example.org/e#Tent", "https://example.org/e#Dome"}


# ── a URL or header that cannot be sent is refused before any request ─────────
SHORT_TIMEOUT = 0.5
ENDPOINT_DEADLINE_SLACK = 3.0  # seconds a giving-up read may overshoot its timeout


@pytest.mark.parametrize(
    "url",
    [
        "http://[::1",
        "http://127.0.0.1:99999/sparql",
        "http://",
        "http://host/a b",
        "http://host/a\nb",
        "http://exämple.com/sparql",
    ],
)
def test_a_url_no_client_could_send_is_a_clean_error(url):
    with pytest.raises(EndpointError):
        EndpointSource(url)


def test_credentials_in_the_url_are_refused_without_being_repeated():
    with pytest.raises(EndpointError, match="--header") as raised:
        EndpointSource("https://alice:s3cret@host/sparql")

    assert "s3cret" not in str(raised.value)
    assert "alice" not in str(raised.value)


@pytest.mark.parametrize(
    ("url", "shown"),
    [
        ("https://alice:s3cret@host:3030/ds/sparql?token=abc#frag", "https://host:3030/ds/sparql"),
        ("https://host/sparql", "https://host/sparql"),
        ("alice:s3cret@host/x?t=1", "host/x"),
        ("http://[::1", "<invalid URL>"),
    ],
)
def test_display_url_drops_credentials_query_and_fragment(url, shown):
    assert ep.display_url(url) == shown


def test_a_query_string_token_never_appears_in_an_error():
    source = EndpointSource(f"{DEAD_ENDPOINT}?token=abc123")

    with pytest.raises(EndpointError) as raised:
        ep.load(source)

    assert "abc123" not in str(raised.value)


@pytest.mark.parametrize(
    ("name", "value"),
    [("bad name", "x"), ("X-A", "line\nbreak"), ("X-A", "caf\u20ac"), ("", "x")],
)
def test_a_header_that_would_break_the_request_is_refused(name, value):
    with pytest.raises(EndpointError, match="header"):
        EndpointSource("https://x/sparql", headers=((name, value),))


def test_the_timeout_must_be_positive():
    with pytest.raises(EndpointError, match="timeout"):
        EndpointSource("https://x/sparql", timeout=0)


# ── a server that goes wrong ──────────────────────────────────────────────────


def test_a_silent_server_times_out_with_a_clear_message(misbehaving):
    server = misbehaving(lambda handler: time.sleep(1.5))

    with pytest.raises(EndpointError, match=r"did not answer within 0\.5 s"):
        ep.fetch(EndpointSource(server.url, timeout=SHORT_TIMEOUT))


def test_a_server_trickling_bytes_cannot_outlast_the_timeout(misbehaving):
    def trickle(handler):
        handler.send_response(200)
        handler.send_header("Content-Length", "100000")
        handler.end_headers()
        for _ in range(100):
            handler.wfile.write(b"#")
            handler.wfile.flush()
            time.sleep(0.1)

    server = misbehaving(trickle)
    started = time.monotonic()

    with pytest.raises(EndpointError, match="still sending"):
        ep.fetch(EndpointSource(server.url, timeout=1.0))

    assert time.monotonic() - started < ENDPOINT_DEADLINE_SLACK


def test_a_connection_dropped_mid_answer_is_a_clean_error_not_a_short_graph(misbehaving):
    def hang_up(handler):
        handler.send_response(200)
        handler.send_header("Content-Length", "5000")
        handler.end_headers()
        handler.wfile.write(b"@prefix ex: <https://e#> . ex:a a ex:C .")
        handler.wfile.flush()
        handler.connection.close()

    server = misbehaving(hang_up)

    with pytest.raises(EndpointError, match="closed the connection before the answer"):
        ep.load(EndpointSource(server.url))


def test_an_answer_over_the_size_cap_is_refused(fake, monkeypatch):
    monkeypatch.setattr(ep, "_MAX_ANSWER_BYTES", 50)

    with pytest.raises(EndpointError, match="ask for less"):
        ep.fetch(EndpointSource(fake().url))


@pytest.mark.parametrize("status", [301, 302, 307])
def test_a_redirect_is_reported_not_followed_and_sends_nothing_on(misbehaving, status):
    elsewhere = misbehaving(lambda handler: handler.send_response(200))

    def redirect(handler):
        handler.send_response(status)
        handler.send_header("Location", f"{elsewhere.url}?token=abc")
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    server = misbehaving(redirect)
    source = EndpointSource(server.url, headers=(("Authorization", "Bearer s3cret"),))

    with pytest.raises(EndpointError, match="redirecting to") as raised:
        ep.fetch(source)

    assert elsewhere.url in str(raised.value)
    assert "abc" not in str(raised.value)
    assert elsewhere.requests == []  # the Authorization header went nowhere else


def test_the_servers_own_error_text_is_shown(fake):
    server = fake((400, "text/plain", b"Parse error: line 1, column 8\nmore detail"))

    with pytest.raises(EndpointError) as raised:
        ep.fetch(EndpointSource(server.url))

    assert "answered 400" in str(raised.value)
    assert "Parse error: line 1, column 8" in str(raised.value)
    assert "more detail" not in str(raised.value)


def test_a_refused_login_says_where_credentials_go(fake):
    with pytest.raises(EndpointError, match="--header 'Authorization"):
        ep.fetch(EndpointSource(fake((401, "text/plain", b"")).url))


def test_an_html_error_page_is_not_quoted(fake):
    server = fake((404, "text/html", b"<!DOCTYPE HTML PUBLIC><html>File not found</html>"))

    with pytest.raises(EndpointError) as raised:
        ep.fetch(EndpointSource(server.url))

    assert str(raised.value).endswith("answered 404 Not Found.")


def test_an_error_with_no_body_reads_cleanly(fake):
    with pytest.raises(EndpointError) as raised:
        ep.fetch(EndpointSource(fake((404, "text/plain", b"")).url))

    assert str(raised.value).endswith("answered 404 Not Found.")


def test_a_reply_that_is_not_rdf_is_distinguishable_from_one_that_did_not_arrive(fake):
    with pytest.raises(NotRdfError):
        ep.load(EndpointSource(fake((200, "text/html", b"<html>login</html>")).url))

    with pytest.raises(EndpointError) as unreachable:
        ep.load(EndpointSource(DEAD_ENDPOINT))
    assert not isinstance(unreachable.value, NotRdfError)


def test_an_empty_answer_is_flagged_and_the_viewer_is_told(fake):
    source = EndpointSource(fake((200, "text/turtle", b"")).url)

    assert ep.load(source).empty is True
    _taxonomy, notice = ep.loader_for(source)(None)
    assert notice == "The endpoint answered, but with no triples."
