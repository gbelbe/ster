"""Portable query-trace journal and PROV materialization tests."""

from __future__ import annotations

import json
import runpy
import sys

import pytest

from ster.query_trace.jsonl import JsonlTraceRecorder, read_events
from ster.query_trace.materialize import materialize_events
from ster.query_trace.model import Event
from ster.query_trace.recorder import (
    NoOpTraceRecorder,
    configure,
    configure_from_environment,
    get_recorder,
)
from ster.query_trace.subgraph import trace_subgraph
from ster.query_trace.validation import validate_events


def test_jsonl_recorder_writes_one_journal_with_ordered_events(tmp_path):
    recorder = JsonlTraceRecorder(tmp_path)
    ref = recorder.start_run("What is Ontology?", graph_id="kai")
    recorder.record(
        Event(
            event="step_completed",
            run_id=ref.run_id,
            trace_id=ref.trace_id,
            sequence=2,
            step_id="step-1",
            payload={"objective": "Resolve the entity", "query": "SELECT * WHERE {}"},
        )
    )
    recorder.finish(ref)

    path = next(tmp_path.glob("*.jsonl"))
    events = list(read_events(path))
    assert [event.event for event in events] == [
        "run_started",
        "step_completed",
        "run_completed",
    ]
    assert [event.sequence for event in events] == [1, 2, 3]
    assert json.loads(path.read_text().splitlines()[-1])["payload"]["status"] == "completed"
    assert validate_events(events) == []


def test_trace_validation_rejects_non_contiguous_events():
    events = [
        Event("run_started", "run", "trace", 1),
        Event("run_completed", "run", "trace", 3),
    ]
    errors = validate_events(events)
    assert "event sequences must be contiguous starting at 1" in errors


def test_trace_validation_reports_all_structural_errors():
    events = [
        Event("step_completed", "run-a", "trace-a", 2, event_id="duplicate"),
        Event("step_completed", "run-b", "trace-b", 2, event_id="duplicate"),
    ]

    errors = validate_events(events)

    assert "trace contains multiple run IDs" in errors
    assert "trace contains multiple trace IDs" in errors
    assert "trace must start with run_started" in errors
    assert "trace must end with run_completed or run_failed" in errors
    assert "trace must contain exactly one run_started event" in errors
    assert "trace must contain exactly one terminal event" in errors
    assert "event IDs must be unique" in errors


def test_trace_validation_rejects_an_empty_journal():
    assert validate_events([]) == ["trace contains no events"]


def test_jsonl_reader_skips_blank_lines_and_reports_invalid_lines(tmp_path):
    path = tmp_path / "trace.jsonl"
    path.write_text("\nnot json\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid event at line 2"):
        list(read_events(path))


def test_trace_materializes_steps_queries_and_results_as_prov_dataset(tmp_path):
    recorder = JsonlTraceRecorder(tmp_path)
    ref = recorder.start_run("What is Ontology?", graph_id="kai")
    recorder.record(
        Event(
            "step_planned",
            ref.run_id,
            ref.trace_id,
            2,
            step_id="step-1",
            payload={
                "objective": "Resolve the entity",
                "natural_language": "Find the entity labelled Ontology.",
            },
        )
    )
    recorder.record(
        Event(
            "step_completed",
            ref.run_id,
            ref.trace_id,
            3,
            step_id="step-1",
            payload={
                "status": "completed",
                "query_id": "query-1",
                "query": "SELECT * WHERE {}",
                "result_id": "result-1",
                "row_count": 1,
            },
        )
    )
    recorder.finish(ref)

    dataset = materialize_events(read_events(next(tmp_path.glob("*.jsonl"))))
    graph = dataset.graph(f"urn:kaiq:trace:{ref.run_id}")
    assert (None, None, None) in graph
    assert any(str(value) == "Resolve the entity" for _, _, value in graph)
    assert any(str(value) == "SELECT * WHERE {}" for _, _, value in graph)
    assert any(str(value) == "1" for _, _, value in graph)


def test_trace_configuration_can_enable_and_disable_recording(tmp_path):
    configure(True, str(tmp_path))
    assert get_recorder().enabled() is True
    configure(False)
    assert isinstance(get_recorder(), NoOpTraceRecorder)


def test_trace_configuration_reads_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("STER_QUERY_TRACE", "true")
    monkeypatch.setenv("STER_QUERY_TRACE_DIR", str(tmp_path))
    configure_from_environment()
    assert get_recorder().enabled() is True
    monkeypatch.setenv("STER_QUERY_TRACE", "off")
    configure_from_environment()
    assert isinstance(get_recorder(), NoOpTraceRecorder)


def test_trace_subgraph_connects_binding_to_bounded_domain_graph(tmp_path):
    from rdflib import Graph, URIRef

    recorder = JsonlTraceRecorder(tmp_path)
    ref = recorder.start_run("Find ontology")
    recorder.record(
        Event(
            "step_completed",
            ref.run_id,
            ref.trace_id,
            2,
            step_id="step-1",
            payload={
                "status": "completed",
                "result_id": "result-1",
                "row_count": 1,
                "domain_bindings": [
                    {
                        "variable": "entity",
                        "value": "https://example.org/Ontology",
                        "label": "Ontology",
                    }
                ],
            },
        )
    )
    recorder.finish(ref)
    dataset = materialize_events(read_events(next(tmp_path.glob("*.jsonl"))))
    domain = Graph()
    ontology = URIRef("https://example.org/Ontology")
    related = URIRef("https://example.org/Related")
    predicate = URIRef("https://example.org/relatedTo")
    domain.add((ontology, predicate, related))
    output = trace_subgraph(dataset, ref.run_id, domain, domain_hops=1)
    assert (ontology, predicate, related) in output


def test_trace_cli_inspects_a_recorded_trace(tmp_path, monkeypatch, capsys):
    recorder = JsonlTraceRecorder(tmp_path)
    ref = recorder.start_run("Inspect this trace")
    recorder.finish(ref)
    path = next(tmp_path.glob("*.jsonl"))
    monkeypatch.setattr(sys, "argv", ["ster-trace", "inspect", str(path)])

    runpy.run_module("ster.query_trace.cli", run_name="__main__")

    output = capsys.readouterr().out
    assert f"Run: {ref.run_id}" in output
    assert "Question: Inspect this trace" in output


def test_trace_cli_validates_a_recorded_trace(tmp_path, monkeypatch, capsys):
    recorder = JsonlTraceRecorder(tmp_path)
    ref = recorder.start_run("Validate this trace")
    recorder.finish(ref)
    path = next(tmp_path.glob("*.jsonl"))
    monkeypatch.setattr(sys, "argv", ["ster-trace", "validate", str(path)])

    runpy.run_module("ster.query_trace.cli", run_name="__main__")

    assert "valid trace: 2 events" in capsys.readouterr().out
