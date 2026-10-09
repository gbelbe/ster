"""What a new user meets in the first minute.

Naming a file the obvious way, before reading any documentation. Half the
commands took a file positionally while the other half insisted on -f, so
``ster validate x.ttl`` answered "Got unexpected extra argument(s)" — which
reads as "that made no sense" rather than "use -f".
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


@pytest.mark.parametrize("command", ["validate", "handles"])
def test_a_file_can_be_named_the_obvious_way(command: str, taxonomy, monkeypatch) -> None:
    """Positionally, like every other command that takes one."""
    monkeypatch.setattr("webbrowser.open", lambda *_a, **_k: True)

    result = runner.invoke(app, [command, "real.ttl"])

    assert "unexpected extra argument" not in result.output, result.output
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize("command", ["validate", "handles"])
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
