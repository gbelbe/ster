"""Run semanticlint checks inline and display results with Rich."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import semanticlint  # noqa: F401 — registers all built-in checks
from semanticlint.checks.base import CheckConfig, Severity, Violation
from semanticlint.checks.lint.syntax import lint_syntax
from semanticlint.checks.registry import CheckRegistry
from semanticlint.detect import detect_vocab_type
from semanticlint.shacl.discovery import discover_shapes_files, load_shapes
from semanticlint.shacl.runner import run_shapes

from ster.plugins.semanticlint import checks as _checks  # noqa: F401 — registers ster checks

_SEVERITY_ORDER = {Severity.INFO: 0, Severity.WARNING: 1, Severity.ERROR: 2}

# Checks ster suppresses by default: RDF006 (BaseURIConsistency) flags the common,
# valid SKOS layout where concepts are siblings of — not nested under — their scheme
# URI, so it is noise for most vocabularies. (Reported upstream; re-enable via config
# when semanticlint tightens it.)
_DEFAULT_IGNORE = ("RDF006",)

_SEVERITY_STYLE = {
    Severity.ERROR: "bold red",
    Severity.WARNING: "yellow",
    Severity.INFO: "blue",
}


def load_config(search_dir: Path) -> tuple[CheckConfig, Severity]:
    """Load onto-ci.yml from *search_dir*. Returns (CheckConfig, fail_on_severity)."""
    candidate = search_dir / "onto-ci.yml"
    if candidate.exists():
        import yaml

        with open(candidate) as f:
            data = yaml.safe_load(f) or {}
        cfg = CheckConfig(
            select=data.get("select", []),
            ignore=data.get("ignore", []),
            quality=data.get("quality", {}),
        )
        try:
            fail_on = Severity(data.get("fail_on", "error"))
        except ValueError:
            fail_on = Severity.ERROR
        return cfg, fail_on
    return CheckConfig(), Severity.ERROR


def _check_included(check_id: str, cfg: CheckConfig) -> bool:
    """Apply ster's default ignores + the config's ``select`` / ``ignore`` (ids or
    prefixes). Enforced here because ster runs both the SHACL pass and the registry."""
    ignore = (*_DEFAULT_IGNORE, *cfg.ignore)
    if any(check_id == entry or check_id.startswith(entry) for entry in ignore):
        return False
    if cfg.select:
        return any(check_id == entry or check_id.startswith(entry) for entry in cfg.select)
    return True


def _language_label_shapes(cfg: CheckConfig):  # type: ignore[no-untyped-def]
    """The ster-authored per-language ``rdfs:label`` shapes for the configured class /
    property label languages (empty graph when none are required)."""
    from ster.plugins.semanticlint.language_shapes import build_label_language_shapes

    return build_label_language_shapes(
        cfg.quality.get("class_label_languages", []),
        cfg.quality.get("property_label_languages", []),
    )


def _graph_violations(graph, cfg: CheckConfig, path: Path) -> list[Violation]:  # type: ignore[no-untyped-def]
    """Violations for one parsed *graph*: the SHACL pass (built-in shapes since
    semanticlint 0.5 + any sibling ``*.shapes.ttl`` business rules) plus the registered
    Python checks, each filtered by select/ignore."""
    vtype = detect_vocab_type(graph)
    local_shapes = load_shapes(discover_shapes_files(path))  # project-owned rules next to the file
    local_shapes += _language_label_shapes(cfg)  # ster-authored per-language rdfs:label rules
    out: list[Violation] = [
        v
        for v in run_shapes(graph, cfg, vtype, extra_shapes=local_shapes)
        if _check_included(v.check_id, cfg)
    ]
    for check_cls in CheckRegistry.for_vocab(vtype):
        if _check_included(check_cls.id, cfg):
            out.extend(check_cls().run(graph, cfg))
    return out


def lint_files(paths: list[Path], cfg: CheckConfig) -> list[Violation]:
    """Run the configured semanticlint checks on *paths* — SHACL shapes (built-in +
    discovered local rules) and Python checks — filtered by select/ignore."""
    all_violations: list[Violation] = []
    for path in paths:
        graph, syntax_violations = lint_syntax(path)
        violations = [v for v in syntax_violations if _check_included(v.check_id, cfg)]
        if graph is not None and len(graph) > 0:
            violations.extend(_graph_violations(graph, cfg, path))
        all_violations.extend(violations)
    return all_violations


def lint_overview(path: Path) -> tuple[dict[str, int], list[dict[str, str]]]:
    """Run semanticlint on *path* and return plain data for UI consumers.

    Returns ``(counts, issues)`` where *counts* maps severity name → count and
    *issues* is a list of ``{severity, check_id, message, subject}`` dicts. Pure
    Python types only, so callers (the TUI) never depend on the semanticlint
    ``Violation`` type — keeping the library behind this adapter (see CLAUDE.md).

    Uses the plugin's global quality config (``~/.config/ster/quality.json``), not the
    repo's ``onto-ci.yml`` — the TUI's live view is driven by the user's global
    thresholds; the commit hook / CI keep using ``onto-ci.yml``.
    """
    from . import config

    violations = lint_files([path], config.build_check_config())
    counts = {sev.value: 0 for sev in Severity}
    for v in violations:
        counts[v.severity.value] += 1
    issues = [
        {
            "severity": v.severity.value,
            "check_id": v.check_id,
            "message": v.message,
            "subject": str(v.subject) if v.subject else "",
        }
        for v in violations
    ]
    return counts, issues


def has_blocking_violations(violations: list[Violation], fail_on: Severity) -> bool:
    """Return True if any violation meets or exceeds the *fail_on* threshold."""
    threshold = _SEVERITY_ORDER[fail_on]
    return any(_SEVERITY_ORDER[v.severity] >= threshold for v in violations)


def _violation_line(v: Violation) -> str:
    """One rendered detail line for a single violation."""
    style = _SEVERITY_STYLE[v.severity]
    label = f"[{style}]{v.severity.value.upper():7}[/{style}]"
    subj = f" {str(v.subject).split('/')[-1].split('#')[-1]}" if v.subject else ""
    return f"  {label} [{v.check_id}]{subj}: {v.message}"


_SUMMARY_STYLES = (
    (Severity.ERROR, "[bold red]", "error"),
    (Severity.WARNING, "[yellow]", "warning"),
    (Severity.INFO, "[blue]", "info"),
)


def _summary_line(violations: list[Violation], fail_on: Severity) -> str:
    """The final count summary line (icon + per-severity counts + fail-on note)."""
    from collections import Counter

    n = Counter(v.severity for v in violations)
    parts = [
        f"{colour}{n[sev]} {name}{'' if n[sev] == 1 else 's'}[/]"
        for sev, colour, name in _SUMMARY_STYLES
        if n[sev]
    ]
    icon = "[bold red]✗[/]" if has_blocking_violations(violations, fail_on) else "[yellow]⚠[/]"
    return f"  {icon}  {', '.join(parts)}  [dim](fail-on: {fail_on.value})[/dim]"


def display_violations(violations: list[Violation], fail_on: Severity) -> None:
    """Print violation details and summary using Rich."""
    from rich.console import Console
    from rich.rule import Rule

    out = Console()
    out.print()
    out.print(Rule("[bold]semanticlint[/bold]", style="dim"))
    if not violations:
        out.print("  [green]✓[/green] No issues found.")
        out.print()
        return
    for v in violations:
        out.print(_violation_line(v))
    out.print()
    out.print(_summary_line(violations, fail_on))
    out.print()


def run_pre_commit_lint(
    taxonomy_path: Path,
    repo_dir: Path,
    confirm_fn: Callable[[str], bool] | None = None,
) -> bool:
    """Run lint, display results, prompt if blocking. Returns True if commit should proceed.

    *confirm_fn* receives the prompt message and returns bool. Defaults to Rich Confirm.ask.
    """
    cfg, fail_on = load_config(repo_dir)
    violations = lint_files([taxonomy_path], cfg)
    display_violations(violations, fail_on)

    if not has_blocking_violations(violations, fail_on):
        return True

    if confirm_fn is None:
        from rich.prompt import Confirm

        confirm_fn = lambda msg: Confirm.ask(msg, default=False)  # noqa: E731

    return confirm_fn("Issues found. Commit anyway?")
