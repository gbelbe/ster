"""Ontology publication pipeline for ster."""

from __future__ import annotations

import datetime
import re
import subprocess
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, OWL, XSD

from .model import Taxonomy


class PublishError(Exception):
    """Raised when the publish pipeline cannot proceed."""


# ── version helpers ───────────────────────────────────────────────────────────


def build_version_string(base: str, date: str, sha: str) -> str:
    """Build 'base+date.sha' version string."""
    return f"{base}+{date}.{sha}"


def bump_version(current: str, kind: str) -> str:
    """Bump a semver string. Strips a leading 'v' if present."""
    v = current.lstrip("v")
    parts = v.split(".")
    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


# ── version triple patching ───────────────────────────────────────────────────


def patch_version_triples(file_path: Path, version_str: str, base_version: str) -> None:
    """Patch OWL version triples into file_path in place."""
    from .store import graph_to_taxonomy

    g = Graph()
    g.parse(str(file_path), format=_detect_format(file_path))
    t = graph_to_taxonomy(g)

    assert t.ontology_uri, "ontology URI must be set before patching version"
    ont_ref = URIRef(t.ontology_uri)

    version_iri = f"{t.ontology_uri}/{base_version}"

    g.set((ont_ref, OWL.versionInfo, Literal(version_str)))
    g.set((ont_ref, OWL.versionIRI, URIRef(version_iri)))
    if t.prior_version:
        g.set((ont_ref, OWL.priorVersion, URIRef(t.prior_version)))
    today = datetime.date.today().isoformat()
    g.set((ont_ref, DCTERMS.modified, Literal(today, datatype=XSD.date)))

    fmt = _detect_format(file_path)
    file_path.write_text(g.serialize(format=fmt))


def _patch_version_in_graph(g: Graph, version_str: str, base_version: str) -> None:
    """Patch version triples directly into an rdflib Graph (in memory)."""
    from rdflib import RDF

    for ont_ref in g.subjects(RDF.type, OWL.Ontology):
        version_iri = f"{str(ont_ref)}/{base_version}"
        g.set((ont_ref, OWL.versionInfo, Literal(version_str)))
        g.set((ont_ref, OWL.versionIRI, URIRef(version_iri)))
        today = datetime.date.today().isoformat()
        g.set((ont_ref, DCTERMS.modified, Literal(today, datatype=XSD.date)))
        break


# ── publish context ───────────────────────────────────────────────────────────


@dataclass
class PublishContext:
    """All data available to serializers during a publish run.

    Built once per publish, shared across all serializers and all output
    directories.  Serializers that do not need every field simply ignore it.
    """

    source_file: Path  # original source path — carries the stem / filename
    taxonomy: Taxonomy  # structured model (needed by KI, analysis serializers)
    graph: Graph  # version-patched rdflib graph (needed by TTL, HTML)
    version_str: str  # full version e.g. "1.2.0+20260528.abc1234"
    base_version: str  # semver base e.g. "1.2.0"


# ── serializer protocol ───────────────────────────────────────────────────────


@runtime_checkable
class ArtifactSerializer(Protocol):
    """Contract for a publish format.

    Implement ``write`` to serialise the ontology into ``dest_dir`` in whatever
    format makes sense, and return the list of files written.  Raise any
    exception on unrecoverable failure; the pipeline isolates failures so that
    one broken serializer never blocks the others.
    """

    name: str

    def write(self, ctx: PublishContext, dest_dir: Path) -> list[Path]: ...


# ── built-in serializers ──────────────────────────────────────────────────────


class TurtleSerializer:
    """Write the ontology as a Turtle (.ttl) file."""

    name = "turtle"

    def write(self, ctx: PublishContext, dest_dir: Path) -> list[Path]:
        path = dest_dir / ctx.source_file.name
        path.write_text(ctx.graph.serialize(format="turtle"))
        return [path]


class HtmlSerializer:
    """Write HTML documentation via pyLODE.  Silently skipped when not installed."""

    name = "html"

    def write(self, ctx: PublishContext, dest_dir: Path) -> list[Path]:
        import tempfile

        from .html_export import render_html

        with tempfile.NamedTemporaryFile(suffix=".ttl", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp_path.write_text(ctx.graph.serialize(format="turtle"))

        try:
            html = render_html(tmp_path)
        except Exception:
            return []
        finally:
            tmp_path.unlink(missing_ok=True)

        html_path = dest_dir / "index.html"
        html_path.write_text(html)
        return [html_path]


def _default_serializers() -> list[ArtifactSerializer]:
    """Return the built-in serializers used when none are supplied by the caller."""
    return [TurtleSerializer(), HtmlSerializer()]


# ── pipeline ──────────────────────────────────────────────────────────────────


def _build_context(source_file: Path, version_str: str, base_version: str) -> PublishContext:
    """Parse source_file, apply version triples, and return a shared PublishContext.

    The source file on disk is never modified; patching happens in memory only.
    """
    from .store import graph_to_taxonomy

    g = Graph()
    g.parse(str(source_file), format=_detect_format(source_file))
    _patch_version_in_graph(g, version_str, base_version)
    taxonomy = graph_to_taxonomy(g)
    return PublishContext(
        source_file=source_file,
        taxonomy=taxonomy,
        graph=g,
        version_str=version_str,
        base_version=base_version,
    )


def _run_serializers(
    ctx: PublishContext,
    dirs: list[Path],
    serializers: list[ArtifactSerializer],
) -> list[Path]:
    """Write every format to every output directory.

    Failures are isolated per serializer: one broken format never prevents the
    others from running.  Directories are created if they do not exist.
    """
    artifacts: list[Path] = []
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        for s in serializers:
            try:
                artifacts.extend(s.write(ctx, d))
            except Exception:
                pass
    return artifacts


def write_stable_artifacts(
    source_file: Path,
    publish_dir: Path,
    base_version: str,
    version_str: str,
    serializers: list[ArtifactSerializer] | None = None,
) -> list[Path]:
    """Write versioned + latest artifacts for a stable release.

    Returns the list of all written file paths.
    Pass ``serializers`` to override or extend the default set (TTL + HTML).
    """
    ctx = _build_context(source_file, version_str, base_version)
    dirs = [publish_dir / f"v{base_version}", publish_dir / "latest"]
    return _run_serializers(ctx, dirs, serializers or _default_serializers())


def write_dev_artifacts(
    source_file: Path,
    publish_dir: Path,
    version_str: str,
    serializers: list[ArtifactSerializer] | None = None,
) -> list[Path]:
    """Write dev-channel artifact.  The source file on disk is NOT modified.

    Pass ``serializers`` to override or extend the default set (TTL + HTML).
    """
    base = version_str.split("+")[0] if "+" in version_str else version_str
    ctx = _build_context(source_file, version_str, base)
    dirs = [publish_dir / "dev"]
    return _run_serializers(ctx, dirs, serializers or _default_serializers())


def _dev_base_version(version_info: str | None) -> str:
    """Return the base semver for a dev rebuild, defaulting to 0.1.0.

    Strips any ``+local`` build metadata; an empty/None version yields 0.1.0.
    """
    if not version_info:
        return "0.1.0"
    return version_info.split("+")[0]


def regenerate_dev_artifacts(source_file: Path, publish_dir: Path | None = None) -> list[Path]:
    """Rebuild the dev-channel TTL + HTML so ``<publish_dir>/dev/`` mirrors *source_file*.

    Reads the base version from the file (falling back to 0.1.0), stamps a dev
    version string (base + today + git short-sha), and writes the dev artifacts.
    The source file is never modified and nothing is committed. *publish_dir*
    defaults to ``<source_file parent>/ontology``. Returns the written paths.
    """
    from .store import load

    base = _dev_base_version(load(source_file).version_info)
    version_str = build_version_string(base, _today_str(), _git_short_sha(source_file.parent))
    pub = publish_dir or source_file.parent / "ontology"
    return write_dev_artifacts(source_file, pub, version_str)


# ── git-tag-driven semver versioning ──────────────────────────────────────────

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_VALID_BUMPS = ("major", "minor", "patch")


@runtime_checkable
class GitTagger(Protocol):
    """The git operations a stable release needs: read tags, commit, tag, push."""

    def list_tags(self) -> list[str]: ...

    def commit_paths(self, paths: list[Path], message: str) -> str | None: ...

    def create_tag(self, tag: str, message: str) -> bool: ...

    def push_release(self, tag: str) -> bool: ...


def semver_bump_from_choice(choice: str) -> str:
    """Normalise a semver bump kind; raise ValueError unless major/minor/patch."""
    kind = choice.strip().lower()
    if kind not in _VALID_BUMPS:
        raise ValueError(f"invalid bump {choice!r}: expected one of {', '.join(_VALID_BUMPS)}")
    return kind


def ontology_tag(stem: str, version: str) -> str:
    """Git tag name for an ontology release: ``<stem>/v<version>``.

    The ``<stem>/`` prefix keeps ontology tags out of the bare ``vX.Y.Z``
    namespace used by the PyPI package release, and lets multiple ontologies
    coexist in one repository.
    """
    return f"{stem}/v{version}"


def parse_ontology_tag(tag: str, stem: str) -> str | None:
    """Return the semver if *tag* is this ontology's ``<stem>/vX.Y.Z``, else None."""
    prefix = f"{stem}/v"
    if not tag.startswith(prefix):
        return None
    version = tag[len(prefix) :]
    return version if _SEMVER_RE.match(version) else None


def latest_ontology_version(tags: list[str], stem: str) -> str | None:
    """Highest semver among this ontology's tags, or None when there are none."""
    versions = [v for t in tags if (v := parse_ontology_tag(t, stem)) is not None]
    if not versions:
        return None
    return max(versions, key=lambda v: tuple(int(x) for x in v.split(".")))


def next_ontology_version(current: str | None, bump: str) -> str:
    """Next semver after *current*, seeding ``0.1.0`` when there is no prior tag."""
    kind = semver_bump_from_choice(bump)
    return bump_version(current if current is not None else "0.1.0", kind)


@dataclass(frozen=True)
class ReleaseResult:
    """Outcome of a stable release: the new version, its tag, files, and push state."""

    version: str  # base semver e.g. "1.2.0"
    version_str: str  # full version e.g. "1.2.0+20260606.abc1234"
    tag: str  # ontology tag e.g. "onto/v1.2.0"
    artifacts: list[Path]
    pushed: bool  # True when the commit + tag were pushed to a remote


def perform_stable_release(
    taxonomy_file: Path,
    publish_dir: Path,
    bump: str,
    git: GitTagger,
    serializers: list[ArtifactSerializer] | None = None,
) -> ReleaseResult:
    """Run a git-tag-driven stable release and return its :class:`ReleaseResult`.

    Reads the latest ontology tag to find the current version, applies *bump*,
    stamps the new version into *taxonomy_file*, writes the versioned + latest
    artifacts, commits the file and artifacts, creates the ontology tag, then
    pushes the commit and tag to the remote (a no-op when none is configured).
    """
    kind = semver_bump_from_choice(bump)
    stem = taxonomy_file.stem
    current = latest_ontology_version(git.list_tags(), stem)
    base_version = next_ontology_version(current, kind)
    version_str = build_version_string(
        base_version, _today_str(), _git_short_sha(taxonomy_file.parent)
    )
    patch_version_triples(taxonomy_file, version_str, base_version)
    artifacts = write_stable_artifacts(
        taxonomy_file, publish_dir, base_version, version_str, serializers
    )
    git.commit_paths([taxonomy_file, publish_dir], f"release({stem}): v{base_version}")
    tag = ontology_tag(stem, base_version)
    git.create_tag(tag, f"{stem} {base_version}")
    pushed = git.push_release(tag)
    return ReleaseResult(base_version, version_str, tag, artifacts, pushed)


# ── publish screen: listing published pages ──────────────────────────────────

_VERSION_DIR_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True)
class PublishedPage:
    """One openable artifact under the publish tree."""

    group: str  # "Dev" | "Latest" | "v1.2.0"
    kind: str  # "html" | "ttl"
    path: Path


@dataclass(frozen=True)
class PublishMenuRow:
    """One row of the Version & Publish screen."""

    label: str
    action: str  # "publish_stable" | "open"
    url: str | None = None
    path: Path | None = None


def _version_dirs_desc(publish_dir: Path) -> list[Path]:
    """Version directories (v{semver}) under *publish_dir*, newest first."""
    if not publish_dir.is_dir():
        return []
    vdirs = [d for d in publish_dir.iterdir() if d.is_dir() and _VERSION_DIR_RE.match(d.name)]
    return sorted(
        vdirs,
        key=lambda d: tuple(int(x) for x in _VERSION_DIR_RE.match(d.name).groups()),  # type: ignore[union-attr]
        reverse=True,
    )


def _ordered_group_dirs(publish_dir: Path) -> list[tuple[Path, str]]:
    """(*directory*, *display label*) pairs in screen order: Dev, Latest, versions."""
    out: list[tuple[Path, str]] = []
    for name, label in (("dev", "Dev"), ("latest", "Latest")):
        d = publish_dir / name
        if d.is_dir():
            out.append((d, label))
    out.extend((d, d.name) for d in _version_dirs_desc(publish_dir))
    return out


def _group_pages(group_dir: Path, label: str) -> list[PublishedPage]:
    """HTML page (if any) then the Turtle file (if any) for one group."""
    pages: list[PublishedPage] = []
    html = group_dir / "index.html"
    if html.is_file():
        pages.append(PublishedPage(label, "html", html))
    ttls = sorted(group_dir.glob("*.ttl"))
    if ttls:
        pages.append(PublishedPage(label, "ttl", ttls[0]))
    return pages


def discover_published_pages(publish_dir: Path) -> list[PublishedPage]:
    """Return the openable pages under *publish_dir*, in screen order.

    Order: Dev, Latest, then each version newest-first; within a group the HTML
    page precedes the Turtle file. Groups that do not exist are omitted.
    """
    pages: list[PublishedPage] = []
    for group_dir, label in _ordered_group_dirs(publish_dir):
        pages.extend(_group_pages(group_dir, label))
    return pages


def page_url(base_url: str | None, publish_dir: Path, path: Path) -> str:
    """Full URL for *path*: a served URL under the server mount, else ``file://``."""
    if not base_url:
        return path.as_uri()
    base = base_url.rstrip("/")
    mount = publish_dir.name
    return f"{base}/{mount}/{path.relative_to(publish_dir).as_posix()}"


def build_publish_menu(
    pages: list[PublishedPage], base_url: str | None, publish_dir: Path
) -> list[PublishMenuRow]:
    """Rows for the publish screen: the stable-publish action, then one row per page."""
    rows = [PublishMenuRow("▸ Publish a new Stable version", "publish_stable")]
    for pg in pages:
        url = page_url(base_url, publish_dir, pg.path)
        rows.append(PublishMenuRow(f"{pg.group} · {pg.kind}   {url}", "open", url, pg.path))
    rows.append(PublishMenuRow("← Back to menu", "back"))  # always an explicit way home
    return rows


# ── opening published artifacts in the browser ────────────────────────────────


def _ordered_pages(artifacts: list[Path]) -> list[Path]:
    """Return the TTL artifact(s) first, then the HTML page(s); ignore the rest."""
    ttls = [a for a in artifacts if a.suffix.lower() == ".ttl"]
    htmls = [a for a in artifacts if a.suffix.lower() in (".html", ".htm")]
    return ttls + htmls


def served_artifact_urls(base_url: str, publish_dir: Path, artifacts: list[Path]) -> list[str]:
    """Map written *artifacts* to served URLs under the server's publish mount.

    The graph server mounts *publish_dir* at ``/{publish_dir.name}`` (e.g.
    ``/ontology``), so an artifact at ``<publish_dir>/dev/index.html`` is served
    at ``<base_url>/ontology/dev/index.html``.  The TTL is listed before the HTML;
    non-TTL/HTML artifacts are ignored.
    """
    base = base_url.rstrip("/")
    mount = publish_dir.name
    return [
        f"{base}/{mount}/{a.relative_to(publish_dir).as_posix()}" for a in _ordered_pages(artifacts)
    ]


def open_dev_artifacts(
    publish_dir: Path,
    artifacts: list[Path],
    base_url: str | None,
    opener: Callable[[str], object] = webbrowser.open,
) -> list[str]:
    """Open the dev TTL and HTML artifacts (TTL first), returning the opened URLs.

    When *base_url* is given the pages are opened as served URLs under the
    server's ``/{publish_dir.name}`` mount; otherwise they fall back to
    ``file://`` paths.  *opener* is injected for testing.
    """
    if base_url:
        urls = served_artifact_urls(base_url, publish_dir, artifacts)
    else:
        urls = [a.as_uri() for a in _ordered_pages(artifacts)]
    for url in urls:
        opener(url)
    return urls


# ── pre-flight gate ───────────────────────────────────────────────────────────


def pre_flight(taxonomy: Taxonomy) -> None:
    """Raise PublishError if basic pre-conditions are not met."""
    if not taxonomy.ontology_uri:
        raise PublishError("ontology URI is not set. Add an owl:Ontology declaration to your file.")


# ── helpers ───────────────────────────────────────────────────────────────────


def _detect_format(path: Path) -> str:
    ext = path.suffix.lower()
    return {".ttl": "turtle", ".rdf": "xml", ".xml": "xml", ".owl": "xml"}.get(ext, "turtle")


def _git_short_sha(repo_dir: Path | None = None) -> str:
    r = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        cwd=repo_dir,
    )
    return r.stdout.strip() if r.returncode == 0 else "unknown"


def _today_str() -> str:
    return datetime.date.today().strftime("%Y%m%d")
