"""Unit tests for git-tag-driven semver versioning in ster/publish.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from ster.model import Label, LabelType, RDFClass, Taxonomy


def _minimal_taxonomy(uri: str = "https://ex.org/onto") -> Taxonomy:
    t = Taxonomy()
    t.ontology_uri = uri
    t.namespace_bindings[""] = uri + "#"
    t.owl_classes[uri + "#Animal"] = RDFClass(
        uri=uri + "#Animal",
        labels=[Label(lang="en", value="Animal", type=LabelType.PREF)],
    )
    return t


def _write_ttl(path: Path, taxonomy: Taxonomy) -> None:
    from ster.store import taxonomy_to_graph

    g = taxonomy_to_graph(taxonomy)
    path.write_text(g.serialize(format="turtle"))


class _FakeGit:
    """Records commit/tag/push calls and serves a fixed tag list (a GitTagger stand-in)."""

    def __init__(self, tags: list[str] | None = None, push_ok: bool = True) -> None:
        self._tags = tags or []
        self._push_ok = push_ok
        self.commits: list[tuple[list[Path], str]] = []
        self.tags_created: list[tuple[str, str]] = []
        self.pushed: list[str] = []

    def list_tags(self) -> list[str]:
        return list(self._tags)

    def commit_paths(self, paths: list[Path], message: str) -> str | None:
        self.commits.append((paths, message))
        return "deadbee"

    def create_tag(self, tag: str, message: str) -> bool:
        self.tags_created.append((tag, message))
        return True

    def push_release(self, tag: str) -> bool:
        self.pushed.append(tag)
        return self._push_ok


# ── ontology_tag ──────────────────────────────────────────────────────────────


def test_ontology_tag_format() -> None:
    from ster.publish import ontology_tag

    assert ontology_tag("mytaxonomy", "1.2.0") == "mytaxonomy/v1.2.0"


# ── parse_ontology_tag ──────────────────────────────────────────────────────────


def test_parse_ontology_tag_matching_stem() -> None:
    from ster.publish import parse_ontology_tag

    assert parse_ontology_tag("onto/v1.2.0", "onto") == "1.2.0"


def test_parse_ontology_tag_different_stem_is_none() -> None:
    from ster.publish import parse_ontology_tag

    assert parse_ontology_tag("other/v1.2.0", "onto") is None


def test_parse_ontology_tag_bare_pypi_tag_is_none() -> None:
    from ster.publish import parse_ontology_tag

    # The bare vX.Y.Z namespace belongs to the PyPI package release, not an ontology.
    assert parse_ontology_tag("v0.7.0", "onto") is None


def test_parse_ontology_tag_malformed_is_none() -> None:
    from ster.publish import parse_ontology_tag

    assert parse_ontology_tag("onto/v1.2", "onto") is None
    assert parse_ontology_tag("onto/vbeta", "onto") is None


# ── latest_ontology_version ─────────────────────────────────────────────────────


def test_latest_ontology_version_picks_highest() -> None:
    from ster.publish import latest_ontology_version

    tags = ["onto/v1.0.0", "onto/v1.2.0", "onto/v1.1.0"]
    assert latest_ontology_version(tags, "onto") == "1.2.0"


def test_latest_ontology_version_is_numeric_not_lexical() -> None:
    from ster.publish import latest_ontology_version

    tags = ["onto/v9.0.0", "onto/v10.0.0"]
    assert latest_ontology_version(tags, "onto") == "10.0.0"


def test_latest_ontology_version_ignores_other_stems_and_pypi() -> None:
    from ster.publish import latest_ontology_version

    tags = ["v9.9.9", "other/v5.0.0", "onto/v0.3.0", "onto/v0.4.0"]
    assert latest_ontology_version(tags, "onto") == "0.4.0"


def test_latest_ontology_version_none_when_no_match() -> None:
    from ster.publish import latest_ontology_version

    assert latest_ontology_version(["v1.0.0", "other/v2.0.0"], "onto") is None


def test_latest_ontology_version_none_when_empty() -> None:
    from ster.publish import latest_ontology_version

    assert latest_ontology_version([], "onto") is None


# ── next_ontology_version ────────────────────────────────────────────────────────


def test_next_ontology_version_major() -> None:
    from ster.publish import next_ontology_version

    assert next_ontology_version("1.2.3", "major") == "2.0.0"


def test_next_ontology_version_minor() -> None:
    from ster.publish import next_ontology_version

    assert next_ontology_version("1.2.3", "minor") == "1.3.0"


def test_next_ontology_version_patch() -> None:
    from ster.publish import next_ontology_version

    assert next_ontology_version("1.2.3", "patch") == "1.2.4"


def test_next_ontology_version_first_patch_seeds_then_bumps() -> None:
    from ster.publish import next_ontology_version

    # No prior tag → seed 0.1.0, then apply the bump.
    assert next_ontology_version(None, "patch") == "0.1.1"


def test_next_ontology_version_first_minor() -> None:
    from ster.publish import next_ontology_version

    assert next_ontology_version(None, "minor") == "0.2.0"


def test_next_ontology_version_first_major() -> None:
    from ster.publish import next_ontology_version

    assert next_ontology_version(None, "major") == "1.0.0"


def test_next_ontology_version_invalid_bump_raises() -> None:
    from ster.publish import next_ontology_version

    with pytest.raises(ValueError, match="bump"):
        next_ontology_version("1.0.0", "rewrite")


# ── semver_bump_from_choice ──────────────────────────────────────────────────────


def test_semver_bump_from_choice_each_kind() -> None:
    from ster.publish import semver_bump_from_choice

    assert semver_bump_from_choice("major") == "major"
    assert semver_bump_from_choice("minor") == "minor"
    assert semver_bump_from_choice("patch") == "patch"


def test_semver_bump_from_choice_is_case_insensitive() -> None:
    from ster.publish import semver_bump_from_choice

    assert semver_bump_from_choice("MAJOR") == "major"


def test_semver_bump_from_choice_invalid_raises() -> None:
    from ster.publish import semver_bump_from_choice

    with pytest.raises(ValueError, match="bump"):
        semver_bump_from_choice("huge")


# ── perform_stable_release ───────────────────────────────────────────────────────


def test_perform_stable_release_first_release(tmp_path: Path) -> None:
    from ster.publish import perform_stable_release

    src = tmp_path / "onto.ttl"
    _write_ttl(src, _minimal_taxonomy())
    git = _FakeGit(tags=[])
    result = perform_stable_release(src, tmp_path / "ontology", "minor", git)
    assert result.version == "0.2.0"
    assert result.tag == "onto/v0.2.0"


def test_perform_stable_release_bumps_from_latest_tag(tmp_path: Path) -> None:
    from ster.publish import perform_stable_release

    src = tmp_path / "onto.ttl"
    _write_ttl(src, _minimal_taxonomy())
    git = _FakeGit(tags=["onto/v1.2.0", "v9.9.9"])
    result = perform_stable_release(src, tmp_path / "ontology", "patch", git)
    assert result.version == "1.2.1"
    assert result.tag == "onto/v1.2.1"


def test_perform_stable_release_creates_tag_once(tmp_path: Path) -> None:
    from ster.publish import perform_stable_release

    src = tmp_path / "onto.ttl"
    _write_ttl(src, _minimal_taxonomy())
    git = _FakeGit(tags=["onto/v1.2.0"])
    perform_stable_release(src, tmp_path / "ontology", "major", git)
    assert git.tags_created == [("onto/v2.0.0", "onto 2.0.0")]


def test_perform_stable_release_commits_file_and_artifacts(tmp_path: Path) -> None:
    from ster.publish import perform_stable_release

    src = tmp_path / "onto.ttl"
    _write_ttl(src, _minimal_taxonomy())
    pub = tmp_path / "ontology"
    git = _FakeGit(tags=[])
    perform_stable_release(src, pub, "patch", git)
    assert len(git.commits) == 1
    paths, message = git.commits[0]
    assert src in paths
    assert pub in paths
    assert message == "release(onto): v0.1.1"


def test_perform_stable_release_stamps_version_into_source_file(tmp_path: Path) -> None:
    from ster.publish import perform_stable_release

    src = tmp_path / "onto.ttl"
    _write_ttl(src, _minimal_taxonomy())
    git = _FakeGit(tags=["onto/v1.2.0"])
    perform_stable_release(src, tmp_path / "ontology", "minor", git)
    content = src.read_text()
    assert "1.3.0" in content  # versionInfo / versionIRI now reflect the new tag


def test_perform_stable_release_writes_artifacts(tmp_path: Path) -> None:
    from ster.publish import perform_stable_release

    src = tmp_path / "onto.ttl"
    _write_ttl(src, _minimal_taxonomy())
    pub = tmp_path / "ontology"
    git = _FakeGit(tags=[])
    result = perform_stable_release(src, pub, "patch", git)
    assert (pub / "v0.1.1" / "onto.ttl").exists()
    assert (pub / "latest" / "onto.ttl").exists()
    assert result.artifacts


def test_perform_stable_release_pushes_the_tag(tmp_path: Path) -> None:
    from ster.publish import perform_stable_release

    src = tmp_path / "onto.ttl"
    _write_ttl(src, _minimal_taxonomy())
    git = _FakeGit(tags=["onto/v1.2.0"])
    result = perform_stable_release(src, tmp_path / "ontology", "patch", git)
    assert git.pushed == ["onto/v1.2.1"]
    assert result.pushed is True


def test_perform_stable_release_pushed_false_without_remote(tmp_path: Path) -> None:
    from ster.publish import perform_stable_release

    src = tmp_path / "onto.ttl"
    _write_ttl(src, _minimal_taxonomy())
    git = _FakeGit(tags=[], push_ok=False)  # no remote → push is a no-op
    result = perform_stable_release(src, tmp_path / "ontology", "patch", git)
    assert result.pushed is False
