"""Regression: `--help` text must be plain in tests, on GitHub as locally.

Root cause: typer switches Rich into forced-terminal mode whenever
`GITHUB_ACTIONS`, `FORCE_COLOR` or `PY_COLORS` is set
(`typer.rich_utils.FORCE_TERMINAL`), so on GitHub the help text is laced with
ANSI escapes that never appear on a laptop. An assertion like
`"--ask-again" in result.output` then passes locally and fails in CI — which
is what held back PRs #249 and #251. The root conftest turns that mode off for
every test, so help assertions read the same text everywhere.
"""

from __future__ import annotations

import typer.rich_utils
from typer.testing import CliRunner

from ster.cli import app


def test_typer_forced_terminal_is_off_in_tests():
    assert typer.rich_utils.FORCE_TERMINAL is False


def test_help_output_has_no_ansi_escapes_regression():
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "\x1b[" not in result.output
