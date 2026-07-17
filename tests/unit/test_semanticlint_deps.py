"""The semanticlint optional-dependency guard (``deps.is_installed``).

Regression: a *present-but-unimportable* install (the package metadata is found,
but importing the library raises — e.g. a missing transitive dependency) used to
report installed, so ``is_active()`` went True and the lint path then ran a
broken ``import semanticlint`` and crashed the app. ``is_installed`` must report
False whenever the library can't actually be imported.
"""

from __future__ import annotations

import importlib

from ster.plugins.semanticlint import deps


def test_is_installed_true_when_the_library_imports() -> None:
    # semanticlint is installed in the dev/test env.
    assert deps.is_installed() is True


def test_is_installed_false_when_the_library_cannot_be_imported(monkeypatch) -> None:
    real_import = importlib.import_module

    def boom(name: str, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        if name == "semanticlint":
            raise ModuleNotFoundError("No module named 'semanticlint._backend'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", boom)
    # find_spec still succeeds (the package is present) — but the import fails, so the
    # honest answer is "not usable".
    assert deps.is_installed() is False
