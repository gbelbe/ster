"""What a new user meets in the first minute.

Two things they hit before reading any documentation: naming a file the obvious
way, and running the export from the directory they are standing in. Both were
wrong.

``ster export -f x.ttl`` wrote the HTML and *then* raised
``ValueError: relative path can't be expressed as a file URI`` — Path.as_uri()
refuses a relative path, and the export builds one to open a browser. The work
was done; the run still ended in a stack trace and exit 1.

And half the commands took a file positionally while the other half insisted on
-f, so ``ster validate x.ttl`` answered "Got unexpected extra argument(s)" —
which reads as "that made no sense" rather than "use -f".
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from ster.cli import app

runner = CliRunner()

TTL = (
    "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
    '<https://x/s> a skos:ConceptScheme ; skos:prefLabel "S"@en .\n'
    '<https://x/c> a skos:Concept ; skos:inScheme <https://x/s> ; skos:prefLabel "C"@en .\n'
)


@pytest.fixture
def taxonomy(tmp_path: Path, monkeypatch) -> Path:
    src = tmp_path / "real.ttl"
    src.write_text(TTL, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return src


# ── naming the file ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("command", ["validate", "export", "handles"])
def test_a_file_can_be_named_the_obvious_way(command: str, taxonomy, monkeypatch) -> None:
    """Positionally, like every other command that takes one."""
    monkeypatch.setattr("webbrowser.open", lambda *_a, **_k: True)

    result = runner.invoke(app, [command, "real.ttl"])

    assert "unexpected extra argument" not in result.output, result.output
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize("command", ["validate", "export", "handles"])
def test_the_old_flag_still_works(command: str, taxonomy, monkeypatch) -> None:
    """-f is how these were invoked before; breaking it would break scripts."""
    monkeypatch.setattr("webbrowser.open", lambda *_a, **_k: True)

    result = runner.invoke(app, [command, "-f", "real.ttl"])

    assert result.exit_code == 0, result.output


def test_naming_the_file_twice_is_refused_rather_than_guessed(taxonomy) -> None:
    """Two different files, one command — say so instead of silently picking."""
    (taxonomy.parent / "other.ttl").write_text(TTL, encoding="utf-8")

    result = runner.invoke(app, ["validate", "real.ttl", "-f", "other.ttl"])

    assert result.exit_code != 0
    assert "once" in result.output.lower() or "both" in result.output.lower(), result.output


# ── the export crash ─────────────────────────────────────────────────────────


def test_a_relative_path_still_yields_a_browser_url(tmp_path, monkeypatch) -> None:
    """The regression, asserted at the line that raised.

    Path.as_uri() refuses a relative path, so the export wrote every file and
    then died on the last line opening a browser. Tested here rather than
    through the command, because whether that step is reached depends on which
    export profile runs.
    """
    from ster.cli._export import _browser_url

    monkeypatch.chdir(tmp_path)
    (tmp_path / "out.html").write_text("<html></html>", encoding="utf-8")

    url = _browser_url(Path("out.html"))

    assert url.startswith("file:///")
    assert url.endswith("/out.html")


def test_export_from_the_current_directory_does_not_crash(taxonomy, monkeypatch) -> None:
    """End to end: no traceback, and a clean exit."""
    monkeypatch.setattr("webbrowser.open", lambda *_a, **_k: True)

    result = runner.invoke(app, ["export", "real.ttl"])

    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output
