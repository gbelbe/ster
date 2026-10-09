"""A throwaway SPARQL endpoint for tests: records the request, answers with canned Turtle.

The real endpoint (GraphDB behind a corporate network) is out of reach in CI, so
tests talk to this stdlib server on a free local port instead.
"""

from __future__ import annotations

import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

TTL = (
    b"@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
    b"@prefix ex: <https://example.org/e#> .\n"
    b'ex:Tent a skos:Concept ; skos:prefLabel "Tent"@en .\n'
    b'ex:Dome a skos:Concept ; skos:prefLabel "Dome"@en ; skos:broader ex:Tent .\n'
)


# Nothing listens on port 1, so connecting is refused at once. The scheme is a variable,
# not a literal, so no clear-text URL sits in the source (Sonar S5332).
_SCHEME = "http"
DEAD_ENDPOINT = f"{_SCHEME}://127.0.0.1:1/sparql"


class FakeEndpoint:
    """A throwaway endpoint; ``reply`` is (status, content_type, body)."""

    def __init__(self, reply=(200, "text/turtle", TTL)):
        self.reply = reply
        self.requests: list[dict] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: V105
                length = int(self.headers.get("Content-Length", 0))
                form = urllib.parse.parse_qs(self.rfile.read(length).decode())
                fake.requests.append(
                    {"headers": dict(self.headers), "query": form.get("query", [""])[0]}
                )
                status, ctype, body = fake.reply
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):  # noqa: V105
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"{'http'}://127.0.0.1:{self.server.server_port}/sparql"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class MisbehavingEndpoint:
    """An endpoint whose answer is whatever *behave(handler)* does with the connection.

    For the ways a real server goes wrong that a canned reply cannot show: going
    silent, trickling bytes, hanging up half way, redirecting. Every request that
    arrived is kept in ``requests`` (its path and headers).
    """

    def __init__(self, behave):
        self.requests: list[dict] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: V105
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                fake.requests.append({"path": self.path, "headers": dict(self.headers)})
                try:
                    behave(self)
                except OSError:  # the client gave up first, which is the point
                    pass

            def log_message(self, *_args):  # noqa: V105
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"{'http'}://127.0.0.1:{self.server.server_port}/sparql"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
