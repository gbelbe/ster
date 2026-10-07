"""Guard against ambiguous ``ster serve`` project loads."""

from __future__ import annotations

import pytest

from ster.cli._serve import _require_explicit_context
from ster.project import Project


def test_serve_refuses_multiple_project_files_without_context(tmp_path):
    main = tmp_path / "main.ttl"
    other = tmp_path / "other.ttl"
    main.write_text("", encoding="utf-8")
    other.write_text("", encoding="utf-8")
    Project(tmp_path, files=[main, other]).save()

    with pytest.raises(Exception, match="multiple ontology files.*context-files"):
        _require_explicit_context(main, None)


def test_serve_allows_multiple_files_when_context_is_explicit(tmp_path):
    main = tmp_path / "main.ttl"
    other = tmp_path / "other.ttl"
    main.write_text("", encoding="utf-8")
    other.write_text("", encoding="utf-8")
    Project(tmp_path, files=[main, other]).save()

    _require_explicit_context(main, [other])
