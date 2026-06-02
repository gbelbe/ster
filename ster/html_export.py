"""HTML export via pyLODE.

Chooses the profile automatically based on file content:
  - skos:ConceptScheme present → VocPub  (SKOS vocabulary)
  - owl:Ontology / prof:Profile only     → OntPub (OWL ontology)
  - both present                         → caller passes explicit profile

Generates one HTML file per language for VocPub; a single file for OntPub.
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path
from typing import Literal

Profile = Literal["vocpub", "ontpub"]


@contextlib.contextmanager
def _patch_missing_pyproject():
    """Work around pyLODE 3.x bug: missing pyproject.toml crashes at import time."""
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


# ── Profile detection ─────────────────────────────────────────────────────────


def detect_profile(taxonomy_path: Path) -> Profile | Literal["both"]:
    """Inspect the RDF file and return which pyLODE profile suits it best.

    Returns ``"vocpub"``, ``"ontpub"``, or ``"both"`` when the file contains
    both a skos:ConceptScheme and an owl:Ontology / prof:Profile declaration.
    """
    from rdflib import Graph
    from rdflib.namespace import OWL, PROF, RDF, SKOS

    g = Graph()
    g.parse(str(taxonomy_path))

    has_skos = bool(next(g.subjects(RDF.type, SKOS.ConceptScheme), None))
    has_owl = bool(next(g.subjects(RDF.type, OWL.Ontology), None)) or bool(
        next(g.subjects(RDF.type, PROF.Profile), None)
    )

    if has_skos and has_owl:
        return "both"
    if has_skos:
        return "vocpub"
    return "ontpub"


# ── Language detection (SKOS only) ────────────────────────────────────────────


def _available_languages(taxonomy: object) -> list[str]:
    """Return sorted list of language codes present in a SKOS taxonomy."""
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


# ── Language-switcher injection (VocPub / multi-language) ─────────────────────

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


# ── OntPub graph sanitiser ───────────────────────────────────────────────────


def _sanitize_ontpub_graph(taxonomy_path: Path) -> Path:
    """Return a path to a sanitized temp TTL safe for pyLODE's OntPub.

    Two transformations are applied:
    1. Remove triples whose subject URI ends with ``#`` (bare namespace URIs
       such as ``ns1: a owl:ObjectProperty``). pyLODE's ``generate_fid``
       returns ``None`` for these, causing a crash at ``"#" + None``.
    2. Add ``dcterms:title`` (from ``rdfs:label`` or the URI local name) and
       ``dcterms:description`` (from ``rdfs:label`` or empty) when absent, so
       pyLODE does not concatenate ``None`` into the page title.

    The caller is responsible for deleting the returned temp file.
    """
    import tempfile

    from rdflib import Graph, Literal, URIRef
    from rdflib.namespace import DCTERMS, OWL, RDF, RDFS

    g = Graph()
    g.parse(str(taxonomy_path))

    # 1. Strip bare-namespace subjects (URI ends with '#')
    for subj in set(g.subjects()):
        if isinstance(subj, URIRef) and str(subj).endswith("#"):
            for p, o in list(g.predicate_objects(subj)):
                g.remove((subj, p, o))

    # 2. Ensure dcterms:title and dcterms:description on the owl:Ontology
    for ont_ref in g.subjects(RDF.type, OWL.Ontology):
        if not isinstance(ont_ref, URIRef):
            continue
        label = g.value(ont_ref, RDFS.label)
        label_str = str(label) if label else None
        fallback = str(ont_ref).rstrip("#/").rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        if not g.value(ont_ref, DCTERMS.title):
            g.add((ont_ref, DCTERMS.title, Literal(label_str or fallback)))
        if not g.value(ont_ref, DCTERMS.description):
            g.add((ont_ref, DCTERMS.description, Literal(label_str or "")))
        break

    with tempfile.NamedTemporaryFile(suffix=".ttl", delete=False) as _f:
        tmp = Path(_f.name)
    tmp.write_text(g.serialize(format="turtle"))
    return tmp


# ── pyLODE adapter (the only place pyLODE is imported) ────────────────────────


def is_pylode_available() -> bool:
    """Return True if pyLODE can be imported."""
    with _patch_missing_pyproject():
        try:
            import pylode  # noqa: F401

            return True
        except ImportError:
            return False


def render_html(
    taxonomy_path: Path,
    *,
    profile: Profile | None = None,
    language: str | None = None,
) -> str:
    """Render one pyLODE HTML page for *taxonomy_path* and return it as a string.

    This is the single function that imports pyLODE; every other module renders
    documentation through it (or through ``generate_html``, which builds on it).
    OWL/OntPub input is sanitised first (see ``_sanitize_ontpub_graph``); when
    *language* is given it sets VocPub's default language.

    Raises
    ------
    RuntimeError
        If pyLODE is not installed.
    """
    import logging

    with _patch_missing_pyproject():
        try:
            from pylode import OntPub, VocPub  # type: ignore[import]
        except ImportError:
            raise RuntimeError(
                "pyLODE is not installed.\nRun:  pip install pylode\nThen try again."
            )

    if profile is None:
        detected = detect_profile(taxonomy_path)
        profile = "vocpub" if detected == "both" else detected  # type: ignore[assignment]

    # Silence pyLODE's INFO/DEBUG chatter (root logger + asyncio).
    _root_level = logging.root.level
    _asyncio_logger = logging.getLogger("asyncio")
    _asyncio_level = _asyncio_logger.level
    logging.root.setLevel(logging.WARNING)
    _asyncio_logger.setLevel(logging.WARNING)

    try:
        if profile == "ontpub":
            tmp_path = _sanitize_ontpub_graph(taxonomy_path)
            try:
                return OntPub(ontology=str(tmp_path.resolve())).make_html()
            finally:
                tmp_path.unlink(missing_ok=True)

        # vocpub
        if language is not None:
            try:
                vp = VocPub(ontology=str(taxonomy_path.resolve()), default_language=language)
            except TypeError:
                vp = VocPub(ontology=str(taxonomy_path.resolve()))
        else:
            vp = VocPub(ontology=str(taxonomy_path.resolve()))
        return vp.make_html()
    finally:
        logging.root.setLevel(_root_level)
        _asyncio_logger.setLevel(_asyncio_level)


# ── Core export ───────────────────────────────────────────────────────────────


def generate_html(
    taxonomy_path: Path,
    output_dir: Path,
    languages: list[str] | None = None,
    profile: Profile | None = None,
) -> list[Path]:
    """Generate HTML documentation via pyLODE.

    Parameters
    ----------
    taxonomy_path:
        Source RDF file.
    output_dir:
        Directory where HTML files are written. Created if absent.
    languages:
        Language codes for VocPub multi-language export. Ignored for OntPub.
        Defaults to all languages detected in the file.
    profile:
        ``"vocpub"`` (SKOS) or ``"ontpub"`` (OWL). Auto-detected if omitted.

    Returns
    -------
    List of Path objects for the files written.

    Raises
    ------
    RuntimeError
        If pyLODE is not installed.
    """
    if profile is None:
        detected = detect_profile(taxonomy_path)
        profile = "vocpub" if detected == "both" else detected  # type: ignore[assignment]

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = taxonomy_path.stem
    created: list[Path] = []

    if profile == "ontpub":
        out_path = output_dir / f"{stem}.html"
        out_path.write_text(render_html(taxonomy_path, profile="ontpub"), encoding="utf-8")
        created.append(out_path)
        return created

    # vocpub — one file per language, with a language switcher when multiple
    from .store import load as _load

    taxonomy = _load(taxonomy_path)
    if languages is None:
        languages = _available_languages(taxonomy)
    if not languages:
        languages = ["en"]

    multi = len(languages) > 1
    for lang in languages:
        html = render_html(taxonomy_path, profile="vocpub", language=lang)
        if multi:
            html = _inject_switcher(html, stem, lang, languages)
            out_path = output_dir / f"{stem}_{lang}.html"
        else:
            out_path = output_dir / f"{stem}.html"
        out_path.write_text(html, encoding="utf-8")
        created.append(out_path)

    return created
