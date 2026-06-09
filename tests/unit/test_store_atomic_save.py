"""Unit tests for atomic persistence in ster/store.py::save.

save() must write via a sibling temp file + os.replace so that a crash or a
concurrent reader never observes a truncated TTL, and a failed write never
corrupts or removes the pre-existing file.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ster import store

_SKOS_TTL = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix t: <https://ex.org/t/> .

t:Scheme a skos:ConceptScheme ; skos:hasTopConcept t:Top .
t:Top a skos:Concept ; skos:inScheme t:Scheme ; skos:topConceptOf t:Scheme ;
      skos:prefLabel "Top"@en .
"""


def _load_ttl(tmp_path: Path) -> tuple[object, Path]:
    src = tmp_path / "onto.ttl"
    src.write_text(_SKOS_TTL)
    return store.load(src), src


# ── happy paths ───────────────────────────────────────────────────────────────


def test_save_writes_valid_ttl_roundtrip(tmp_path: Path) -> None:
    tax, _ = _load_ttl(tmp_path)
    out = tmp_path / "out.ttl"
    store.save(tax, out)
    reloaded = store.load(out)
    assert "https://ex.org/t/Top" in reloaded.concepts


def test_save_creates_new_file_when_absent(tmp_path: Path) -> None:
    tax, _ = _load_ttl(tmp_path)
    out = tmp_path / "fresh.ttl"
    assert not out.exists()
    store.save(tax, out)
    assert out.is_file() and out.stat().st_size > 0


def test_save_overwrites_existing_completely(tmp_path: Path) -> None:
    tax, _ = _load_ttl(tmp_path)
    out = tmp_path / "out.ttl"
    out.write_text("LEFTOVER " * 500)  # large stale content
    store.save(tax, out)
    text = out.read_text()
    assert "LEFTOVER" not in text  # fully replaced, no trailing stale bytes
    assert "https://ex.org/t/Top" in store.load(out).concepts  # real content, semantically intact


def test_save_leaves_no_temp_file(tmp_path: Path) -> None:
    tax, _ = _load_ttl(tmp_path)
    out = tmp_path / "out.ttl"
    store.save(tax, out)
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "onto.ttl" and p != out]
    assert leftovers == []


# ── failure paths (atomicity guarantees) ──────────────────────────────────────


def test_save_leaves_original_intact_on_serialize_failure(tmp_path: Path) -> None:
    """If serialization fails, the pre-existing file is untouched."""
    tax, _ = _load_ttl(tmp_path)
    out = tmp_path / "out.ttl"
    original = "ORIGINAL CONTENT — must survive a failed save"
    out.write_text(original)

    with (
        patch("ster.store.taxonomy_to_graph", side_effect=RuntimeError("boom")),
        pytest.raises(RuntimeError),
    ):
        store.save(tax, out)

    assert out.read_text() == original  # regression: no partial/empty write


def test_save_intact_and_no_temp_when_replace_fails(tmp_path: Path) -> None:
    """If the atomic rename fails, the original survives and no temp is left behind."""
    tax, _ = _load_ttl(tmp_path)
    out = tmp_path / "out.ttl"
    original = "ORIGINAL — survives a failed rename"
    out.write_text(original)

    with (
        patch("ster.store.os.replace", side_effect=OSError("rename failed")),
        pytest.raises(OSError),
    ):
        store.save(tax, out)

    assert out.read_text() == original
    leftovers = [p.name for p in tmp_path.iterdir() if p.name not in ("onto.ttl", "out.ttl")]
    assert leftovers == []  # temp cleaned up on failure
