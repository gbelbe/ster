"""A trace says which agent and which model made its calls, and PROV-O carries it."""

from __future__ import annotations

import pytest
from rdflib import Dataset, Literal, URIRef
from rdflib.namespace import RDF, RDFS

from ster import mcp_server as ms
from ster.model import Taxonomy
from ster.query_trace.agent import agent_of, from_meta, from_user_agent, with_answer
from ster.query_trace.answers import answer_for_run, clean_answer, record_answer
from ster.query_trace.jsonl import JsonlTraceRecorder, read_events
from ster.query_trace.materialize import KAIQ, PROV, materialize_events
from ster.query_trace.recorder import configure, set_recorder

pytestmark = pytest.mark.mutation  # noqa: V107  # pytest reads it to select the mutation tests

HARNESS, VERSION = "claude-code", "2.1.292"
HEADER = f"{HARNESS}/{VERSION} (sdk-cli)"
OTHER, OTHER_VERSION = "opencode", "1.18.34"
MODEL, MODEL_ID = "claude-haiku-4-5", "claude-haiku-4-5-20251001"
GPT, QUESTION, RUN_IDS, OVERVIEW, ANSWERED_BY = (
    "gpt-x",
    "question",
    "run_ids",
    "get_overview",
    "OpenCode",
)
META = "com.adeo/agent-"
K_NAME, K_VERSION, K_MODEL, K_AGENT = "name", "version", "model", "agent"
OUR_ANSWER = {K_MODEL: GPT, K_AGENT: ANSWERED_BY}
MODEL_URN = "urn:kaiq:model:"
AGENT_URI = URIRef(f"urn:kaiq:agent:{HARNESS}-{VERSION}")
MODEL_URI = URIRef(f"{MODEL_URN}{MODEL_ID}")


def who(name=None, version=None, model=None) -> dict:
    """An agent record with only the fields that were given."""
    given = {K_NAME: name, K_VERSION: version, K_MODEL: model}
    return {k: v for k, v in given.items() if v}


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (HEADER, who(HARNESS, VERSION)),
        (f"{OTHER}/{OTHER_VERSION}", who(OTHER, OTHER_VERSION)),
        ("Mozilla/5.0 (Macintosh)", {}),
        ("Python-urllib/3.13", {}),
        ("curl/8.7.1", {}),
        ("", {}),
        (None, {}),
        ("no-slash-here", {}),
    ],
)
def test_the_user_agent_names_the_agent_unless_it_is_a_generic_client(header, expected):
    assert from_user_agent(header) == expected


def test_meta_fields_are_kept_only_when_short_strings():
    assert from_meta(
        {META + K_NAME: " mine ", META + K_VERSION: 3, META + K_MODEL: "m" * 129, "x": "y"}
    ) == who("mine")
    assert from_meta({META + K_MODEL: MODEL}) == who(model=MODEL)


def test_meta_wins_over_the_user_agent_and_a_new_name_drops_the_old_version():
    assert agent_of(HEADER, {META + K_MODEL: MODEL}) == who(HARNESS, VERSION, MODEL)
    assert agent_of(HEADER, {META + K_NAME: OTHER}) == who(OTHER)
    assert agent_of(HEADER, {META + K_NAME: OTHER, META + K_VERSION: "1"}) == who(OTHER, "1")
    assert agent_of("curl/8", {}) is None


def test_the_answer_completes_the_model_and_a_missing_name_but_never_overrides():
    assert with_answer(None, None) is None
    assert with_answer(who(OTHER), OUR_ANSWER) == who(OTHER, model=GPT)
    assert with_answer(None, OUR_ANSWER) == who(ANSWERED_BY, model=GPT)
    assert with_answer(who(model="known"), OUR_ANSWER) == who(ANSWERED_BY, model="known")
    assert with_answer(who("a"), {K_MODEL: " ", K_AGENT: 3}) == who("a")


@pytest.fixture
def recorder(tmp_path):
    rec = JsonlTraceRecorder(tmp_path)
    set_recorder(rec)
    yield rec
    configure(False)


def _call(tool, arguments=None, meta=None, user_agent=None):
    params = {"name": tool, "arguments": arguments or {}, **({"_meta": meta} if meta else {})}
    message = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}
    return ms.handle_message(message, Taxonomy(), call=ms.CallContext(user_agent=user_agent))


def _agents_recorded(tmp_path) -> list:
    firsts = (next(iter(read_events(path))) for path in sorted(tmp_path.glob("run-*.jsonl")))
    return [first.payload.get("agent") for first in firsts]


def test_a_tool_call_records_the_agent_its_user_agent_names(recorder, tmp_path):
    _call(OVERVIEW, user_agent=HEADER)
    assert _agents_recorded(tmp_path) == [who(HARNESS, VERSION)]


def test_a_client_that_names_its_model_in_meta_has_it_recorded(recorder, tmp_path):
    _call(OVERVIEW, meta={META + K_MODEL: MODEL}, user_agent=HEADER)
    assert _agents_recorded(tmp_path) == [who(HARNESS, VERSION, MODEL)]


def test_run_sparql_records_the_agent_too(recorder, tmp_path):
    _call(
        "run_sparql",
        {"query": "SELECT * WHERE { ?s ?p ?o } LIMIT 1"},
        user_agent=f"{OTHER}/{OTHER_VERSION}",
    )
    assert who(OTHER, OTHER_VERSION) in _agents_recorded(tmp_path)


def test_a_call_from_an_unknown_client_records_no_agent(recorder, tmp_path):
    _call(OVERVIEW)
    assert _agents_recorded(tmp_path) == [None]


def _events(tmp_path, agent):
    rec = JsonlTraceRecorder(tmp_path)
    ref = rec.start_run("What is it?", agent=agent)
    rec.finish(ref)
    return list(read_events(rec.path_for(ref.run_id)))


def _objects(dataset: Dataset, subject, predicate):
    return {o for g in dataset.graphs() for o in g.objects(subject, predicate)}


def _run_uri(events):
    return URIRef(f"urn:kaiq:run:{events[0].run_id}")


def _associated(events, answer=None):
    return _objects(materialize_events(events, answer), _run_uri(events), PROV.wasAssociatedWith)


def test_prov_associates_the_run_with_the_agent_and_its_model(tmp_path):
    events = _events(tmp_path, who(HARNESS, VERSION, MODEL_ID))
    dataset = materialize_events(events)
    assert _associated(events) == {AGENT_URI, MODEL_URI}
    assert {PROV.SoftwareAgent, KAIQ.QueryAgent} <= _objects(dataset, AGENT_URI, RDF.type)
    assert Literal(HARNESS) in _objects(dataset, AGENT_URI, RDFS.label)
    assert Literal(VERSION) in _objects(dataset, AGENT_URI, KAIQ.version)
    assert {PROV.SoftwareAgent, KAIQ.LanguageModel} <= _objects(dataset, MODEL_URI, RDF.type)
    assert Literal(MODEL_ID) in _objects(dataset, MODEL_URI, RDFS.label)
    assert _objects(dataset, MODEL_URI, PROV.actedOnBehalfOf) == {AGENT_URI}


def test_a_model_alone_is_associated_without_an_agent(tmp_path):
    assert _associated(_events(tmp_path, who(model=GPT))) == {URIRef(f"{MODEL_URN}{GPT}")}


def test_a_run_with_no_agent_has_no_association(tmp_path):
    assert _associated(_events(tmp_path, None)) == set()


def test_the_same_agent_in_two_runs_is_one_resource(tmp_path):
    agent = who(OTHER, "1.1")
    both = _associated(_events(tmp_path, agent)) | _associated(_events(tmp_path, agent))
    assert both == {URIRef(f"urn:kaiq:agent:{OTHER}-1.1")}


def test_the_answer_an_agent_reported_supplies_the_model(tmp_path):
    events = _events(tmp_path, who(HARNESS, VERSION))
    assert MODEL_URI in _associated(events, {K_MODEL: MODEL_ID})


def test_an_answer_is_found_by_the_run_it_rests_on(tmp_path):
    run_id = _events(tmp_path, None)[0].run_id
    record_answer(tmp_path, "a1", {QUESTION: "q", K_MODEL: "m1", RUN_IDS: [run_id]})
    record_answer(tmp_path, "a2", {QUESTION: "q", K_MODEL: "m2", RUN_IDS: ["run-other"]})
    assert answer_for_run(tmp_path, run_id)[K_MODEL] == "m1"
    assert answer_for_run(tmp_path, "run-none") is None


def test_the_model_is_a_stored_answer_field_and_must_be_text():
    assert clean_answer("a", {QUESTION: "q", K_MODEL: "m"})[K_MODEL] == "m"
    with pytest.raises(ValueError, match="model has the wrong type"):
        clean_answer("a", {QUESTION: "q", K_MODEL: 3})


def test_the_exported_trace_names_the_agent_and_takes_the_model_from_its_answer(tmp_path, recorder):
    from ster import mcp_context as ctx

    _call(OVERVIEW, user_agent=HEADER)
    run_id = next(iter(read_events(next(tmp_path.glob("run-*.jsonl"))))).run_id
    record_answer(tmp_path, "a1", {QUESTION: "q", K_MODEL: MODEL, RUN_IDS: [run_id]})
    trig = ctx.query_trace(run_id, export=True)["trig"]
    assert str(AGENT_URI) in trig
    assert f"{MODEL_URN}{MODEL}" in trig
