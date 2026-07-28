from __future__ import annotations

import ster.__main__
import ster.cli


def test_main_imported():
    """Ensure the __main__ entry point can be imported and refers to cli.main."""
    assert ster.__main__.main is ster.cli.main
