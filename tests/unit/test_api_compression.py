"""The map payload is compressed on the way out.

/api/locate answers with one record per place, and those records are mostly
repeated strings — the same ancestors, the same facet classes, the same icon
data URI, once per store. On a file of a thousand shops that is 2.2 MB, and
roughly 70% of it is the same URIs again.

Restructuring it was measured against simply compressing it:

    as it is               2224 KB
    + gzip                  134 KB
    icon dedup + gzip       131 KB
    full intern table+gzip  129 KB

The elaborate version saves 5 KB over the transport doing the work, and costs a
new wire format on both sides. So the payload stays readable and plain, and the
response is compressed.

Small responses are left alone: below the threshold the compressed form can be
larger than the original, and the CPU is spent for nothing.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from ster.api import MIN_COMPRESS_BYTES, SSEBroadcaster, create_app
from ster.model import Taxonomy

TOKEN = "tok"  # noqa: S105 — a test double, not a credential


def _client() -> TestClient:
    app = create_app(Taxonomy(), TOKEN, SSEBroadcaster(), lambda t: None)
    return TestClient(app)


def test_a_large_response_comes_back_compressed() -> None:
    """The header is the contract: without it a browser decompresses nothing."""
    response = _client().get("/openapi.json", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert len(response.content) > MIN_COMPRESS_BYTES, "pick a bigger endpoint to test with"
    assert response.headers.get("content-encoding") == "gzip"


def test_a_client_that_cannot_decompress_still_gets_the_body() -> None:
    """No gzip offered means no gzip sent — never a body the caller cannot read."""
    response = _client().get("/openapi.json", headers={"Accept-Encoding": "identity"})

    assert response.status_code == 200
    assert response.headers.get("content-encoding") != "gzip"
    assert response.json()["openapi"]


def test_the_threshold_leaves_small_responses_alone() -> None:
    """Below it, compressing costs CPU and can make the body larger."""
    assert MIN_COMPRESS_BYTES >= 500
