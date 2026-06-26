"""Language and general preference persistence for the TUI."""

from __future__ import annotations

import json
from pathlib import Path

# ── lang persistence ──────────────────────────────────────────────────────────


def _lang_prefs_path() -> Path:
    return Path.home() / ".config" / "ster" / "lang_prefs.json"


def _load_lang_pref(file_path: Path) -> str | None:
    p = _lang_prefs_path()
    if p.exists():
        try:
            data = json.loads(p.read_text())
            return data.get(str(file_path.resolve()))
        except Exception:
            pass
    return None


def _save_lang_pref(file_path: Path, lang: str) -> None:
    p = _lang_prefs_path()
    try:
        data: dict = {}
        if p.exists():
            data = json.loads(p.read_text())
        data[str(file_path.resolve())] = lang
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2))
    except Exception:
        pass


# ── configured languages (per file) ──────────────────────────────────────────
# The set of language codes the user authors in — drives how many label / prefLabel
# / comment fields language-dependent create flows offer. Stored per taxonomy file,
# like the display-language preference.


def _configured_langs_path() -> Path:
    return Path.home() / ".config" / "ster" / "configured_langs.json"


def load_configured_langs(file_path: Path) -> list[str]:
    """Return the configured language codes for *file_path* (empty if unset)."""
    p = _configured_langs_path()
    if p.exists():
        try:
            data = json.loads(p.read_text())
            value = data.get(str(file_path.resolve()))
            if isinstance(value, list):
                return [str(code) for code in value]
        except Exception:
            pass
    return []


def save_configured_langs(file_path: Path, langs: list[str]) -> None:
    """Persist the configured language codes for *file_path*."""
    p = _configured_langs_path()
    try:
        data: dict = {}
        if p.exists():
            data = json.loads(p.read_text())
        data[str(file_path.resolve())] = langs
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2))
    except Exception:
        pass


# ── ontology-metadata predicate catalog (global) ──────────────────────────────


def _metadata_props_path() -> Path:
    return Path.home() / ".config" / "ster" / "metadata_props.json"


def load_metadata_props() -> list[tuple[str, str]] | None:
    """The configured ontology-metadata predicates as ``(predicate, label)`` pairs,
    or ``None`` when never configured (callers fall back to the built-in defaults)."""
    p = _metadata_props_path()
    if p.exists():
        try:
            data = json.loads(p.read_text())
            if isinstance(data, list):
                return [
                    (str(e["predicate"]), str(e.get("label", "")))
                    for e in data
                    if isinstance(e, dict) and e.get("predicate")
                ]
        except Exception:
            pass
    return None


def save_metadata_props(props: list[tuple[str, str]]) -> None:
    """Persist the ontology-metadata predicate catalog (global, tool-wide)."""
    p = _metadata_props_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps([{"predicate": pr, "label": lb} for pr, lb in props], indent=2))
    except Exception:
        pass


# ── general prefs ─────────────────────────────────────────────────────────────


def _prefs_path() -> Path:
    return Path.home() / ".config" / "ster" / "prefs.json"


def _load_prefs() -> dict:
    p = _prefs_path()
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}


def _save_prefs(data: dict) -> None:
    p = _prefs_path()
    try:
        existing: dict = {}
        if p.exists():
            existing = json.loads(p.read_text())
        existing.update(data)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(existing, indent=2))
    except Exception:
        pass
