"""Every third-party package ster imports is declared in pyproject.toml.

Regression: 0.50 imported ``packaging`` (the update check's PEP 440 comparison)
without declaring it. It was always installed in the dev/CI environment — pytest
and friends pull it in transitively — so nothing failed here, but a clean
``uv tool install ster`` has only the declared dependencies, and every command
died with ``ModuleNotFoundError: No module named 'packaging'``.

The check reads the source rather than the environment, so a transitive install
cannot mask a missing declaration.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SOURCE = _ROOT / "ster"
# Extras that are plugin dependencies: not core, so not in [project].dependencies,
# but imported by the code that only runs once the plugin is active.
_OPTIONAL_PLUGIN_EXTRAS = ("semanticlint", "rdfdiff")


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _distribution_name(spec: str) -> str:
    """``"textual[syntax]>=0.80"`` -> ``"textual"``."""
    return _normalise(re.split(r"[\s\[<>=!~;]", spec, maxsplit=1)[0])


def _pyproject() -> dict:
    return tomllib.loads((_ROOT / "pyproject.toml").read_text())


def _declared_distributions() -> set[str]:
    """Distribution names in the core ``dependencies`` list (extras stripped)."""
    return {_distribution_name(spec) for spec in _pyproject()["project"]["dependencies"]}


def _plugin_distributions() -> set[str]:
    """Distributions of the optional plugins, imported lazily and only when active."""
    extras = _pyproject()["project"]["optional-dependencies"]
    return {_distribution_name(spec) for extra in _OPTIONAL_PLUGIN_EXTRAS for spec in extras[extra]}


def _wheel_packages() -> set[str]:
    """Top-level packages built into the wheel itself (``agent-app/agent_app`` -> ``agent_app``)."""
    listed = _pyproject()["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    return {Path(entry).name for entry in listed}


def _imported_top_level_modules() -> dict[str, str]:
    """Top-level module -> first file importing it, for absolute imports in ster/."""
    found: dict[str, str] = {}
    for path in sorted(_SOURCE.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                found.setdefault(name.split(".")[0], str(path.relative_to(_ROOT)))
    return found


def _undeclared_third_party_imports() -> dict[str, str]:
    declared = _declared_distributions() | _plugin_distributions()
    shipped = _wheel_packages()
    owners = packages_distributions()
    missing: dict[str, str] = {}
    for module, origin in _imported_top_level_modules().items():
        if module in shipped or module in sys.stdlib_module_names:
            continue
        distributions = {_normalise(d) for d in owners.get(module, [module])}
        if not distributions & declared:
            missing[module] = origin
    return missing


def test_packaging_is_declared_regression() -> None:
    # Root cause: ster/cli/_app.py imports packaging.version but pyproject.toml
    # never listed it, so a clean install crashed at launch.
    assert "packaging" in _declared_distributions()


def test_every_third_party_import_is_a_declared_dependency() -> None:
    missing = _undeclared_third_party_imports()
    assert not missing, (
        "imported by ster/ but absent from [project].dependencies "
        f"(module -> first importing file): {missing}"
    )


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("rdflib>=7.0", "rdflib"),
        ("textual[syntax]>=0.80", "textual"),
        ("uvicorn[standard]>=0.30", "uvicorn"),
        ("Typer >= 0.12", "typer"),
    ],
)
def test_declared_name_parsing_strips_extras_and_specifiers(spec: str, expected: str) -> None:
    assert _distribution_name(spec) == expected
