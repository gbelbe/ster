"""Tests for workspace, project, validator and workspace_ops."""

from __future__ import annotations

from pathlib import Path

import pytest

from ster.model import Concept, ConceptScheme, Label, LabelType, Taxonomy
from ster.project import Project
from ster.validator import SkosValidator
from ster.workspace import TaxonomyWorkspace
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


def test_project_load_returns_none_on_bad_json(tmp_path, monkeypatch):
    monkeypatch.setattr("ster.project._git_root", lambda cwd: None)
    p = Project(root=tmp_path)
    p.save()
    # Corrupt the file
    (tmp_path / ".ster" / "project.json").write_text("not json")
    assert Project.load(tmp_path) is None


def test_project_add_file_outside_root(tmp_path, monkeypatch):
    monkeypatch.setattr("ster.project._git_root", lambda cwd: None)
    p = Project(root=tmp_path / "sub")
    (tmp_path / "sub").mkdir()
    outside = tmp_path / "other" / "file.ttl"
    p.add_file(outside)
    # Stored as absolute path since it's outside root
    assert outside.resolve() in p.files


def test_project_remove_file_outside_root(tmp_path, monkeypatch):
    monkeypatch.setattr("ster.project._git_root", lambda cwd: None)
    sub = tmp_path / "sub"
    sub.mkdir()
    p = Project(root=sub)
    outside = tmp_path / "other" / "file.ttl"
    p.add_file(outside)
    p.remove_file(outside)
    assert outside.resolve() not in p.files


def test_project_set_lang(tmp_path, monkeypatch):
    monkeypatch.setattr("ster.project._git_root", lambda cwd: None)
    p = Project(root=tmp_path, lang="en")
    p.set_lang("de")
    assert p.lang == "de"
    # Also persisted
    loaded = Project.load(tmp_path)
    assert loaded is not None
    assert loaded.lang == "de"


def test_project_resolved_files_absolute(tmp_path, monkeypatch):
    monkeypatch.setattr("ster.project._git_root", lambda cwd: None)
    abs_file = tmp_path / "abs.ttl"
    abs_file.write_text("")
    p = Project(root=tmp_path / "sub")
    p.files.append(abs_file)  # absolute path stored directly
    resolved = p.resolved_files()
    assert abs_file in resolved


# ──────────────────────────── TaxonomyWorkspace (extra coverage) ─────────────


def test_workspace_from_files(tmp_path):
    from ster import store
    from ster.model import Taxonomy

    t = _make_taxonomy(BASE_A, "Scheme A", ["Dog"])
    path = tmp_path / "a.ttl"
    store.save(t, path)
    ws = TaxonomyWorkspace.from_files([path])
    assert path in ws.taxonomies


def test_workspace_add_file(tmp_path):
    from ster import store

    t = _make_taxonomy(BASE_A, "Scheme A", ["Dog"])
    path = tmp_path / "a.ttl"
    store.save(t, path)
    ws = TaxonomyWorkspace()
    ws.add_file(path)
    assert path in ws.taxonomies


def test_workspace_save_file(tmp_path):
    from ster import store

    t = _make_taxonomy(BASE_A, "Scheme A", ["Dog"])
    path = tmp_path / "a.ttl"
    store.save(t, path)
    ws = TaxonomyWorkspace()
    ws.taxonomies[path] = t
    ws.save_file(path)  # no crash
    assert path.exists()


def test_workspace_save_file_unknown_path(tmp_path):
    ws = TaxonomyWorkspace()
    ws.save_file(tmp_path / "nonexistent.ttl")  # no crash


def test_workspace_save_all(tmp_path):
    from ster import store

    t = _make_taxonomy(BASE_A, "Scheme A", ["Dog"])
    path = tmp_path / "a.ttl"
    store.save(t, path)
    ws = TaxonomyWorkspace()
    ws.taxonomies[path] = t
    ws.save_all()
    assert path.exists()


def test_workspace_taxonomy_for_uri(workspace):
    t = workspace.taxonomy_for_uri(BASE_A + "Dog")
    assert t is not None
    assert BASE_A + "Dog" in t.concepts


def test_workspace_taxonomy_for_uri_unknown(workspace):
    assert workspace.taxonomy_for_uri("https://unknown.org/X") is None


def test_workspace_concept_for_unknown(workspace):
    assert workspace.concept_for("https://unknown.org/X") is None


def test_workspace_scheme_for_unknown(workspace):
    assert workspace.scheme_for("https://unknown.org/X") is None


def test_workspace_is_known_uri(workspace):
    assert workspace.is_known_uri(BASE_A + "Dog") is True
    assert workspace.is_known_uri("https://nope.org/X") is False


def test_workspace_all_schemes(workspace):
    schemes = workspace.all_schemes()
    assert len(schemes) == 2


def test_workspace_scheme_count(workspace):
    assert workspace.scheme_count() == 2


def test_workspace_concept_scheme_uri(workspace):
    uri = workspace.concept_scheme_uri(BASE_A + "Dog")
    assert uri == BASE_A + "scheme"


def test_workspace_concept_scheme_uri_unknown(workspace):
    assert workspace.concept_scheme_uri("https://nope.org/X") is None


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
    src_file, tgt_file = add_mapping(workspace, BASE_A + "Dog", BASE_B + "Mammal", "broadMatch")
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
