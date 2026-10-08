"""Materialise query-trace events as a PROV-O RDF dataset."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from rdflib import Dataset, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, XSD

from .agent import MODEL, NAME, VERSION, with_answer
from .model import Event
from .validation import validate_events

PROV = Namespace("http://www.w3.org/ns/prov#")
KAIQ = Namespace("https://www.adeo.com/ontology/kai-query#")


def materialize_events(events: Iterable[Event], answer: Mapping[str, Any] | None = None) -> Dataset:
    """Build a deterministic named-graph PROV-O dataset from *events*.

    *answer* is the record an agent reported for the run (see :mod:`ster.query_trace.answers`): it completes
    what the calls themselves said about the agent, notably the model.
    """
    items = list(events)
    errors = validate_events(items)
    if errors:
        raise ValueError("invalid trace: " + "; ".join(errors))

    first = items[0]
    graph_uri = URIRef(f"urn:kaiq:trace:{first.run_id}")
    dataset = Dataset()
    graph = dataset.graph(graph_uri)
    run_uri = _uri("run", first.run_id)
    trace_uri = _uri("trace", first.trace_id)
    graph.add((run_uri, RDF.type, PROV.Activity))
    graph.add((run_uri, RDF.type, KAIQ.QueryRun))
    graph.add((trace_uri, RDF.type, PROV.Collection))
    graph.add((trace_uri, RDF.type, KAIQ.QueryTrace))
    graph.add((run_uri, KAIQ.hasTrace, trace_uri))
    _add_agent(graph, run_uri, with_answer(first.payload.get("agent"), answer))

    steps: dict[str, URIRef] = {}
    for event in items:
        _materialize_event(graph, event, run_uri, trace_uri, steps)
    return dataset


def _materialize_event(
    graph, event: Event, run_uri: URIRef, trace_uri: URIRef, steps: dict[str, URIRef]
) -> None:
    payload = event.payload
    if event.event == "run_started":
        graph.add((run_uri, KAIQ.question, Literal(payload.get("question", ""))))
        graph.add((run_uri, PROV.startedAtTime, _timestamp(event.timestamp)))
        return
    if event.event in {"run_completed", "run_failed"}:
        graph.add((run_uri, KAIQ.status, KAIQ[payload.get("status", "failed")]))
        graph.add((run_uri, PROV.endedAtTime, _timestamp(event.timestamp)))
        return
    if event.step_id is None:
        return
    step_uri = steps.setdefault(event.step_id, _uri("step", f"{event.run_id}:{event.step_id}"))
    graph.add((trace_uri, PROV.hadMember, step_uri))
    graph.add((step_uri, RDF.type, PROV.Activity))
    graph.add((step_uri, RDF.type, KAIQ.QueryStep))
    graph.add((step_uri, KAIQ.stepId, Literal(event.step_id)))
    if payload.get("objective"):
        graph.add((step_uri, KAIQ.objective, Literal(payload["objective"])))
    if payload.get("natural_language"):
        graph.add((step_uri, KAIQ.naturalLanguageEquivalent, Literal(payload["natural_language"])))
    if event.event == "step_planned":
        graph.add((step_uri, KAIQ.status, KAIQ.Planned))
    elif event.event == "step_started":
        graph.add((step_uri, KAIQ.status, KAIQ.Running))
        graph.add((step_uri, PROV.startedAtTime, _timestamp(event.timestamp)))
    elif event.event in {"step_completed", "step_empty", "step_failed"}:
        status = payload.get("status", event.event.removeprefix("step_"))
        graph.add((step_uri, KAIQ.status, KAIQ[status]))
        graph.add((step_uri, PROV.endedAtTime, _timestamp(event.timestamp)))
        _link_artifacts(graph, step_uri, payload)


def _add_agent(graph, run_uri: URIRef, agent: Mapping[str, str] | None) -> None:
    """The agent that asked and the model behind it, as PROV software agents associated with the run.

    The agent (Claude Code, opencode, ...) acts for the person; the model it consulted acts on its behalf.
    Both are named by what they are, so the same agent in two runs is one resource.
    """
    if not agent:
        return
    harness = model = None
    if agent.get(NAME):
        harness = _uri(
            "agent", _slug(agent[NAME] + ("-" + agent[VERSION] if agent.get(VERSION) else ""))
        )
        graph.add((harness, RDF.type, PROV.SoftwareAgent))
        graph.add((harness, RDF.type, KAIQ.QueryAgent))
        graph.add((harness, RDFS.label, Literal(agent[NAME])))
        if agent.get(VERSION):
            graph.add((harness, KAIQ.version, Literal(agent[VERSION])))
        graph.add((run_uri, PROV.wasAssociatedWith, harness))
    if agent.get(MODEL):
        model = _uri("model", _slug(agent[MODEL]))
        graph.add((model, RDF.type, PROV.SoftwareAgent))
        graph.add((model, RDF.type, KAIQ.LanguageModel))
        graph.add((model, RDFS.label, Literal(agent[MODEL])))
        graph.add((run_uri, PROV.wasAssociatedWith, model))
    if harness and model:
        graph.add((model, PROV.actedOnBehalfOf, harness))


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-").lower()


def _link_artifacts(graph, step_uri: URIRef, payload: dict) -> None:
    query_id = payload.get("query_id")
    if query_id:
        query_uri = _uri("query", query_id)
        graph.add((query_uri, RDF.type, PROV.Entity))
        graph.add((query_uri, RDF.type, KAIQ.SPARQLQuery))
        if payload.get("query"):
            graph.add((query_uri, KAIQ.queryText, Literal(payload["query"])))
        graph.add((step_uri, PROV.used, query_uri))
    result_id = payload.get("result_id")
    if result_id:
        result_uri = _uri("result", result_id)
        graph.add((result_uri, RDF.type, PROV.Entity))
        graph.add((result_uri, RDF.type, KAIQ.QueryResult))
        if "row_count" in payload:
            graph.add(
                (result_uri, KAIQ.rowCount, Literal(payload["row_count"], datatype=XSD.integer))
            )
        for index, binding in enumerate(payload.get("domain_bindings", [])):
            binding_uri = _uri("binding", f"{result_id}:{index}")
            graph.add((binding_uri, RDF.type, KAIQ.Binding))
            graph.add((binding_uri, KAIQ.variable, Literal(binding["variable"])))
            resource = URIRef(binding["value"])
            graph.add((binding_uri, KAIQ.referencesResource, resource))
            if binding.get("label"):
                graph.add((binding_uri, KAIQ.label, Literal(binding["label"])))
            if binding.get("kind"):
                graph.add((binding_uri, KAIQ.entityKind, Literal(binding["kind"])))
            for rdf_type in binding.get("rdf_types", []):
                graph.add((resource, RDF.type, URIRef(rdf_type)))
            graph.add((result_uri, KAIQ.hasBinding, binding_uri))
        graph.add((step_uri, PROV.generated, result_uri))


def _uri(kind: str, value: str) -> URIRef:
    return URIRef(f"urn:kaiq:{kind}:{value}")


def _timestamp(value: str) -> Literal:
    return Literal(value, datatype=XSD.dateTime)
