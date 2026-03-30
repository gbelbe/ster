"""Tests for workspace, project, validator and workspace_ops."""
from __future__ import annotations
import json
import pytest
from pathlib import Path
from ster.model import Concept, ConceptScheme, Label, LabelType, Taxonomy
from ster.workspace import TaxonomyWorkspace
from ster.project import Project, _git_root
from ster.validator import SkosValidator, ValidationIssue
from ster.workspace_ops import add_mapping, remove_mapping

BASE_A = "https://a.example.org/"
BASE_B = "https://b.example.org/"


# ──────────────────────────── fixtures ───────────────────────────────────────

def _make_taxonomy(base: str, scheme_name: str, concept_names: list[str]) -> Taxonomy:
    t = Taxonomy()
    scheme_uri = base + "scheme"
    scheme = ConceptScheme(uri=scheme_uri)
    scheme.labels.append(Label(lang="en", value=scheme_name))
    t.schemes[scheme_uri] = scheme

    prev_uri: str | None = None
    for name in concept_names:
        uri = base + name
        c = Concept(uri=uri)
        c.labels.append(Label(lang="en", value=name, type=LabelType.PREF))
        if prev_uri is None:
            c.top_concept_of = scheme_uri
            scheme.top_concepts.append(uri)
        else:
            c.broader.append(prev_uri)
            t.concepts[prev_uri].narrower.append(uri)
        t.concepts[uri] = c
        prev_uri = uri
    return t


@pytest.fixture
def tax_a() -> Taxonomy:
    return _make_taxonomy(BASE_A, "Scheme A", ["Dog", "Cat"])


@pytest.fixture
def tax_b() -> Taxonomy:
    return _make_taxonomy(BASE_B, "Scheme B", ["Mammal", "Animal"])


@pytest.fixture
def workspace(tax_a, tax_b, tmp_path) -> TaxonomyWorkspace:
    path_a = tmp_path / "a.ttl"
    path_b = tmp_path / "b.ttl"
    tax_a.file_path = path_a
    tax_b.file_path = path_b
    ws = TaxonomyWorkspace()
    ws.taxonomies[path_a] = tax_a
    ws.taxonomies[path_b] = tax_b
    return ws


# ──────────────────────────── TaxonomyWorkspace ───────────────────────────────

def test_workspace_uri_to_file(workspace, tmp_path):
    assert workspace.uri_to_file(BASE_A + "Dog") == tmp_path / "a.ttl"
    assert workspace.uri_to_file(BASE_B + "Mammal") == tmp_path / "b.ttl"
    assert workspace.uri_to_file("https://unknown.org/X") is None


def test_workspace_concept_for(workspace, tmp_path):
    result = workspace.concept_for(BASE_A + "Dog")
    assert result is not None
    path, concept = result
    assert path == tmp_path / "a.ttl"
    assert concept.uri == BASE_A + "Dog"


def test_workspace_scheme_for(workspace, tmp_path):
    result = workspace.scheme_for(BASE_B + "scheme")
    assert result is not None
    path, scheme = result
    assert path == tmp_path / "b.ttl"


def test_workspace_multiple_schemes(workspace, tax_a, tmp_path):
    assert workspace.multiple_schemes() is True
    single = TaxonomyWorkspace()
    single.taxonomies[tmp_path / "a.ttl"] = tax_a
    assert single.multiple_schemes() is False


def test_workspace_merged_taxonomy(workspace):
    merged = workspace.merged_taxonomy()
    assert BASE_A + "Dog" in merged.concepts
    assert BASE_B + "Mammal" in merged.concepts
    assert BASE_A + "scheme" in merged.schemes
    assert BASE_B + "scheme" in merged.schemes


def test_workspace_from_taxonomy(tax_a, tmp_path):
    path = tmp_path / "a.ttl"
    ws = TaxonomyWorkspace.from_taxonomy(tax_a, path)
    assert len(ws.taxonomies) == 1
    assert ws.concept_for(BASE_A + "Dog") is not None


def test_workspace_unresolved_refs(tmp_path):
    t = _make_taxonomy(BASE_A, "Scheme A", ["Dog"])
    t.concepts[BASE_A + "Dog"].broad_match.append("https://missing.org/X")
    ws = TaxonomyWorkspace()
    ws.taxonomies[tmp_path / "a.ttl"] = t
    unresolved = ws.unresolved_refs()
    assert "https://missing.org/X" in unresolved


# ──────────────────────────── Project ────────────────────────────────────────

def test_project_save_load(tmp_path, monkeypatch):
    monkeypatch.setattr("ster.project._git_root", lambda cwd: None)
    p = Project(root=tmp_path, files=[Path("a.ttl"), Path("b.ttl")], lang="fr")
    p.save()
    loaded = Project.load(tmp_path)
    assert loaded is not None
    assert loaded.lang == "fr"
    assert Path("a.ttl") in loaded.files
    assert Path("b.ttl") in loaded.files


def test_project_resolved_files(tmp_path, monkeypatch):
    monkeypatch.setattr("ster.project._git_root", lambda cwd: None)
    (tmp_path / "a.ttl").write_text("")
    p = Project(root=tmp_path, files=[Path("a.ttl"), Path("missing.ttl")])
    resolved = p.resolved_files()
    assert len(resolved) == 1
    assert resolved[0] == tmp_path / "a.ttl"


def test_project_add_remove_file(tmp_path, monkeypatch):
    monkeypatch.setattr("ster.project._git_root", lambda cwd: None)
    p = Project(root=tmp_path)
    p.add_file(tmp_path / "a.ttl")
    assert Path("a.ttl") in p.files
    p.remove_file(tmp_path / "a.ttl")
    assert Path("a.ttl") not in p.files


def test_project_load_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("ster.project._git_root", lambda cwd: None)
    assert Project.load(tmp_path) is None


# ──────────────────────────── SkosValidator ──────────────────────────────────

def test_validator_no_issues_clean(workspace):
    v = SkosValidator()
    issues = v.validate(workspace)
    # Clean fixture should have no errors
    errors = [i for i in issues if i.severity == "error"]
    assert errors == []


def test_validator_broken_ref(tmp_path):
    t = _make_taxonomy(BASE_A, "Scheme A", ["Dog"])
    t.concepts[BASE_A + "Dog"].broader.append("https://missing.org/X")
    ws = TaxonomyWorkspace()
    ws.taxonomies[tmp_path / "a.ttl"] = t
    issues = SkosValidator().validate(ws)
    codes = [i.code for i in issues]
    assert "broken_ref" in codes


def test_validator_broken_mapping(tmp_path):
    t = _make_taxonomy(BASE_A, "Scheme A", ["Dog"])
    t.concepts[BASE_A + "Dog"].broad_match.append("https://missing.org/X")
    ws = TaxonomyWorkspace()
    ws.taxonomies[tmp_path / "a.ttl"] = t
    issues = SkosValidator().validate(ws)
    codes = [i.code for i in issues]
    assert "broken_mapping" in codes


def test_validator_dup_pref_label(tmp_path):
    t = _make_taxonomy(BASE_A, "Scheme A", ["Dog"])
    c2 = Concept(uri=BASE_A + "Dog2")
    c2.labels.append(Label(lang="en", value="Dog", type=LabelType.PREF))
    c2.broader.append(BASE_A + "Dog")
    t.concepts[BASE_A + "Dog"].narrower.append(BASE_A + "Dog2")
    t.concepts[BASE_A + "Dog2"] = c2
    ws = TaxonomyWorkspace()
    ws.taxonomies[tmp_path / "a.ttl"] = t
    issues = SkosValidator().validate(ws)
    assert any(i.code == "dup_pref_label" for i in issues)


def test_validator_cycle(tmp_path):
    t = _make_taxonomy(BASE_A, "Scheme A", ["A", "B"])
    # Introduce cycle: B broader A AND A broader B
    t.concepts[BASE_A + "A"].broader.append(BASE_A + "B")
    ws = TaxonomyWorkspace()
    ws.taxonomies[tmp_path / "a.ttl"] = t
    issues = SkosValidator().validate(ws)
    assert any(i.code == "cycle" for i in issues)


# ──────────────────────────── workspace_ops ──────────────────────────────────

def test_add_mapping_cross_file(workspace, tmp_path):
    src_file, tgt_file = add_mapping(
        workspace, BASE_A + "Dog", BASE_B + "Mammal", "broadMatch"
    )
    assert src_file == tmp_path / "a.ttl"
    assert tgt_file == tmp_path / "b.ttl"

    src_concept = workspace.concept_for(BASE_A + "Dog")[1]
    tgt_concept = workspace.concept_for(BASE_B + "Mammal")[1]
    assert BASE_B + "Mammal" in src_concept.broad_match
    assert BASE_A + "Dog" in tgt_concept.narrow_match


def test_add_mapping_no_duplicate(workspace):
    add_mapping(workspace, BASE_A + "Dog", BASE_B + "Mammal", "broadMatch")
    add_mapping(workspace, BASE_A + "Dog", BASE_B + "Mammal", "broadMatch")
    src = workspace.concept_for(BASE_A + "Dog")[1]
    assert src.broad_match.count(BASE_B + "Mammal") == 1


def test_add_mapping_symmetric_related(workspace):
    add_mapping(workspace, BASE_A + "Dog", BASE_B + "Mammal", "relatedMatch")
    src = workspace.concept_for(BASE_A + "Dog")[1]
    tgt = workspace.concept_for(BASE_B + "Mammal")[1]
    assert BASE_B + "Mammal" in src.related_match
    assert BASE_A + "Dog" in tgt.related_match


def test_remove_mapping(workspace):
    add_mapping(workspace, BASE_A + "Dog", BASE_B + "Mammal", "broadMatch")
    remove_mapping(workspace, BASE_A + "Dog", BASE_B + "Mammal", "broadMatch")
    src = workspace.concept_for(BASE_A + "Dog")[1]
    tgt = workspace.concept_for(BASE_B + "Mammal")[1]
    assert BASE_B + "Mammal" not in src.broad_match
    assert BASE_A + "Dog" not in tgt.narrow_match


def test_add_mapping_unknown_source_raises(workspace):
    from ster.exceptions import SkostaxError
    with pytest.raises(SkostaxError):
        add_mapping(workspace, "https://unknown.org/X", BASE_B + "Mammal", "broadMatch")
