"""Step definitions for reopening a project from its saved merged graph."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pytest_bdd import given, scenarios, then, when
from typer.testing import CliRunner

from ster import store
from ster.cli import app
from ster.store import _cache, _load_save

scenarios("../features/perf/merged_cache.feature")

PREFIXES = (
    "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n@prefix ex: <https://example.org/t#> .\n"
)
NAMES = ("Alpha", "Beta", "Gamma")
OLD = 1_000_000_000
TEXT = "utf-8"


def _ttl(name: str) -> str:
    return PREFIXES + f"ex:{name} a owl:Class .\n"


@pytest.fixture
def project(tmp_path, monkeypatch) -> dict:
    monkeypatch.delenv("STER_NO_CACHE", raising=False)
    monkeypatch.setattr(_cache, "_bin_cache_dir", lambda: tmp_path / "cache")
    main = tmp_path / "main.ttl"
    main.write_text(_ttl("Main"), encoding=TEXT)
    context = []
    for name in NAMES:
        path = tmp_path / f"{name.lower()}.ttl"
        path.write_text(_ttl(name), encoding=TEXT)
        context.append(path)
    return {"main": main, "context": context, "parsed": [], "model": None}


@pytest.fixture(autouse=True)
def _count_parses(project, monkeypatch):
    real = _load_save._parse_graph

    def counting(path):
        project["parsed"].append(Path(path))
        return real(path)

    monkeypatch.setattr(_load_save, "_parse_graph", counting)


def _open(project) -> None:
    project["parsed"].clear()
    project["model"] = store.load(project["main"], context=project["context"])


@given("a project with context files that was opened once")
def _opened_once(project):
    _open(project)


@when("the project is opened again")
def _reopen(project):
    _open(project)


@when("a context file is edited")
def _edit(project):
    project["context"][0].write_text(_ttl("Delta"), encoding=TEXT)
    _open(project)


@when("a context file is replaced by different content with an older timestamp")
def _replace_older(project):
    project["context"][0].write_text(_ttl("Delta"), encoding=TEXT)
    os.utime(project["context"][0], (OLD, OLD))
    _open(project)


@when("a context file is touched without changing it")
def _touch(project):
    os.utime(project["context"][0], None)
    _open(project)


@when("the saved graph is corrupted")
def _corrupt(project):
    cache = _cache._get_context_cache_path(project["main"], project["context"])
    cache.write_bytes(b"not a pickle")
    _open(project)


@when("the user clears the cache")
def _clear(project, tmp_path):
    asset = tmp_path / "vendored.js"
    asset.write_text("lib", encoding=TEXT)
    project["asset"] = asset
    assert CliRunner().invoke(app, ["cache", "clear"]).exit_code == 0


@then("the saved graph is loaded and no file is parsed")
def _no_parse(project):
    assert project["parsed"] == []


@then("the project is rebuilt from the files")
def _rebuilt(project):
    assert set(project["context"]) <= set(project["parsed"])


@then("the saved graphs are deleted and downloaded assets are kept")
def _deleted(project, tmp_path):
    assert not _cache._get_context_cache_path(project["main"], project["context"]).exists()
    assert project["asset"].exists()


@then("the next open rebuilds from the files")
def _next_rebuilds(project):
    _open(project)
    assert set(project["context"]) <= set(project["parsed"])
