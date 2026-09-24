"""What .ster/project.json remembers between launches.

Two answers a user should give once, not every time ster starts: whether to
look in subfolders, and which files to load read-only beside a given file.
"""

from __future__ import annotations

import json

from ster.project import Project


def _project(tmp_path) -> Project:
    return Project(root=tmp_path)


def _reload(tmp_path) -> Project:
    loaded = Project.load(tmp_path)
    assert loaded is not None
    return loaded


def test_the_subfolder_answer_is_unset_until_given(tmp_path) -> None:
    assert _project(tmp_path).include_subfolders is None


def test_the_subfolder_answer_survives_a_reload(tmp_path) -> None:
    project = _project(tmp_path)
    project.include_subfolders = True
    project.save()
    assert _reload(tmp_path).include_subfolders is True


def test_the_context_chosen_for_a_file_survives_a_reload(tmp_path) -> None:
    editable, context = tmp_path / "gear.ttl", tmp_path / "vocab" / "labels.ttl"
    context.parent.mkdir()
    for path in (editable, context):
        path.write_text("", encoding="utf-8")
    project = _project(tmp_path)
    project.remember_context(editable, [context])
    project.save()
    assert _reload(tmp_path).remembered_context(editable) == [context]


def test_context_is_stored_relative_to_the_project(tmp_path) -> None:
    editable, context = tmp_path / "gear.ttl", tmp_path / "labels.ttl"
    project = _project(tmp_path)
    project.remember_context(editable, [context])
    project.save()
    stored = json.loads((tmp_path / ".ster" / "project.json").read_text())
    assert stored["context"] == {"gear.ttl": ["labels.ttl"]}


def test_a_remembered_file_that_was_deleted_is_dropped(tmp_path) -> None:
    editable, kept, gone = (tmp_path / name for name in ("gear.ttl", "kept.ttl", "gone.ttl"))
    for path in (editable, kept):
        path.write_text("", encoding="utf-8")
    project = _project(tmp_path)
    project.remember_context(editable, [kept, gone])
    assert project.remembered_context(editable) == [kept]


def test_each_editable_file_keeps_its_own_context(tmp_path) -> None:
    a, b, c = (tmp_path / name for name in ("a.ttl", "b.ttl", "c.ttl"))
    for path in (a, b, c):
        path.write_text("", encoding="utf-8")
    project = _project(tmp_path)
    project.remember_context(a, [b])
    project.remember_context(b, [c])
    assert (project.remembered_context(a), project.remembered_context(b)) == ([b], [c])


def test_an_older_project_file_without_these_keys_still_loads(tmp_path) -> None:
    (tmp_path / ".ster").mkdir()
    (tmp_path / ".ster" / "project.json").write_text('{"files": [], "lang": "fr"}')
    loaded = _reload(tmp_path)
    assert (loaded.lang, loaded.include_subfolders, loaded.context) == ("fr", None, {})
