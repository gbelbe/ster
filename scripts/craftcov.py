#!/usr/bin/env python3
"""craftCov — a coverage-report-style scan of the craftsmanship catalog.

Honest about its limits before anything else: only the entries in
catalog.yaml that carry `detectors` (8 of 35 as of this writing — see
`--list-detectors`) have a real mechanical proxy here. Four more
(cyclomatic/cognitive complexity, invariant return, duplicated literal)
are covered by a separate script, `check_complexity_ratchet.py` — this
module has no awareness of it, so they show as "needs judgment" below even
though they are, in fact, mechanically checked elsewhere; see
CRAFTSMANSHIP.md's "The complexity ratchet". Three engines reused, one
technique ported rather than reimplemented from scratch:

  - `ruff` (Rust, already a dependency in every repo this ships to, ships
    its own fast internal cache) — guard-clauses, dead-code,
    explaining-constant, extract-helper, introduce-parameter-object,
    replace-conditional-with-polymorphism.
  - `pylint`, scoped to exactly two rules (R0902/R0904) — extract-class /
    God Class. ruff hasn't ported these yet (R0904 is preview-only there,
    R0902 doesn't exist in ruff at all); upstream pylint's originals are
    stable, so this is the one entry that needs a second tool on PATH.
  - `vulture` — a second, higher-recall pass for dead-code alongside
    ruff's F401/F811/F841: catches unused module-level functions/classes
    ruff's own-file-scoped checks can't see. Verified on a real, framework-
    heavy codebase (kai-ster: pytest-bdd + Textual) while building this:
    vulture's confidence scores cluster hard into two tiers — unused
    *variables* at 100% (redundant with ruff's own F841, adds nothing) and
    unused functions/classes/methods at 60% (vulture's own "fairly sure but
    could be wrong" floor — decorator-registered step defs and Textual's
    on_* handlers score exactly here without being genuinely dead). That
    60% tier is also where all of vulture's actual unique value lives, so
    craftCov reports it unfiltered by default (`--vulture-min-confidence 0`,
    vulture's own default) rather than quietly discarding the one thing
    ruff can't already tell you — raise the threshold yourself via
    `--vulture-min-confidence` once you've triaged a first pass and know
    your codebase's noise floor. The per-finding confidence is preserved in
    `--verbose`/JSON output for exactly this triage.
  - `dupes` (this module's own code, not a subprocess) — a from-scratch
    port of the rolling-hash line-window matching technique both PMD CPD
    (Karp-Rabin string matching over a token stream, per PMD's own docs)
    and pylint's own R0801 checker (same technique, one level coarser:
    stripped lines instead of language tokens — verified against pylint's
    actual source before porting) use — consolidate-duplicate-conditional.
    Ported rather than subprocessing pylint's checker because its CLI only
    puts ONE of a duplicate pair's two locations in structured JSON output
    (the other is free text inside the message), and its internal API is
    private/unstable across versions. See that section of this file for
    the full explanation, including why it's corpus-wide (runs over every
    file, every time — never through the per-file cache, unlike the three
    subprocess engines above) and what "exact match, no docstring
    special-casing" means for it in practice.

Feature Envy, Data Clumps *precisely* (not just "too many params" — the
*same group* repeating), Message Chains, Primitive Obsession, Refused
Bequest, and every `principle`/`workflow` entry have no detector on
purpose: no maintained, reusable Python tool exists for any of them
(checked against the design-smell-detection literature, which is
Java/C#/C++-tooling-only). A regex or AST check confident enough to report
these would cry wolf more than it'd help. Those stay a job for the
procedure in CRAFTSMANSHIP.md (read the code, ask the developer), not this
script. craftCov finds the mechanically-checkable subset; it is not a
replacement for the judgment call the rest of the catalog asks for.

Caching: findings for a file are cached by its content hash, keyed by path
relative to the scan root (so the cache survives the repo moving to a
different absolute path). A re-run only re-scans files whose hash changed
since the last run (or that are new); everything else is read back from
`.craftcov_cache.json`. This is on top of, not instead of, each tool's own
cache where it has one (ruff's `.ruff_cache/`) — craftCov's cache also
stores the class/function attribution none of the three tools track on
their own, so a warm re-run skips re-parsing ASTs too, not just re-linting.

When more than one tool flags the *same* line for the *same* heuristic
(e.g. ruff's F401 and vulture both catch an unused import), it's counted
once, not twice — see `scan_files`'s dedup.

Requires (unlike the other craft-gate scripts, which are plain bash):
PyYAML importable, plus whichever of `ruff` / `pylint` / `vulture` is on
PATH for the detectors catalog.yaml actually uses — only invoked if at
least one entry needs it, so a repo without pylint installed still gets
the other engines' findings, not a hard failure. `dupes` needs nothing
beyond the stdlib. `uv sync --extra craftcov` in this repo installs all
three external engines; see README's Requirements.

Usage:
    python3 scripts/craftcov.py                  # scan, text report
    python3 scripts/craftcov.py --format json     # machine-readable
    python3 scripts/craftcov.py --verbose         # + every finding, file:line
    python3 scripts/craftcov.py --no-cache        # ignore and overwrite the cache
    python3 scripts/craftcov.py --list-detectors  # which heuristics are detectable, and how
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import re
import subprocess
import sys
import time
import tokenize
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "catalog.yaml"
DEFAULT_CACHE_PATH = Path(".craftcov_cache.json")
DEFAULT_SNAPSHOT_PATH = Path(".craftcov_last_report.json")
CACHE_VERSION = 4

RULE_BASED_TOOLS = {"ruff", "pylint"}
WHOLE_FILE_TOOLS = {"vulture"}
CORPUS_TOOLS = {"dupes"}  # needs the whole file set at once, not per-file


# ── catalog / detector mapping ────────────────────────────────────────────────


def load_catalog() -> list[dict]:
    return yaml.safe_load(CATALOG_PATH.read_text())


def build_detector_index(
    catalog: list[dict],
) -> tuple[dict[str, dict[str, dict]], dict[str, dict], dict[str, dict]]:
    """(rule_maps, whole_tool_map, corpus_tool_map).

    rule_maps: tool -> {rule_code: catalog_entry}, for rule-granular tools
    (ruff, pylint). whole_tool_map: tool -> catalog_entry, for tools whose
    findings all mean one specific heuristic regardless of message
    (vulture) — one finding, one location. corpus_tool_map: tool ->
    {"entry": catalog_entry, **config}, for tools that need the whole file
    set at once rather than per-file (dupes — a duplicate only means
    anything relative to its other copy, possibly in a different file).
    Each (tool, rule) or (tool) claims exactly one entry by construction —
    collisions are a catalog.yaml authoring error, not something to
    silently pick a winner for.
    """
    rule_maps: dict[str, dict[str, dict]] = {}
    whole_tool: dict[str, dict] = {}
    corpus_tool: dict[str, dict] = {}
    for entry in catalog:
        for d in entry.get("detectors", []):
            tool = d["tool"]
            if tool in RULE_BASED_TOOLS:
                bucket = rule_maps.setdefault(tool, {})
                for rule in d["rules"]:
                    if rule in bucket:
                        raise SystemExit(
                            f"✗ {tool} rule {rule} is claimed by both "
                            f"{bucket[rule]['id']} and {entry['id']} in catalog.yaml"
                        )
                    bucket[rule] = entry
            elif tool in WHOLE_FILE_TOOLS:
                if tool in whole_tool:
                    raise SystemExit(
                        f"✗ {tool} (a whole-file detector) is claimed by both "
                        f"{whole_tool[tool]['id']} and {entry['id']} in catalog.yaml"
                    )
                whole_tool[tool] = entry
            elif tool in CORPUS_TOOLS:
                if tool in corpus_tool:
                    raise SystemExit(
                        f"✗ {tool} (a corpus-wide detector) is claimed by both "
                        f"{corpus_tool[tool]['entry']['id']} and {entry['id']} in catalog.yaml"
                    )
                corpus_tool[tool] = {"entry": entry, **{k: v for k, v in d.items() if k != "tool"}}
            else:
                raise SystemExit(f"✗ catalog.yaml: unknown detector tool '{tool}' on {entry['id']}")
    return rule_maps, whole_tool, corpus_tool


# ── file discovery ───────────────────────────────────────────────────────────


def discover_python_files(root: Path) -> list[str]:
    """Paths, relative to root, of every tracked .py file. Via git when
    possible (git already knows what to ignore — venvs, build artefacts —
    so this avoids reinventing that); falls back to a plain glob outside a
    git repo."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "*.py"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return sorted(line for line in out.splitlines() if line)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return sorted(str(p.relative_to(root)) for p in root.rglob("*.py"))


def file_hash(root: Path, rel: str) -> str:
    return hashlib.sha256((root / rel).read_bytes()).hexdigest()


# ── class/function attribution ───────────────────────────────────────────────


def build_scope_index(source: str) -> list[tuple[int, int, str, str]]:
    """(start_line, end_line, kind, qualified_name) for every class/function
    in the file. Callers pick the smallest enclosing span themselves, so
    order here doesn't matter."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    scopes: list[tuple[int, int, str, str]] = []

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = "class" if isinstance(child, ast.ClassDef) else "function"
                qualname = f"{prefix}{child.name}" if not prefix else f"{prefix}.{child.name}"
                end = getattr(child, "end_lineno", child.lineno)
                scopes.append((child.lineno, end, kind, qualname))
                walk(child, qualname + ("." if kind == "class" else ""))
            else:
                walk(child, prefix)

    walk(tree, "")
    return scopes


def enclosing_class(scopes: list[tuple[int, int, str, str]], line: int) -> str | None:
    best: tuple[int, int, str, str] | None = None
    for start, end, kind, qualname in scopes:
        if kind != "class" or not (start <= line <= end):
            continue
        if best is None or (end - start) < (best[1] - best[0]):
            best = (start, end, kind, qualname)
    return best[3] if best else None


# ── duplicate code (ported, not subprocessed) ───────────────────────────────
# Same core technique as both PMD CPD (Karp-Rabin rolling-hash string
# matching over a token stream, per its own docs) and pylint's own R0801
# checker (same technique, one level coarser: stripped *lines* rather than
# language tokens) — verified against both before writing this, not
# designed from scratch. Ported instead of subprocessing pylint because
# pylint's CLI only puts ONE of a duplicate pair's two locations in
# structured JSON; the other is embedded as free text inside the message,
# and its internal API (`_compute_sims`) is private/unstable. This is ~60
# lines once you already know the algorithm, and needs no new dependency.
#
# Corpus-wide by nature (a duplicate only means anything relative to its
# other copy, possibly in a different file) — unlike ruff/pylint/vulture,
# this always runs over every file, not just ones the per-file cache says
# changed. See main()'s comment on why that's an acceptable trade rather
# than a missed optimization.
#
# Exact-match only, like both reference tools' default mode — no
# identifier/literal normalization (PMD's opt-in Type-2 fuzzy matching
# needs a real per-language tokenizer to do properly; out of scope here).
# Doesn't special-case docstrings the way pylint's checker does either (a
# deliberate simplification) — a duplicated docstring block is still
# reported, which is arguably still useful signal for this catalog entry.
#
# Import statements ARE special-cased, on purpose, unlike PMD/pylint's own
# checkers: two files both doing `import os / import sys / from pathlib
# import Path` the same way isn't duplicated logic, it's every file in the
# repo depending on the same libraries the same way — see
# `_import_lines`/`strip_lines_for_dupes`.


def _import_lines(source: str) -> set[int]:
    """Every line number spanned by an `import`/`from ... import` statement,
    anywhere in the file (not just top-level — a lazy import inside a
    function is still a library, not code this repo wrote). AST-based, not
    a line-prefix regex, so a multi-line parenthesized `from x import (a,
    b, c)` has all of its lines excluded, not just the first."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            end = getattr(node, "end_lineno", node.lineno)
            lines.update(range(node.lineno, end + 1))
    return lines


def strip_lines_for_dupes(source: str) -> list[tuple[int, str]]:
    """(original_line_number, normalized_text) for every line of code this
    repo actually wrote — comments, blank lines, and import statements all
    dropped. Comments via `tokenize`, not a regex, so a '#' inside a string
    literal is never mistaken for a comment start; imports via `ast`, so a
    library import can't masquerade as "duplicated logic" just because two
    files both `import os, sys, json` the same way."""
    lines = source.splitlines()
    comment_cols: dict[int, int] = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                comment_cols[tok.start[0]] = tok.start[1]
    except (tokenize.TokenizeError, IndentationError, SyntaxError, ValueError):
        pass  # fall back to no comment-stripping for a file tokenize can't handle

    skip = _import_lines(source)

    result: list[tuple[int, str]] = []
    for i, raw in enumerate(lines, start=1):
        if i in skip:
            continue
        text = (raw[: comment_cols[i]] if i in comment_cols else raw).strip()
        if text:
            result.append((i, text))
    return result


def find_duplicate_blocks(
    filtered_by_file: dict[str, list[tuple[int, str]]], min_lines: int
) -> list[dict]:
    """Hash every min_lines-line window per file; any hash shared by two
    windows (same file or different) is a candidate duplicate, extended
    forward line-by-line to its true length, then de-overlapped so one long
    duplicate doesn't get reported as a pile of short overlapping ones."""
    texts_by_file = {rel: [t for _, t in lines] for rel, lines in filtered_by_file.items()}

    window_hash: dict[str, list[tuple[str, int]]] = {}
    for rel, texts in texts_by_file.items():
        for i in range(len(texts) - min_lines + 1):
            key = hashlib.sha256("\n".join(texts[i : i + min_lines]).encode()).hexdigest()
            window_hash.setdefault(key, []).append((rel, i))

    raw_matches: list[tuple[str, int, int, str, int, int]] = []
    seen_pairs: set[tuple[str, int, str, int]] = set()
    for occurrences in window_hash.values():
        if len(occurrences) < 2:
            continue
        for a in range(len(occurrences)):
            for b in range(a + 1, len(occurrences)):
                rel_a, i_a = occurrences[a]
                rel_b, i_b = occurrences[b]
                if rel_a == rel_b and i_a == i_b:
                    continue
                pair_key = (rel_a, i_a, rel_b, i_b)
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                texts_a, texts_b = texts_by_file[rel_a], texts_by_file[rel_b]
                length = min_lines
                while (
                    i_a + length < len(texts_a)
                    and i_b + length < len(texts_b)
                    and texts_a[i_a + length] == texts_b[i_b + length]
                ):
                    length += 1
                raw_matches.append((rel_a, i_a, i_a + length, rel_b, i_b, i_b + length))

    # Longer matches subsume the shorter, overlapping windows that also
    # matched inside them — a 20-line duplicate would otherwise produce
    # ~17 separate 4-line reports. Keep only matches not already covered by
    # a longer one over the same (file, file) pair and overlapping range.
    raw_matches.sort(key=lambda m: -(m[2] - m[1]))
    covered: dict[tuple[str, str], list[tuple[int, int, int, int]]] = {}
    kept: list[dict] = []
    for rel_a, i_a, end_a, rel_b, i_b, end_b in raw_matches:
        pair_key = (rel_a, rel_b) if rel_a <= rel_b else (rel_b, rel_a)
        ranges = covered.setdefault(pair_key, [])
        if any(
            i_a >= ca0 and end_a <= ca1 and i_b >= cb0 and end_b <= cb1
            for ca0, ca1, cb0, cb1 in ranges
        ):
            continue
        ranges.append((i_a, end_a, i_b, end_b))
        kept.append(
            {
                "file_a": rel_a,
                "start_a": filtered_by_file[rel_a][i_a][0],
                "end_a": filtered_by_file[rel_a][end_a - 1][0],
                "file_b": rel_b,
                "start_b": filtered_by_file[rel_b][i_b][0],
                "end_b": filtered_by_file[rel_b][end_b - 1][0],
                "lines": end_a - i_a,
            }
        )
    return kept


def run_dupes(root: Path, rel_files: list[str], min_lines: int) -> list[dict]:
    filtered_by_file = {rel: strip_lines_for_dupes((root / rel).read_text()) for rel in rel_files}
    blocks = find_duplicate_blocks(filtered_by_file, min_lines)
    items: list[dict] = []
    for b in blocks:
        items.append(
            {
                "rel": b["file_a"],
                "line": b["start_a"],
                "col": 0,
                "tool": "dupes",
                "rule": None,
                "duplicate_of": f"{b['file_b']}:{b['start_b']}-{b['end_b']}",
                "dup_lines": b["lines"],
            }
        )
        items.append(
            {
                "rel": b["file_b"],
                "line": b["start_b"],
                "col": 0,
                "tool": "dupes",
                "rule": None,
                "duplicate_of": f"{b['file_a']}:{b['start_a']}-{b['end_a']}",
                "dup_lines": b["lines"],
            }
        )
    return items


# ── tool runners ──────────────────────────────────────────────────────────────
# Each returns a flat list of {rel, line, col, tool, rule} — normalized
# before anything downstream has to know these are three different tools.


def _normalize_path(root: Path, raw: str) -> str | None:
    p = Path(raw)
    if not p.is_absolute():
        p = (root / p).resolve()
    try:
        return str(p.relative_to(root))
    except ValueError:
        return None  # outside root somehow — caller skips rather than crashes


def run_ruff(root: Path, rel_files: list[str], rules: list[str]) -> list[dict]:
    if not rel_files:
        return []
    try:
        proc = subprocess.run(
            ["ruff", "check", "--select", ",".join(rules), "--output-format=json", *rel_files],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,  # ruff exits 1 when it finds anything — not our error
        )
    except FileNotFoundError:
        raise SystemExit(
            "✗ craftcov needs `ruff` on PATH for this catalog's ruff-mapped entries — "
            "pip install ruff."
        ) from None
    if proc.returncode not in (0, 1):
        raise SystemExit(f"✗ ruff failed:\n{proc.stderr}")
    items = []
    for item in json.loads(proc.stdout or "[]"):
        rel = _normalize_path(root, item["filename"])
        if rel is None:
            continue
        items.append(
            {
                "rel": rel,
                "line": item["location"]["row"],
                "col": item["location"]["column"],
                "tool": "ruff",
                "rule": item["code"],
            }
        )
    return items


def run_pylint(root: Path, rel_files: list[str], rules: list[str]) -> list[dict]:
    if not rel_files:
        return []
    try:
        proc = subprocess.run(
            [
                "pylint",
                "--disable=all",
                f"--enable={','.join(rules)}",
                "--output-format=json",
                *rel_files,
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,  # pylint's exit code is a findings bitmask, not a crash signal
        )
    except FileNotFoundError:
        raise SystemExit(
            "✗ craftcov needs `pylint` on PATH for this catalog's pylint-mapped entries "
            "(extract-class) — pip install pylint, or drop that entry's detector in catalog.yaml."
        ) from None
    try:
        raw = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        raise SystemExit(
            f"✗ pylint produced unparseable output:\n{proc.stdout}\n{proc.stderr}"
        ) from None
    items = []
    for item in raw:
        rel = _normalize_path(root, item["path"])
        if rel is None:
            continue
        items.append(
            {
                "rel": rel,
                "line": item["line"],
                "col": item.get("column", 0),
                "tool": "pylint",
                "rule": item["message-id"],
            }
        )
    return items


_VULTURE_LINE = re.compile(r"^(?P<path>.+):(?P<line>\d+): .+ \((?P<pct>\d+)% confidence\)$")


def run_vulture(root: Path, rel_files: list[str], min_confidence: int) -> list[dict]:
    """min_confidence is vulture's own per-finding score, not craftcov's
    invention — on a real codebase (kai-ster, checked while building this)
    it clusters hard into two tiers: unused *variables* at 100% (redundant
    with ruff's own F841 — vulture adds nothing there) and unused
    functions/classes/methods at 60% (vulture's own floor for "fairly sure
    but could be wrong" — decorator-registered pytest-bdd steps and
    Textual's on_* naming-convention handlers are exactly the kind of
    indirect-call pattern that scores here without being genuinely dead).
    Default 0 (vulture's own default: report everything) trades precision
    for recall on purpose — raise it via --vulture-min-confidence once
    you've triaged a first pass and know your codebase's noise floor."""
    if not rel_files:
        return []
    try:
        proc = subprocess.run(
            ["vulture", f"--min-confidence={min_confidence}", *rel_files],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,  # vulture exits non-zero when it finds anything — not our error
        )
    except FileNotFoundError:
        raise SystemExit(
            "✗ craftcov needs `vulture` on PATH for this catalog's vulture-mapped entries "
            "(dead-code) — pip install vulture, or drop that entry's vulture detector "
            "in catalog.yaml."
        ) from None
    items = []
    for line in proc.stdout.splitlines():
        m = _VULTURE_LINE.match(line)
        if not m:
            # vulture has no machine-readable format; skip anything that doesn't parse
            continue
        rel = _normalize_path(root, m.group("path"))
        if rel is None:
            continue
        items.append(
            {
                "rel": rel,
                "line": int(m.group("line")),
                "col": 0,
                "tool": "vulture",
                "rule": None,
                "confidence": int(m.group("pct")),
            }
        )
    return items


# ── scanning ──────────────────────────────────────────────────────────────────


def scan_files(
    root: Path,
    rel_files: list[str],
    rule_maps: dict[str, dict[str, dict]],
    whole_tool: dict[str, dict],
    vulture_min_confidence: int = 0,
) -> dict[str, list[dict]]:
    """relative path -> list of finding dicts, for exactly these files."""
    raw_items: list[dict] = []
    if "ruff" in rule_maps:
        raw_items += run_ruff(root, rel_files, sorted(rule_maps["ruff"]))
    if "pylint" in rule_maps:
        raw_items += run_pylint(root, rel_files, sorted(rule_maps["pylint"]))
    if "vulture" in whole_tool:
        raw_items += run_vulture(root, rel_files, vulture_min_confidence)

    by_file: dict[str, list[dict]] = {rel: [] for rel in rel_files}
    scopes_cache: dict[str, list[tuple[int, int, str, str]]] = {}
    seen: set[tuple[str, int, str]] = set()  # (rel, line, heuristic_id) — dedup across tools

    for item in raw_items:
        rel = item["rel"]
        if rel not in by_file:
            continue  # not one of the files we were asked to scan this run
        if item["tool"] in RULE_BASED_TOOLS:
            entry = rule_maps.get(item["tool"], {}).get(item["rule"])
        else:
            entry = whole_tool.get(item["tool"])
        if entry is None:
            continue  # shouldn't happen (we only ask for mapped rules), but don't crash on it

        dedup_key = (rel, item["line"], entry["id"])
        if dedup_key in seen:
            continue  # another tool already flagged this exact line for this heuristic
        seen.add(dedup_key)

        if rel not in scopes_cache:
            scopes_cache[rel] = build_scope_index((root / rel).read_text())
        cls = enclosing_class(scopes_cache[rel], item["line"])

        by_file[rel].append(
            {
                "line": item["line"],
                "col": item["col"],
                "tool": item["tool"],
                "rule": item["rule"],
                "confidence": item.get("confidence"),  # only vulture sets this
                "heuristic_id": entry["id"],
                "heuristic_code": entry.get("code", ""),
                "class": cls,
            }
        )
    return by_file


# ── cache ─────────────────────────────────────────────────────────────────────


def load_cache(cache_path: Path) -> dict:
    if not cache_path.exists():
        return {"version": CACHE_VERSION, "files": {}}
    try:
        data = json.loads(cache_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"version": CACHE_VERSION, "files": {}}
    if data.get("version") != CACHE_VERSION:
        return {"version": CACHE_VERSION, "files": {}}  # schema changed — start fresh, don't crash
    return data


def save_cache(cache_path: Path, cache: dict) -> None:
    cache_path.write_text(json.dumps(cache, indent=0))


# ── report snapshot (for the "changes since last run" diff) ─────────────────
# Deliberately a separate file from .craftcov_cache.json, not a section of
# it: the cache is about per-file findings for incremental *scanning*
# (invalidated by --no-cache, doesn't cover dupes at all — see that
# section); the snapshot is about "what did the summary look like last time
# a report was shown," which should survive --no-cache (forcing a fresh
# recompute doesn't mean you don't still want to know what changed) and
# does need to cover dupes (it's just the aggregate, tool-agnostic).


def load_report_snapshot(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if "by_heuristic" not in data:
        return None  # schema changed — treat as "no previous snapshot" rather than crash
    return data


def save_report_snapshot(path: Path, agg: dict) -> None:
    path.write_text(
        json.dumps(
            {
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "by_heuristic": agg["by_heuristic"],
                "total": agg["total"],
            },
            indent=2,
        )
    )


def diff_by_heuristic(
    old: dict[str, int] | None, new: dict[str, int]
) -> list[tuple[str, int, int]]:
    """(heuristic_id, old_count, new_count) for every heuristic whose count
    changed — old_count/new_count are 0 for a heuristic that's new or fully
    resolved. Empty list (not None) when old is None (first-ever run) is the
    caller's job to distinguish, since "no previous snapshot" and "nothing
    changed" need different messages."""
    ids = set(old or {}) | set(new)
    changed = []
    for hid in ids:
        old_count = (old or {}).get(hid, 0)
        new_count = new.get(hid, 0)
        if old_count != new_count:
            changed.append((hid, old_count, new_count))
    changed.sort(key=lambda t: -abs(t[2] - t[1]))
    return changed


# ── aggregation + report ─────────────────────────────────────────────────────


def aggregate(by_file: dict[str, list[dict]]) -> dict:
    by_heuristic: dict[str, int] = {}
    by_file_count: dict[str, int] = {}
    by_class: dict[str, int] = {}
    by_library: dict[str, int] = {}
    total = 0

    for rel, findings in by_file.items():
        if not findings:
            continue
        by_file_count[rel] = len(findings)
        parts = Path(rel).parts
        library = parts[0] if len(parts) > 1 else "(root)"
        for f in findings:
            total += 1
            by_heuristic[f["heuristic_id"]] = by_heuristic.get(f["heuristic_id"], 0) + 1
            by_library[library] = by_library.get(library, 0) + 1
            key = f"{rel}::{f['class']}" if f["class"] else rel
            by_class[key] = by_class.get(key, 0) + 1

    return {
        "total": total,
        "by_heuristic": by_heuristic,
        "by_file": by_file_count,
        "by_class": by_class,
        "by_library": by_library,
    }


def print_diff_section(
    prev_snapshot: dict | None, agg: dict, catalog_by_id: dict[str, dict]
) -> None:
    if prev_snapshot is None:
        print("Changes since last run: none — this is the first run (no previous snapshot).")
        print()
        return

    changed = diff_by_heuristic(prev_snapshot["by_heuristic"], agg["by_heuristic"])
    when = prev_snapshot.get("generated_at", "an earlier run")
    if not changed:
        print(f"Changes since last run ({when}): none — identical totals.")
        print()
        return

    print(f"Changes since last run ({when})")
    for hid, old_count, new_count in changed:
        code = catalog_by_id.get(hid, {}).get("code", "")
        delta = new_count - old_count
        sign = "+" if delta > 0 else ""
        if old_count == 0:
            tag = " (NEW)"
        elif new_count == 0:
            tag = " (RESOLVED)"
        else:
            tag = ""
        print(f"  {code:7s} {hid:38s} {old_count:5d} -> {new_count:<5d} ({sign}{delta}){tag}")
    old_total = prev_snapshot.get("total", 0)
    total_delta = agg["total"] - old_total
    sign = "+" if total_delta > 0 else ""
    print(f"  {'':7s} {'TOTAL':38s} {old_total:5d} -> {agg['total']:<5d} ({sign}{total_delta})")
    print()


def print_text_report(
    agg: dict,
    catalog_by_id: dict[str, dict],
    by_file: dict[str, list[dict]],
    verbose: bool,
    timing: dict,
    prev_snapshot: dict | None,
    show_diff: bool = True,
    scope_label: str | None = None,
) -> None:
    print("craftCov — craftsmanship heuristic scan")
    print(
        f"Scanned {timing['total_files']} files "
        f"({timing['changed']} changed, {timing['cached']} from cache) in {timing['elapsed']:.2f}s"
    )
    if timing.get("dupes_elapsed", 0) > 0:
        print(
            f"Duplicate-code pass: {timing['dupes_elapsed']:.2f}s (always full-corpus — see README)"
        )
    if scope_label:
        print(
            f"Reporting scope: {scope_label} only "
            "(full corpus was still scanned — see --file's help)"
        )
    print()

    if show_diff:
        print_diff_section(prev_snapshot, agg, catalog_by_id)

    if agg["total"] == 0:
        print("No findings for the detectable heuristics. ✓")
    else:
        print("By heuristic")
        print(f"{'CODE':7s} {'ID':38s} {'COUNT':>6s}  SOURCE")
        rows = sorted(agg["by_heuristic"].items(), key=lambda kv: -kv[1])
        for hid, count in rows:
            entry = catalog_by_id[hid]
            print(f"{entry.get('code', ''):7s} {hid:38s} {count:6d}  {entry['source']}")
        print(f"{'':7s} {'TOTAL':38s} {agg['total']:6d}")
        print()

        print("By file (top 15)")
        for rel, count in sorted(agg["by_file"].items(), key=lambda kv: -kv[1])[:15]:
            print(f"  {count:5d}  {rel}")
        print()

        print("By class (top 15, module-level findings excluded)")
        class_only = {k: v for k, v in agg["by_class"].items() if "::" in k}
        for key, count in sorted(class_only.items(), key=lambda kv: -kv[1])[:15]:
            print(f"  {count:5d}  {key}")
        print()

        print("By library (top-level directory)")
        for lib, count in sorted(agg["by_library"].items(), key=lambda kv: -kv[1]):
            print(f"  {count:5d}  {lib}")

    if verbose and agg["total"] > 0:
        print()
        print("Every finding")
        for rel, findings in sorted(by_file.items()):
            for f in sorted(findings, key=lambda x: x["line"]):
                scope = f" [{f['class']}]" if f["class"] else ""
                rule = f"{f['tool']}:{f['rule']}" if f["rule"] else f["tool"]
                if f.get("confidence") is not None:
                    rule += f" {f['confidence']}%"
                dup = (
                    f"  <-> {f['duplicate_of']} ({f['dup_lines']} lines)"
                    if f.get("duplicate_of")
                    else ""
                )
                print(
                    f"  {rel}:{f['line']}  {f['heuristic_code']} {f['heuristic_id']} "
                    f"({rule}){scope}{dup}"
                )

    n_detectable = sum(1 for e in catalog_by_id.values() if e.get("detectors"))
    n_total = len(catalog_by_id)
    print()
    print(
        f"{n_detectable}/{n_total} heuristics have an automatic detector "
        f"({100 * n_detectable // n_total}%) — the rest need the procedure in "
        f"CRAFTSMANSHIP.md (ask the developer), not a scan. Run with "
        f"--list-detectors to see which is which."
    )


def print_detector_list(catalog: list[dict]) -> None:
    for e in catalog:
        detectors = e.get("detectors")
        if not detectors:
            status = "— (needs judgment, see procedure)"
        else:
            parts = []
            for d in detectors:
                parts.append(f"{d['tool']}: {', '.join(d['rules'])}" if "rules" in d else d["tool"])
            status = " + ".join(parts)
        print(f"{e.get('code', ''):7s} {e['id']:38s} {status}")


def merge_corpus_findings(
    root: Path, all_files: list[str], by_file: dict[str, list[dict]], corpus_tool: dict[str, dict]
) -> None:
    """Runs corpus-wide tools (currently just `dupes`) over every file,
    every run — never through the per-file cache (see the module docstring
    on `dupes`'s own section for why). Appends into by_file in place."""
    if "dupes" not in corpus_tool:
        return
    cfg = corpus_tool["dupes"]
    entry = cfg["entry"]
    min_lines = cfg.get(
        "min_lines", 8
    )  # see catalog.yaml's comment for the PMD-calibration behind this
    items = run_dupes(root, all_files, min_lines)

    scopes_cache: dict[str, list[tuple[int, int, str, str]]] = {}
    for item in items:
        rel = item["rel"]
        if rel not in scopes_cache:
            scopes_cache[rel] = build_scope_index((root / rel).read_text())
        cls = enclosing_class(scopes_cache[rel], item["line"])
        by_file.setdefault(rel, []).append(
            {
                "line": item["line"],
                "col": item["col"],
                "tool": item["tool"],
                "rule": item["rule"],
                "confidence": None,
                "heuristic_id": entry["id"],
                "heuristic_code": entry.get("code", ""),
                "class": cls,
                "duplicate_of": item["duplicate_of"],
                "dup_lines": item["dup_lines"],
            }
        )


# ── main ──────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--path", default=".", help="repo root to scan (default: .)")
    parser.add_argument("--cache-file", default=str(DEFAULT_CACHE_PATH))
    parser.add_argument(
        "--no-cache", action="store_true", help="ignore and overwrite the existing cache"
    )
    parser.add_argument(
        "--snapshot-file",
        default=str(DEFAULT_SNAPSHOT_PATH),
        help="where the by-heuristic totals from this run are saved, to diff against next time",
    )
    parser.add_argument(
        "--no-diff",
        action="store_true",
        help="don't print the 'changes since last run' section "
        "(the snapshot still updates for next time)",
    )
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="list every finding, not just the summary"
    )
    parser.add_argument(
        "--list-detectors",
        action="store_true",
        help="print which heuristics are detectable and how, then exit",
    )
    parser.add_argument(
        "--file",
        default=None,
        help="report only findings in this one file (a REPORT filter, applied after the "
        "full corpus scan — dupes still needs every file scanned to find a match's "
        "other half, so this never restricts what gets scanned, only what gets "
        "shown/counted). Path relative to --path, or absolute.",
    )
    parser.add_argument(
        "--class",
        dest="cls",
        default=None,
        help="further restrict --file to one enclosing class (module-level findings "
        "excluded). Ignored without --file.",
    )
    parser.add_argument(
        "--vulture-min-confidence",
        type=int,
        default=0,
        metavar="N",
        help="vulture's own confidence floor (0-100, default 0 = vulture's default: "
        "report everything). On a real codebase this tends to cluster at 60%% "
        "(functions/classes/methods, vulture's own 'fairly sure but could be wrong' "
        "tier) and 100%% (unused variables, redundant with ruff's own F841). The cache "
        "doesn't know about this flag — changing it between runs needs --no-cache "
        "to actually take effect.",
    )
    args = parser.parse_args()

    catalog = load_catalog()
    catalog_by_id = {e["id"]: e for e in catalog}

    if args.list_detectors:
        print_detector_list(catalog)
        return 0

    rule_maps, whole_tool, corpus_tool = build_detector_index(catalog)
    root = Path(args.path).resolve()
    cache_path = Path(args.cache_file)
    snapshot_path = Path(args.snapshot_file)
    # --file scopes the report to a slice of the repo; the snapshot/diff
    # feature is a whole-repo view (and shared by every scoped run, so a
    # scoped run must not read or overwrite it — that'd corrupt the next
    # whole-repo run's baseline with a single file's totals).
    diff_active = not args.no_diff and not args.file
    prev_snapshot = load_report_snapshot(snapshot_path) if diff_active else None

    t0 = time.monotonic()
    files = discover_python_files(root)  # relative paths
    cache = {"version": CACHE_VERSION, "files": {}} if args.no_cache else load_cache(cache_path)
    cached_files = cache["files"]

    hashes = {rel: file_hash(root, rel) for rel in files}
    changed = [rel for rel in files if cached_files.get(rel, {}).get("hash") != hashes[rel]]
    unchanged = [rel for rel in files if rel not in changed]

    new_findings = (
        scan_files(root, changed, rule_maps, whole_tool, args.vulture_min_confidence)
        if changed
        else {}
    )

    by_file: dict[str, list[dict]] = {}
    for rel in unchanged:
        by_file[rel] = cached_files[rel]["findings"]
    for rel in changed:
        entry = new_findings.get(rel, [])
        by_file[rel] = entry
        cached_files[rel] = {"hash": hashes[rel], "findings": entry}

    # drop cache entries for files that no longer exist
    for stale in set(cached_files) - set(hashes):
        del cached_files[stale]

    save_cache(cache_path, cache)  # before dupes: those never get persisted

    dupes_t0 = time.monotonic()
    merge_corpus_findings(root, files, by_file, corpus_tool)
    dupes_elapsed = time.monotonic() - dupes_t0

    scope_label = None
    if args.file:
        target = _normalize_path(root, args.file)
        if target is None or target not in files:
            raise SystemExit(
                f"✗ --file {args.file!r} not found among this repo's tracked "
                f".py files (relative to {root})"
            )
        findings = by_file.get(target, [])
        if args.cls:
            findings = [f for f in findings if f.get("class") == args.cls]
        by_file = {target: findings}
        scope_label = f"{target}::{args.cls}" if args.cls else target

    agg = aggregate(by_file)
    timing = {
        "total_files": len(files),
        "changed": len(changed),
        "cached": len(unchanged),
        "elapsed": time.monotonic() - t0,
        "dupes_elapsed": dupes_elapsed,
    }

    if args.format == "json":
        payload = {"summary": agg, "findings": by_file, "timing": timing, "scope": scope_label}
        if diff_active:
            payload["diff"] = {
                "previous_generated_at": (prev_snapshot or {}).get("generated_at"),
                "by_heuristic": [
                    {"heuristic_id": hid, "old": old_count, "new": new_count}
                    for hid, old_count, new_count in diff_by_heuristic(
                        (prev_snapshot or {}).get("by_heuristic"), agg["by_heuristic"]
                    )
                ],
            }
        print(json.dumps(payload, indent=2))
    else:
        print_text_report(
            agg,
            catalog_by_id,
            by_file,
            args.verbose,
            timing,
            prev_snapshot,
            show_diff=diff_active,
            scope_label=scope_label,
        )

    if not args.file:
        save_report_snapshot(snapshot_path, agg)

    return 0


if __name__ == "__main__":
    sys.exit(main())
