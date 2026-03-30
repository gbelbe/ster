"""HTML export using pyLODE's VocPub profile.

Generates one HTML file per language found in the taxonomy. Each file includes
a header language-switcher bar that links to the other language versions.
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path


@contextlib.contextmanager
def _patch_missing_pyproject():
    """Work around pyLODE 3.x bug.

    pyLODE's ``version.py`` does ``Path(...).open("rb")`` at module-import
    time to read ``<site-packages>/pyproject.toml``.  That file does not
    exist when pyLODE is installed as a wheel, causing a crash.

    We temporarily patch ``pathlib.Path.open`` (not ``builtins.open``) to
    return a minimal in-memory stub for any nonexistent ``pyproject.toml``.
    """
    import pathlib

    _stub = b'[project]\nname = "pylode"\nversion = "3.0.0"\n'
    _orig = pathlib.Path.open

    def _mock(self, mode="r", *args, **kwargs):
        if self.name == "pyproject.toml" and not self.exists():
            return io.BytesIO(_stub) if "b" in str(mode) else io.StringIO(_stub.decode())
        return _orig(self, mode, *args, **kwargs)

    pathlib.Path.open = _mock  # type: ignore[method-assign]
    try:
        yield
    finally:
        pathlib.Path.open = _orig  # type: ignore[method-assign]


# ── language detection ────────────────────────────────────────────────────────


def _available_languages(taxonomy: object) -> list[str]:
    """Return sorted list of language codes present in the taxonomy."""
    from .model import Taxonomy

    assert isinstance(taxonomy, Taxonomy)
    langs: set[str] = set()
    for scheme in taxonomy.schemes.values():
        for lbl in scheme.labels:
            langs.add(lbl.lang)
        for desc in scheme.descriptions:
            langs.add(desc.lang)
    for concept in taxonomy.concepts.values():
        for lbl in concept.labels:
            langs.add(lbl.lang)
        for defn in concept.definitions:
            langs.add(defn.lang)
    return sorted(langs)


# ── language-switcher injection ───────────────────────────────────────────────

_SWITCHER_CSS = """
<style>
  #ster-lang-bar {
    background: #2c3e50;
    padding: 10px 24px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 14px;
    display: flex;
    align-items: center;
    gap: 14px;
    position: sticky;
    top: 0;
    z-index: 1000;
    box-shadow: 0 2px 6px rgba(0,0,0,.35);
  }
  #ster-lang-bar .ster-label { color: #95a5a6; }
  #ster-lang-bar a {
    color: #3498db;
    text-decoration: none;
    padding: 3px 8px;
    border-radius: 4px;
    transition: background .15s;
  }
  #ster-lang-bar a:hover { background: rgba(52,152,219,.25); }
  #ster-lang-bar .ster-current {
    color: #fff;
    font-weight: 700;
    padding: 3px 8px;
    border-radius: 4px;
    background: rgba(255,255,255,.12);
  }
</style>
"""


def _lang_switcher_html(stem: str, current: str, all_langs: list[str]) -> str:
    items = []
    for lang in all_langs:
        label = lang.upper()
        if lang == current:
            items.append(f'<span class="ster-current">{label}</span>')
        else:
            items.append(f'<a href="{stem}_{lang}.html">{label}</a>')
    links = "\n    ".join(items)
    return (
        f"{_SWITCHER_CSS}\n"
        f'<div id="ster-lang-bar">\n'
        f'  <span class="ster-label">Language:</span>\n'
        f"  {links}\n"
        f"</div>"
    )


def _inject_switcher(html: str, stem: str, current: str, all_langs: list[str]) -> str:
    """Insert the language bar immediately after the opening <body> tag."""
    bar = _lang_switcher_html(stem, current, all_langs)
    tag = "<body>"
    idx = html.lower().find(tag)
    if idx == -1:
        return bar + "\n" + html
    return html[: idx + len(tag)] + "\n" + bar + html[idx + len(tag) :]


# ── core export ───────────────────────────────────────────────────────────────


def generate_html(
    taxonomy_path: Path,
    output_dir: Path,
    languages: list[str] | None = None,
) -> list[Path]:
    """Generate one HTML file per language via pyLODE's VocPub profile.

    Parameters
    ----------
    taxonomy_path:
        Source ``.ttl`` (or any RDF) file.
    output_dir:
        Directory where HTML files are written.  Created if absent.
    languages:
        Language codes to generate.  Defaults to all languages found in the
        taxonomy.  Pass ``["en"]`` to generate only one file.

    Returns
    -------
    List of ``Path`` objects for the files that were written.

    Raises
    ------
    RuntimeError
        If pyLODE is not installed.
    """
    # The patch must wrap the first import: pyLODE's version.py runs at import
    # time and crashes on the missing pyproject.toml.  Subsequent imports hit
    # the sys.modules cache so the patch is only needed here.
    with _patch_missing_pyproject():
        try:
            from pylode import VocPub  # type: ignore[import]
        except ImportError:
            raise RuntimeError(
                "pyLODE is not installed.\nRun:  pip install pylode\nThen try again."
            )

    from .store import load as _load

    taxonomy = _load(taxonomy_path)
    if languages is None:
        languages = _available_languages(taxonomy)
    if not languages:
        languages = ["en"]

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = taxonomy_path.stem
    multi = len(languages) > 1
    created: list[Path] = []

    for lang in languages:
        try:
            vp = VocPub(ontology=str(taxonomy_path.resolve()), default_language=lang)
        except TypeError:
            # Older pyLODE without default_language support
            vp = VocPub(ontology=str(taxonomy_path.resolve()))
        html = vp.make_html()

        if multi:
            html = _inject_switcher(html, stem, lang, languages)
            out_path = output_dir / f"{stem}_{lang}.html"
        else:
            out_path = output_dir / f"{stem}.html"

        out_path.write_text(html, encoding="utf-8")
        created.append(out_path)

    return created
