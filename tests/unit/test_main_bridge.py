from __future__ import annotations

import ster.__main__
import ster.cli


def test_main_imported():
    """Ensure the __main__ entry point can be imported and refers to cli._home.main."""
    assert ster.__main__.main is ster.cli._home.main


def test_cli_package_main_module_importable():
    """`python -m ster.cli` resolves to the same entry point as `ster.cli.main`."""
    import ster.cli.__main__ as cli_main_module

    assert cli_main_module.main is ster.cli.main


# ── main() dispatch (ster/cli/_home.py) ─────────────────────────────────────


def test_main_bare_invocation_runs_home_screen(monkeypatch):
    from unittest.mock import patch

    monkeypatch.setattr("sys.argv", ["ster"])
    with patch("ster.cli._home._home_screen") as home_screen:
        ster.cli.main()
    home_screen.assert_called_once_with()


def test_main_subcommand_delegates_to_typer(monkeypatch):
    from unittest.mock import patch

    monkeypatch.setattr("sys.argv", ["ster", "validate", "--file", "x.ttl"])
    with patch("ster.cli._app.app") as app:
        ster.cli.main()
    app.assert_called_once_with()


def test_main_flag_first_delegates_to_typer(monkeypatch):
    from unittest.mock import patch

    monkeypatch.setattr("sys.argv", ["ster", "--help"])
    with patch("ster.cli._app.app") as app:
        ster.cli.main()
    app.assert_called_once_with()


def test_main_single_ttl_arg_opens_home_screen_in_its_folder(tmp_path, monkeypatch):
    from unittest.mock import patch

    ttl = tmp_path / "sub" / "taxonomy.ttl"
    ttl.parent.mkdir()
    ttl.write_text("@prefix ex: <https://example.org/> .\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["ster", "sub/taxonomy.ttl"])
    with patch("ster.cli._home._home_screen") as home_screen:
        ster.cli.main()
    home_screen.assert_called_once()
    from pathlib import Path

    kwargs = home_screen.call_args.kwargs
    assert kwargs["initial_file"] == Path.cwd() / "taxonomy.ttl"
    assert Path.cwd() == ttl.parent.resolve()


def test_main_ttl_arg_with_options_delegates_to_show(monkeypatch, tmp_path):
    from unittest.mock import patch

    monkeypatch.setattr(
        "sys.argv", ["ster", "missing.ttl", "--lang", "fr"]
    )  # >1 arg → never treated as bare-open
    with patch("ster.cli._app.app") as app:
        ster.cli.main()
    import sys

    assert sys.argv[1] == "show"
    app.assert_called_once_with()


def test_main_nonexistent_single_ttl_arg_delegates_to_show(monkeypatch):
    from unittest.mock import patch

    monkeypatch.setattr("sys.argv", ["ster", "does-not-exist.ttl"])
    with patch("ster.cli._app.app") as app:
        ster.cli.main()
    import sys

    assert sys.argv[1] == "show"
    app.assert_called_once_with()
