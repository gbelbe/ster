"""Unit tests for ster.init_ci — template validity and detection logic."""

from __future__ import annotations

from pathlib import Path

import yaml

from ster.init_ci import needs_ci, prompt_if_missing

# ── Template validity ─────────────────────────────────────────────────────────


def test_workflow_template_is_valid_yaml():
    from ster.init_ci import _read_template

    content = _read_template("taxonomy-ci.yml")
    parsed = yaml.safe_load(content)
    assert isinstance(parsed, dict)


def test_workflow_triggers_on_push_and_pr():
    from ster.init_ci import _read_template

    parsed = yaml.safe_load(_read_template("taxonomy-ci.yml"))
    # PyYAML parses the bare `on` key as boolean True
    triggers = parsed[True]
    assert "push" in triggers
    assert "pull_request" in triggers


def test_workflow_has_ontology_path_filter():
    from ster.init_ci import _read_template

    parsed = yaml.safe_load(_read_template("taxonomy-ci.yml"))
    push_paths = parsed[True]["push"]["paths"]
    assert any(".ttl" in p for p in push_paths)
    assert any(".owl" in p for p in push_paths)


def test_workflow_semanticlint_is_first_job():
    from ster.init_ci import _read_template

    parsed = yaml.safe_load(_read_template("taxonomy-ci.yml"))
    first_job = next(iter(parsed["jobs"].values()))
    steps = first_job["steps"]
    step_runs = [s.get("run", "") for s in steps]
    assert any("semanticlint" in r for r in step_runs)


def test_config_template_is_valid_yaml():
    from ster.init_ci import _read_template

    content = _read_template("onto-ci.yml")
    parsed = yaml.safe_load(content)
    assert parsed is None or isinstance(parsed, dict)


def test_config_template_has_all_quality_keys():
    from ster.init_ci import _read_template

    content = _read_template("onto-ci.yml")
    expected = [
        "min_label_coverage",
        "min_definition_coverage",
        "min_class_label_coverage",
        "min_property_label_coverage",
        "languages",
    ]
    for key in expected:
        assert key in content, f"Expected quality key {key!r} in onto-ci.yml template"


# ── needs_ci detection ────────────────────────────────────────────────────────


def test_detects_missing_workflow_in_git_project_with_ontology(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "vocab.ttl").write_text("", encoding="utf-8")
    assert needs_ci(tmp_path) is True


def test_no_detection_when_taxonomy_ci_exists(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "vocab.ttl").write_text("", encoding="utf-8")
    wf = tmp_path / ".github" / "workflows" / "taxonomy-ci.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text("name: CI", encoding="utf-8")
    assert needs_ci(tmp_path) is False


def test_no_detection_when_other_ci_workflow_exists(tmp_path: Path):
    """Projects with any existing CI workflow should not be prompted."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "vocab.ttl").write_text("", encoding="utf-8")
    wf = tmp_path / ".github" / "workflows" / "ontology-ci.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text("name: Ontology CI", encoding="utf-8")
    assert needs_ci(tmp_path) is False


def test_no_detection_outside_git_repo(tmp_path: Path):
    (tmp_path / "vocab.ttl").write_text("", encoding="utf-8")
    assert needs_ci(tmp_path) is False


def test_no_detection_when_no_ontology_files(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    assert needs_ci(tmp_path) is False


# ── prompt_if_missing ─────────────────────────────────────────────────────────


def test_prompt_if_missing_creates_files_when_confirmed(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "vocab.ttl").write_text("", encoding="utf-8")
    result = prompt_if_missing(tmp_path, ask_fn=lambda _: True)
    assert result is True
    assert (tmp_path / ".github" / "workflows" / "taxonomy-ci.yml").exists()


def test_prompt_if_missing_does_nothing_when_declined(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "vocab.ttl").write_text("", encoding="utf-8")
    result = prompt_if_missing(tmp_path, ask_fn=lambda _: False)
    assert result is False
    assert not (tmp_path / ".github" / "workflows" / "taxonomy-ci.yml").exists()


def test_prompt_if_missing_skips_when_ci_exists(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "vocab.ttl").write_text("", encoding="utf-8")
    wf = tmp_path / ".github" / "workflows" / "taxonomy-ci.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text("name: CI", encoding="utf-8")
    called = []
    prompt_if_missing(tmp_path, ask_fn=lambda _: called.append(True) or True)
    assert called == [], "Should not prompt when CI already exists"
