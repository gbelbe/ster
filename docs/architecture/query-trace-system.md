# Query Trace and Evaluation System

## Status

Proposed architecture. This document defines the observability, provenance, and
evaluation system for the stepped query engine. It can also instrument the
existing single-query flow before the stepped engine is introduced. The query
engine design is [stepped-query-engine.md](stepped-query-engine.md).

## Purpose

The query process needs to be inspectable at two levels:

- A complete natural-language question, from request to final answer.
- Every planning, discovery, resolution, construction, validation, and execution
  step used to produce that answer.

The trace system records each step as an event with:

- Its objective.
- Its natural-language equivalent.
- Its inputs and outputs.
- The SPARQL query, if any.
- Its status and dependencies.
- Its timing and resource metrics.
- Its errors, warnings, assumptions, and replanning decisions.

The trace also provides the data needed to compare a baseline query strategy with
the stepped strategy on a fixed graph and question set.

The main design goal is **diagnosability without coupling**. The query engine
emits domain-neutral lifecycle events to a recorder interface. The recorder maps
those events to PROV-O, JSON, logs, or another backend. Query execution must not
depend on a PROV store being available.

## Design Principles

### Use PROV-O for provenance relationships

PROV-O is used for activities, entities, usage, generation, ordering, collections,
agents, timestamps, and revisions. It gives the trace a standard semantic shape.

### Use a small application vocabulary for query semantics

PROV-O does not define SPARQL text, query objectives, natural-language
equivalents, step kinds, token counts, truncation, or result accuracy. Those
properties belong in a small `kaiq:` vocabulary rather than being forced into
PROV-O.

### Never overwrite an executed trace

Plans and steps are immutable after completion. Replanning, retries, and
corrections create new activities related to the originals. Historical evidence
must remain replayable.

### Keep large payloads out of the provenance graph

Queries and small results can be embedded. Large prompts, result sets, and model
responses should be stored as content-addressed artifacts, with hashes and
locations recorded in the provenance graph.

### Record intended and actual execution separately

The planner may describe one logical step while the executor fuses it with
another query, retries it, or replans after an empty result. The trace must show
both the logical plan and the physical execution.

## Scope and Terminology

| Term | Meaning |
|---|---|
| Query run | One attempt to answer one user question |
| Query plan | Versioned logical plan produced for the run |
| Query trace | Collection of activities and entities belonging to the run |
| Query step | One logical activity in the plan |
| Physical execution | One actual backend query or local operation |
| Query artifact | SPARQL text, prompt, result, or other stored payload |
| Benchmark case | Versioned question, graph, and expected result definition |
| Evaluation run | Activity comparing one or more query runs |

## Provenance Model

### Complete query run

Represent the complete user request as a `prov:Activity` and `kaiq:QueryRun`.

```turtle
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix kaiq: <https://www.adeo.com/ontology/kai-query#> .

<urn:kaiq:run:01J...>
    a prov:Activity, kaiq:QueryRun ;
    kaiq:question "Which people work on projects related to ontology?" ;
    kaiq:language "en" ;
    kaiq:executionMode kaiq:StepByStep ;
    kaiq:status kaiq:Completed ;
    kaiq:usesPlan <urn:kaiq:plan:01J...> ;
    kaiq:hasTrace <urn:kaiq:trace:01J...> ;
    kaiq:graphSnapshot <urn:kaiq:graph:sha256-...> ;
    kaiq:plannerVersion "0.1.0" ;
    prov:startedAtTime "2026-10-01T10:00:00Z"^^xsd:dateTime ;
    prov:endedAtTime "2026-10-01T10:00:00.250Z"^^xsd:dateTime .
```

The run is the stable root for user-facing reporting and evaluation. It should
have a globally unique ID, a graph content hash, a plan version, and an
execution configuration reference.

### Trace group

Represent the collection of logical steps as a `prov:Collection`.

```turtle
<urn:kaiq:trace:01J...>
    a prov:Collection, kaiq:QueryTrace ;
    prov:hadMember <urn:kaiq:step:01J...:resolve-topic> ;
    prov:hadMember <urn:kaiq:step:01J...:find-projects> ;
    prov:hadMember <urn:kaiq:step:01J...:find-people> ;
    kaiq:belongsToRun <urn:kaiq:run:01J...> .
```

`prov:hadMember` answers which activities belong to the complete query. It does
not imply execution order; dependencies and informing relationships express
ordering separately.

### Logical step

Each logical step is a `prov:Activity` and `kaiq:QueryStep`.

```turtle
<urn:kaiq:step:01J...:find-projects>
    a prov:Activity, kaiq:QueryStep ;
    kaiq:stepId "find-projects" ;
    kaiq:stepNumber 2 ;
    kaiq:stepKind kaiq:RelationshipTraversal ;
    kaiq:stepVersion "1.0.0" ;
    kaiq:objective "Find projects related to the resolved topic." ;
    kaiq:naturalLanguageEquivalent
        "Find projects that have Ontology as a topic of interest." ;
    kaiq:status kaiq:Completed ;
    kaiq:dependsOn <urn:kaiq:step:01J...:resolve-topic> ;
    prov:wasInformedBy <urn:kaiq:step:01J...:resolve-topic> ;
    prov:used <urn:kaiq:sparql:01J...:find-projects> ;
    prov:used <urn:kaiq:result:01J...:resolve-topic> ;
    prov:generated <urn:kaiq:result:01J...:find-projects> ;
    prov:startedAtTime "2026-10-01T10:00:00.030Z"^^xsd:dateTime ;
    prov:endedAtTime "2026-10-01T10:00:00.072Z"^^xsd:dateTime .
```

`prov:wasInformedBy` describes provenance ordering. `kaiq:dependsOn` is an
optional application-level relation useful for querying the logical plan. If
both are emitted, they must agree.

### SPARQL query artifact

The query is a separate `prov:Entity`, not merely a string property on the step.

```turtle
<urn:kaiq:sparql:01J...:find-projects>
    a prov:Entity, kaiq:SPARQLQuery ;
    kaiq:queryText "PREFIX kai: ... SELECT DISTINCT ..." ;
    kaiq:queryHash "sha256:..." ;
    kaiq:queryKind kaiq:Select ;
    kaiq:queryShape kaiq:EntityList ;
    kaiq:limit 100 ;
    kaiq:prefixes "kai,rdfs" ;
    kaiq:serialization "sparql11" .
```

The query hash is calculated over a canonical representation. The canonicalizer
must be versioned because formatting and prefix ordering can change.

### Result artifact

Each logical step produces a result entity, including failures and empty results.

```turtle
<urn:kaiq:result:01J...:find-projects>
    a prov:Entity, kaiq:QueryResult ;
    kaiq:resultShape kaiq:BindingSet ;
    kaiq:column "project_uri", "project_label" ;
    kaiq:rowCount 3 ;
    kaiq:returnedCount 3 ;
    kaiq:truncated false ;
    kaiq:contentHash "sha256:..." ;
    kaiq:serialization "json" ;
    kaiq:resultLocation "results/01J.../find-projects.json" .
```

For small result sets, bindings may be represented directly. For large result
sets, record metadata and a content-addressed location. The trace must preserve
enough information to understand the step without requiring the full payload.

### Final answer artifact

The final answer is a generated entity linked to the run.

```turtle
<urn:kaiq:answer:01J...>
    a prov:Entity, kaiq:FinalAnswer ;
    kaiq:answerText "Seven people are associated with the matching projects." ;
    kaiq:answerFormat "markdown" ;
    kaiq:supportedBy <urn:kaiq:result:01J...:find-people> .

<urn:kaiq:run:01J...>
    prov:generated <urn:kaiq:answer:01J...> .
```

## Application Vocabulary

Namespace:

```turtle
@prefix kaiq: <https://www.adeo.com/ontology/kai-query#> .
```

### Classes

```text
kaiq:QueryRun
kaiq:QueryTrace
kaiq:QueryPlan
kaiq:QueryStep
kaiq:SPARQLQuery
kaiq:QueryResult
kaiq:FinalAnswer
kaiq:GraphSnapshot
kaiq:ExecutionConfiguration
kaiq:PromptArtifact
kaiq:ModelResponse
kaiq:BenchmarkCase
kaiq:BenchmarkSuite
kaiq:EvaluationRun
kaiq:Comparison
kaiq:MetricObservation
kaiq:Replan
kaiq:Error
```

### Step kinds

```text
kaiq:ModelDiscovery
kaiq:EntityResolution
kaiq:PropertyResolution
kaiq:PathSelection
kaiq:QueryConstruction
kaiq:QueryValidation
kaiq:SubqueryExecution
kaiq:ResultNormalization
kaiq:Aggregation
kaiq:AnswerConstruction
```

### Status values

```text
kaiq:Planned
kaiq:WaitingForInput
kaiq:Generated
kaiq:Validated
kaiq:Running
kaiq:Completed
kaiq:Empty
kaiq:Failed
kaiq:TimedOut
kaiq:Blocked
kaiq:Skipped
kaiq:Cancelled
```

### Properties

| Property | Domain | Range | Meaning |
|---|---|---|---|
| `kaiq:question` | `QueryRun` | string | Original user question |
| `kaiq:objective` | `QueryStep` | string | Why the step exists |
| `kaiq:naturalLanguageEquivalent` | `QueryStep` | string | Human-readable operation |
| `kaiq:stepKind` | `QueryStep` | resource | Semantic step category |
| `kaiq:stepVersion` | `QueryStep` | string | Implementation version |
| `kaiq:stepNumber` | `QueryStep` | integer | Display order |
| `kaiq:dependsOn` | `QueryStep` | `QueryStep` | Logical dependency |
| `kaiq:status` | run/step | resource | Lifecycle state |
| `kaiq:queryText` | `SPARQLQuery` | string | Generated SPARQL |
| `kaiq:queryHash` | `SPARQLQuery` | string | Canonical content hash |
| `kaiq:queryKind` | `SPARQLQuery` | resource | SELECT or ASK, initially |
| `kaiq:queryShape` | `SPARQLQuery` | resource | Expected result shape |
| `kaiq:rowCount` | `QueryResult` | integer | Total rows found |
| `kaiq:returnedCount` | `QueryResult` | integer | Rows returned |
| `kaiq:truncated` | `QueryResult` | boolean | Whether a limit truncated output |
| `kaiq:resultLocation` | `QueryResult` | URI/string | External payload location |
| `kaiq:contentHash` | artifact | string | Hash of external content |
| `kaiq:durationMilliseconds` | activity | decimal | Wall-clock duration |
| `kaiq:queueMilliseconds` | activity | decimal | Time waiting to execute |
| `kaiq:retryCount` | activity | integer | Number of retries |
| `kaiq:replanReason` | `Replan` | string | Why the plan changed |
| `kaiq:promptTokens` | activity | integer | Input tokens |
| `kaiq:completionTokens` | activity | integer | Output tokens |
| `kaiq:toolCalls` | activity | integer | Tool calls used |
| `kaiq:confidence` | plan/step | decimal | Planner confidence |
| `kaiq:assumption` | run/step | string | Explicit assumption |
| `kaiq:errorCode` | `Error` | string | Stable failure category |
| `kaiq:errorMessage` | `Error` | string | Human-readable failure |

Use `prov:used`, `prov:generated`, `prov:wasInformedBy`, `prov:hadMember`,
`prov:wasRevisionOf`, `prov:wasAssociatedWith`, and the PROV time properties for
relationships that already have standard semantics.

## Event Contract

The query engine emits events through a narrow recorder interface. A reference
event shape is:

```json
{
  "event_id": "event-01J...",
  "run_id": "run-01J...",
  "trace_id": "trace-01J...",
  "step_id": "find-projects",
  "event_type": "step_completed",
  "occurred_at": "2026-10-01T10:00:00.072Z",
  "sequence": 7,
  "payload": {
    "status": "completed",
    "query_hash": "sha256:...",
    "row_count": 3,
    "returned_count": 3,
    "duration_ms": 42
  }
}
```

Required event types:

```text
run_started
plan_created
plan_revised
step_planned
step_waiting
query_generated
query_validated
step_started
step_completed
step_empty
step_failed
step_retried
replan_created
answer_generated
run_completed
run_failed
```

The event stream is append-only. The PROV materializer consumes events and
creates the semantic graph. A JSONL sink is useful for local debugging and
reprocessing.

### Recorder interface

```text
class QueryTraceRecorder:
    start_run(request, graph, configuration) -> RunRef
    record_plan(run, plan) -> None
    record_step_planned(run, step) -> None
    record_query(run, step, query) -> None
    record_step_result(run, step, result) -> None
    record_replan(run, revision) -> None
    finish_run(run, answer) -> None
    fail_run(run, error) -> None
```

Every method must be best effort from the query engine's perspective. Recorder
failure must be surfaced in diagnostics but must not turn a successful graph
query into a failed user query. A strict mode may be used in benchmark runs.

## Logical Versus Physical Execution

A logical step may be executed by one physical query, several retries, or a
fused query with another step.

```turtle
<urn:kaiq:physical:01J...:query-1>
    a prov:Activity, kaiq:PhysicalExecution ;
    kaiq:executesStep <urn:kaiq:step:01J...:find-projects> ;
    prov:used <urn:kaiq:sparql:01J...:find-projects> ;
    prov:generated <urn:kaiq:result:01J...:find-projects> ;
    kaiq:durationMilliseconds 42 .
```

If two logical steps are fused:

```turtle
<urn:kaiq:physical:01J...:fused-query>
    kaiq:executesStep <urn:kaiq:step:01J...:find-projects>,
                      <urn:kaiq:step:01J...:find-departments> ;
    kaiq:optimization kaiq:FusedExecution .
```

This distinction lets performance analysis compare the conceptual process with
the actual number of backend queries.

## Timing and Metrics

Record metrics at run, logical-step, physical-execution, and evaluation levels.

### Required step metrics

- Start and end timestamps.
- Queue wait and execution duration.
- Query text hash and byte size.
- Result row count and returned count.
- Truncation flag.
- Retry count.
- Error code and message when applicable.

### Optional model/tool metrics

- Prompt, completion, and total tokens.
- Model identifier and temperature/settings if relevant.
- Number of model calls.
- Number of MCP tool calls.
- Context size and cached token count.

### Optional backend metrics

- Backend query ID.
- Parse time.
- Planning time.
- Evaluation time.
- Triple or index scans when exposed by the backend.
- Memory and concurrency information.

Metrics should be numeric observations, not only text embedded in descriptions.
This makes aggregation and comparison possible.

## Storage Format

Use TriG with named graphs for persisted provenance:

```trig
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix kaiq: <https://www.adeo.com/ontology/kai-query#> .

GRAPH <urn:kaiq:trace:run-01J...> {
    <urn:kaiq:run:01J...>
        a prov:Activity, kaiq:QueryRun ;
        kaiq:hasTrace <urn:kaiq:trace:01J...> .

    <urn:kaiq:trace:01J...>
        a prov:Collection ;
        prov:hadMember <urn:kaiq:step:01J...:one> .
}
```

Recommended filesystem layout:

```text
query-traces/
  events/
    2026/10/01/run-01J.jsonl
  prov/
    2026/10/01/run-01J.prov.trig
  artifacts/
    sha256/ab/cd/<hash>
  indexes/
    runs.sqlite
```

The JSONL event stream is the append-only source for recovery and rematerializing
PROV. The TriG file is the portable semantic export. An optional index supports
fast operational queries without requiring a SPARQL store for every local run.

Keep query traces separate from the domain ontology. Do not add ephemeral query
activities to the published knowledge graph by default.

## Privacy and Retention

Natural-language questions and model prompts may contain sensitive information.
Support recording levels:

### Summary

Always safe to retain:

- IDs, timestamps, statuses, hashes, counts, durations, error categories, and
  graph/plan versions.

### Diagnostic

Record:

- SPARQL text, objectives, natural-language equivalents, assumptions, and small
  intermediate results.

### Full replay

Record:

- Full model prompts and responses, all tool arguments, all result payloads, and
  environment details.

Full replay should be opt-in, access-controlled, and subject to configurable
retention. Redaction must happen before persistence, not only when displaying a
trace.

## Replay and Reproducibility

A run is replayable only when it records:

- Graph content hash and graph version.
- Query plan and planner version.
- Step implementation versions.
- Generated SPARQL and parameter bindings.
- Prefix and model snapshot identifiers.
- Limits, timeout, and execution mode.
- Input artifacts and their content hashes.

Replay must classify differences:

```text
same_result
different_graph
different_plan
different_step_implementation
different_backend
non_deterministic_model_output
unreplayable_missing_artifact
```

Never claim a replay is equivalent when the graph or plan version differs.

## Benchmark and Evaluation Model

### Benchmark case

```turtle
<urn:kaiq:case:ontology-related-people>
    a kaiq:BenchmarkCase ;
    kaiq:caseId "ontology-related-people" ;
    kaiq:question "Which people work on projects related to ontology?" ;
    kaiq:graphSnapshot <urn:kaiq:graph:sha256-...> ;
    kaiq:goldQuery <urn:kaiq:gold-query:ontology-related-people> ;
    kaiq:goldPlan <urn:kaiq:gold-plan:ontology-related-people> ;
    kaiq:expectedResult <urn:kaiq:expected:ontology-related-people> .
```

The benchmark manifest should also be available as JSON for runners:

```json
{
  "case_id": "ontology-related-people",
  "graph": {
    "id": "kai-internal-knowledge",
    "version": "0.1.2",
    "sha256": "..."
  },
  "question": "Which people work on projects related to ontology?",
  "gold_query_file": "gold/ontology-related-people.rq",
  "gold_plan_file": "gold/ontology-related-people.plan.json",
  "expected_result_file": "expected/ontology-related-people.json",
  "explanation_requirements": [
    "resolve ontology",
    "find related projects",
    "find people associated with those projects"
  ]
}
```

### Baseline runs

Run at least these strategies against the same immutable graph snapshot:

- Existing monolithic query flow.
- Gold monolithic query.
- Refactored single-step flow.
- Gold decomposed plan.
- Generated decomposed plan.

Each execution is a `kaiq:QueryRun` associated with one benchmark case and one
strategy. This allows comparisons across versions without conflating a changed
graph with an improved planner.

### Evaluation run

```turtle
<urn:kaiq:evaluation:01J...>
    a prov:Activity, kaiq:EvaluationRun ;
    kaiq:benchmarkSuite <urn:kaiq:suite:v1> ;
    kaiq:compares <urn:kaiq:run:baseline>,
                  <urn:kaiq:run:stepped> ;
    prov:generated <urn:kaiq:comparison:accuracy>,
                   <urn:kaiq:comparison:tokens>,
                   <urn:kaiq:comparison:latency> ;
    prov:startedAtTime "2026-10-01T11:00:00Z"^^xsd:dateTime .
```

### Metrics

Correctness metrics:

- Exact entity-set match.
- Precision, recall, and F1.
- Count accuracy.
- Relationship/path accuracy.
- Correct handling of empty results.

Efficiency metrics:

- Total and per-step latency.
- Number of logical steps.
- Number of physical queries.
- Intermediate rows and final rows.
- Retries and replans.
- Query text size.
- Input, output, and total tokens.
- Tool and model calls.

Understandability metrics:

- Every step has an objective.
- Every executed query has a natural-language equivalent.
- Entity resolutions are visible.
- Assumptions and ambiguities are explicit.
- Intermediate results are available.
- A human can identify the first failing step.
- Another agent can continue from an intermediate state.

Maintainability metrics:

- Number of step implementations changed.
- Ability to replay historical runs.
- Number of plan revisions.
- Trace schema compatibility.
- Number of planner-specific special cases.

Store each metric as a typed observation:

```turtle
<urn:kaiq:comparison:tokens>
    a prov:Entity, kaiq:Comparison ;
    kaiq:metric kaiq:TotalTokens ;
    kaiq:baselineRun <urn:kaiq:run:baseline> ;
    kaiq:candidateRun <urn:kaiq:run:stepped> ;
    kaiq:baselineValue 12400 ;
    kaiq:candidateValue 8900 ;
    kaiq:delta -3500 ;
    kaiq:betterDirection kaiq:LowerIsBetter .
```

Generated SPARQL must be compared by result and constraints, not string equality.
Equivalent queries may differ in prefix names, variable names, ordering, or
join structure.

## Analysis Queries

The trace store should support questions such as:

```sparql
# Which step kinds are slowest?
SELECT ?kind (AVG(?duration) AS ?averageDuration)
WHERE {
  ?step a kaiq:QueryStep ;
        kaiq:stepKind ?kind ;
        kaiq:durationMilliseconds ?duration .
}
GROUP BY ?kind
ORDER BY DESC(?averageDuration)
```

```sparql
# Which steps most often produce empty results?
SELECT ?kind (COUNT(?step) AS ?emptySteps)
WHERE {
  ?step a kaiq:QueryStep ;
        kaiq:stepKind ?kind ;
        kaiq:status kaiq:Empty .
}
GROUP BY ?kind
ORDER BY DESC(?emptySteps)
```

```sparql
# Which query plans consume the most tokens?
SELECT ?plan (SUM(?tokens) AS ?totalTokens)
WHERE {
  ?run a kaiq:QueryRun ;
       kaiq:usesPlan ?plan .
  ?step kaiq:belongsToRun ?run ;
        kaiq:totalTokens ?tokens .
}
GROUP BY ?plan
ORDER BY DESC(?totalTokens)
```

Operational indexes may make these queries faster, but the semantic model should
remain queryable from the exported PROV graph.

## Module Boundaries

Suggested package layout:

```text
query_trace/
  model.py              # trace IDs, events, artifacts, metric types
  recorder.py           # recorder port and no-op implementation
  event_sink.py         # JSONL or stream sink
  prov_materializer.py  # events -> PROV-O/KAIQ graph
  prov_serializer.py    # TriG export and import
  artifact_store.py     # content-addressed payloads
  replay.py              # replay metadata and classification
  evaluation/
    manifest.py
    runner.py
    metrics.py
    reports.py
```

The query engine depends only on `QueryTraceRecorder` and typed event contracts.
The PROV materializer depends on those contracts, not on query-engine internals.
The benchmark runner depends on the engine coordinator and recorder, so every
benchmark execution automatically produces the same trace as production.

## Schema Evolution

Version the application vocabulary and event schema separately:

```text
PROV-O: stable W3C vocabulary
KAIQ vocabulary: semantic version, e.g. 0.1.0
Event envelope: versioned, e.g. 1
Plan schema: versioned, e.g. 0.1.0
Step implementation: independently versioned
```

Compatibility rules:

- Additive properties are backward compatible.
- Removing or changing the meaning of a property requires a new vocabulary
  version.
- Event readers must ignore unknown fields.
- Materializers must preserve unknown event payloads when round-tripping.
- A trace records the schema versions used to create it.

## Delivery Sequence

### Phase 1: Instrument the current flow

- Define event envelopes and IDs.
- Add a no-op recorder and a JSONL recorder.
- Record the existing single-query process without changing query behaviour.
- Capture graph, planner, and environment versions.

### Phase 2: Define the PROV model

- Add the KAIQ vocabulary.
- Implement materialization to TriG.
- Add named-graph trace storage.
- Add tests for run, trace, step, query, result, and dependency relationships.

### Phase 3: Add replay and artifacts

- Add content-addressed storage for full queries and results.
- Add redaction and retention settings.
- Implement replay classification.

### Phase 4: Add benchmark corpus

- Define immutable graph snapshots.
- Add gold queries, gold plans, and expected result sets.
- Run baseline and stepped strategies through the same recorder.

### Phase 5: Add reports and optimization feedback

- Produce correctness, latency, token, and explainability reports.
- Query traces to find slow, empty, retried, and frequently revised steps.
- Use evidence to improve individual step implementations.

## Acceptance Criteria

The first production-ready version should demonstrate that:

- One complete question is represented as one `kaiq:QueryRun`.
- All logical steps are grouped in one `kaiq:QueryTrace` collection.
- Every step records its objective and natural-language equivalent.
- Every SPARQL query is recorded as a query artifact with a hash.
- Every step records a result, including empty and failed outcomes.
- Dependencies and execution ordering are queryable.
- Timing, row counts, truncation, retries, and errors are recorded.
- Replanning creates a revision instead of overwriting history.
- Large payloads are externalized without losing hashes or references.
- The existing and stepped strategies can be compared on the same graph snapshot.
- A trace can be exported as PROV-O/TriG and analyzed with SPARQL.
- Recorder failure does not break normal query execution unless strict benchmark
  mode is explicitly enabled.
