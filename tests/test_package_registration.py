"""Every shipped package must be registered with every tool that guards it.

Adding a second top-level package to this repository takes nine coordinated
edits across four files. Miss one and the failure is uneven: forgetting the
prek SKIP entry fails loudly on the next PR, but forgetting the ratchet job,
the mypy path, the coverage flag or the Sonar source fails *silently* — the
package simply is not checked, and nothing says so.

That is not hypothetical. A second package shipped 2,527 lines with no complexity
ratchet against the PR base, and it surfaced only because a loud failure
happened to sit beside the silent one.

So the packages are discovered from the filesystem rather than from a list
someone has to remember to update, and each one is asserted present in every
place that guards it. A new package fails this test on the PR that adds it,
naming exactly what is missing.

Sibling of `test_every_feature_file_is_bound`, which does the same job for
feature files.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Directories that are Python packages but are not *shipped* — they carry no
# runtime code, so none of the guards below apply to them.
_NOT_SHIPPED = {"tests", "scripts"}

# The directory check_complexity_ratchet.py scans when given no --path. A
# package equal to this default is covered by an invocation that names no path.
_RATCHET_DEFAULT = "ster"


def _shipped_packages() -> list[str]:
    """Top-level importable packages that ship as part of a distribution."""
    return sorted(
        d.name
        for d in ROOT.iterdir()
        if d.is_dir()
        and (d / "__init__.py").exists()
        and not d.name.startswith((".", "_"))
        and d.name not in _NOT_SHIPPED
    )


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def packages() -> list[str]:
    found = _shipped_packages()
    assert found, "no shipped package found — the discovery rule is wrong"
    return found


@pytest.fixture(scope="module")
def ci() -> str:
    return _read(".github/workflows/ci.yml")


@pytest.fixture(scope="module")
def prek() -> str:
    return _read(".pre-commit-config.yaml")


def test_every_package_is_type_checked(packages, prek) -> None:
    """A package missing from the mypy entry is never type-checked at all."""
    entry = next((line for line in prek.splitlines() if "mypy" in line and "entry:" in line), "")
    missing = [p for p in packages if f"{p}/" not in entry]

    assert not missing, f"not in the mypy hook entry: {missing}\n  entry: {entry.strip()}"


def test_every_package_is_measured_for_coverage(packages, ci) -> None:
    """Without --cov the patch-coverage gate passes over unmeasured code.

    ``--cov=.`` satisfies this for every package at once, and is what ci.yml
    uses: measuring from the repo root is what makes coverage paths carry their
    package, which SonarQube needs to resolve them. A per-package flag list is
    still accepted, so a project that prefers it is not forced to change.
    """
    if "--cov=." in ci:
        return  # the whole tree is measured; no package can be left out
    missing = [p for p in packages if f"--cov={p}" not in ci]

    assert not missing, f"no --cov flag in ci.yml for: {missing}"


def test_every_package_is_a_coverage_source(packages) -> None:
    pyproject = _read("pyproject.toml")
    # source_pkgs, not source: source is the repo root so coverage paths carry
    # their package for SonarQube (see the comment in pyproject). The packages
    # themselves are named in source_pkgs, and that is what must stay complete.
    source = re.search(r"^source_pkgs\s*=\s*\[([^\]]*)\]", pyproject, re.M)
    assert source, "no [tool.coverage.run] source_pkgs list found"
    missing = [p for p in packages if f'"{p}"' not in source.group(1)]

    assert not missing, f"not in coverage source: {missing}"


def test_every_package_is_analysed_by_sonar(packages) -> None:
    sources = _read("sonar-project.properties")
    line = next((ln for ln in sources.splitlines() if ln.startswith("sonar.sources")), "")
    listed = {s.strip() for s in line.partition("=")[2].split(",")}
    missing = [p for p in packages if p not in listed]

    assert not missing, f"not in sonar.sources: {missing}"


def test_every_sonar_source_exists() -> None:
    sources = _read("sonar-project.properties")
    line = next((ln for ln in sources.splitlines() if ln.startswith("sonar.sources")), "")
    listed = [s.strip() for s in line.partition("=")[2].split(",") if s.strip()]
    missing = [path for path in listed if not (ROOT / path).exists()]

    assert not missing, f"sonar.sources lists paths that do not exist: {missing}"


def test_every_package_has_a_complexity_ratchet(packages, ci) -> None:
    """The ratchet scans one directory per run, so each package needs its own.

    It must run in the *dedicated* job, which fetches the base branch. The prek
    job checks out shallow and cannot resolve a base ref at all.
    """
    missing = [p for p in packages if p != _RATCHET_DEFAULT and f"--path {p}" not in ci]

    assert not missing, (
        f"no ratchet invocation in the dedicated ci.yml job for: {missing}\n"
        "  add: uv run python scripts/check_complexity_ratchet.py "
        '--path <pkg> --base "origin/${{ github.base_ref }}"'
    )


def test_every_ratchet_hook_is_skipped_in_the_shallow_job(prek, ci) -> None:
    """A ratchet hook left in prek fails: that job has no base branch to diff.

    This is the loud failure the silent ones hid behind — SKIP matches hook ids
    exactly, so a new hook is not covered by an existing prefix.
    """
    hook_ids = re.findall(r"^\s*-\s*id:\s*(complexity-ratchet[\w-]*)", prek, re.M)
    assert hook_ids, "no complexity-ratchet hook found in the prek config"

    skip_line = next((ln for ln in ci.splitlines() if "SKIP=" in ln), "")
    skipped = set(re.search(r"SKIP=([\w,-]+)", skip_line).group(1).split(","))
    missing = [h for h in hook_ids if h not in skipped]

    assert not missing, (
        f"ratchet hooks not in the prek SKIP list: {missing}\n  SKIP currently: {sorted(skipped)}"
    )
