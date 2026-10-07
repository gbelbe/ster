"""The answers beside the trace runs (:mod:`ster.query_trace.answers`)."""

from __future__ import annotations

import pytest

from ster.query_trace.answers import ANSWERS_DIR, clean_answer, read_answers, record_answer
from ster.query_trace.jsonl import read_events


def test_an_answer_round_trips_with_only_the_known_fields(tmp_path):
    record_answer(
        tmp_path, "t1", {"question": "q", "answer": "a", "run_ids": ["run-1"], "evil": "x"}
    )
    [row] = read_answers(tmp_path)
    assert (row["id"], row["question"], row["answer"], row["run_ids"]) == (
        "t1",
        "q",
        "a",
        ["run-1"],
    )
    assert "evil" not in row
    assert row["recorded"].endswith("Z")


def test_reporting_again_replaces_the_answer(tmp_path):
    record_answer(tmp_path, "t1", {"question": "q", "answer": "first"})
    record_answer(tmp_path, "t1", {"question": "q", "answer": "second"})
    assert [r["answer"] for r in read_answers(tmp_path)] == ["second"]


@pytest.mark.parametrize(
    "answer_id, data",
    [
        ("../escape", {"question": "q"}),
        ("", {"question": "q"}),
        ("t", {"question": "  "}),
        ("t", {}),
        ("t", {"question": "q", "answer": 3}),
        ("t", {"question": "q", "run_ids": ["../x"]}),
        ("t", {"question": "q", "cost_usd": True}),
        ("t", {"question": "q", "answer": "x" * 200_001}),
    ],
)
def test_a_bad_report_is_refused(answer_id, data):
    with pytest.raises(ValueError):
        clean_answer(answer_id, data)


def test_answers_never_look_like_a_run_journal(tmp_path):
    record_answer(tmp_path, "t1", {"question": "q"})
    assert not list(tmp_path.glob("*.jsonl"))
    assert (tmp_path / ANSWERS_DIR / "t1.json").is_file()
    assert read_events  # the journal reader is untouched by the answers folder


def test_a_damaged_file_is_skipped(tmp_path):
    record_answer(tmp_path, "t1", {"question": "q"})
    (tmp_path / ANSWERS_DIR / "bad.json").write_text("{not json")
    assert [r["id"] for r in read_answers(tmp_path)] == ["t1"]


def test_there_are_no_answers_before_any_is_reported(tmp_path):
    assert read_answers(tmp_path) == []


def test_the_graph_an_answer_was_given_on_is_kept(tmp_path):
    record_answer(tmp_path, "t1", {"question": "q", "graph_fingerprint": "00aa11bb22cc33dd"})
    assert read_answers(tmp_path)[0]["graph_fingerprint"] == "00aa11bb22cc33dd"


def test_a_path_that_leaves_the_answers_folder_is_refused(tmp_path):
    from ster.query_trace.answers import _inside

    folder = tmp_path / ANSWERS_DIR
    folder.mkdir()
    assert _inside(folder, "t1.json").parent == folder.resolve()
    for name in ("../escape.json", "/etc/passwd", "sub/../../x"):
        with pytest.raises(ValueError):
            _inside(folder, name)
