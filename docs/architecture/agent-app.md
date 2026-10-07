# Agent app ("Talk to graph")

A local web page where the user's **own** agent or model answers questions about the open graph. It shows each step,
the SPARQL queries and their rows, token use, charts, ster's map, a timeline, and a replayable history.

## Layout

| Where | What |
|---|---|
| `agent-app/agent_app/` | its own Python package, shipped in the same wheel (`packages = ["ster", "agent-app/agent_app"]`) |
| `agent-app/agent_app/launcher.py` | what ster calls: `has_usable_agent()`, `find_page()`, `ensure_running()`. No web server in its imports |
| `agent-app/agent_app/server.py` | the page's bridge process (FastAPI, run as `python -m agent_app --project P`) |
| `ster/plugins/talk_to_graph/` | ster's whole view of it: option on? agent usable? where is the page? |
| `ster/cli/_agent.py` | the home-menu handler |

The package knows nothing of ster's code: it talks to ster over its MCP and HTTP endpoints, so the dependency runs one way
(ster -> `agent_app.launcher`). It is agent-agnostic: recipes (JSON + a small rules engine) describe how to drive any CLI
agent, and a built-in loop drives an Ollama or OpenAI-compatible server with a tool-capable model. State lives per project
in `<project>/.ster/agent-app/`.

## Where it appears in ster

- **Config -> Plugins -> "MCP"** (off by default). One switch with two effects: ster records the agents' queries as traces
  (`.ster/query-traces`, applied from the first request, not only after the box is toggled) and Talk to graph is offered.
  The traces are the page's history, so the two cannot be separated.
- **From the command line**: `ster serve FILE --mcp` and `ster show FILE --mcp` (or `--no-mcp`) force the plugin for that run
  only; `STER_PLUGIN_MCP=1` does the same for any command, including the bare `ster` menu. Nothing is saved, and a choice made
  in Config afterwards replaces it (`ster.plugins.override`).
- **TUI key `a`**: opens the page for the current file's folder. Bound only while the option is on (`check_action`).
- **Home menu**: with the option on *and* a usable agent, "Connect AI Agent (MCP)" becomes "Agent: talk to graph".
  Without an agent the MCP row stays: it is the way to wire a client by hand.
- Without a usable agent the page still opens, read-only (history only).

## Embed mode

`/map` and `/timeline` accept `embed=1` (`view_links.map_url(..., embed=True)`): the page without its header, query box
and details panel, for use in a frame. The agent app's frame points straight at ster's embed page.

## The MCP plugin

The former "MCP Query Trace" plugin is now **MCP** (id `mcp`). A choice saved under the old id (`mcp_query_trace`) is read
until the new id has one (`ster/plugins/state.py`, `_FORMER_IDS`). Its code stays in `ster/plugins/query_trace/`.

## One page per open graph

ster serves one graph (its file and the read-only files beside it) on one port. The page is connected to **that graph and
nothing narrower**: it compares no file or context list, and it never refuses a question.

- **A page is a folder and a ster port.** `launcher.find_page` / `ensure_running` reuse a page for the same folder and
  ster port; another port or folder starts another page on the next free port (8780-8789). The folder is where the
  history, the agent's working directory and the traces live.
- **ster stamps its graph.** `get_overview` returns `graph: {triples, fingerprint}`: a hash of the store's triples that
  ignores order and blank-node labels and changes with any edit.
- **The page watches ster** (`/api/status`, polled every 4 s, cached 3 s): `down` (pill red; ster restarts from
  `project.json` on the next question) or `up`, with the graph's title, triple count and the first characters of the
  stamp, shown in the pill's tooltip.
- **Each answer records the stamp it was given on** (`graph` on the turn, `graph_fingerprint` in ster's answer record).
  When ster's stamp differs from the conversation's last answer, a notice says the graph changed since the conversation
  began and offers a new one. Nothing is blocked: a hash cannot tell an edit from another graph, and both mean earlier
  answers may no longer hold.
- **To work on two graphs at once**, run two ster instances on different ports. Each `a` opens the page for its own port.

## What the traces hold, and what the page adds to them

A trace run records one tool call: its arguments, the query, its rows, durations and token use. It cannot see the agent's
final text or the id the agent resumes a conversation with. After each turn the page reports both to ster
(`POST /api/query_trace/answers/{turn}`, token-authenticated, refused with 409 while tracing is off). ster keeps one small
JSON file per answer in `.ster/query-traces/answers/` (never mistaken for a run journal) with `question`, `answer`,
`status`, `agent`, `conversation_id`, `resume_session_id`, `run_ids` (the join to the runs it rests on), tokens, cost and
timing. `GET /api/query_trace/answers` lists them, and each `AgentSession` of the trace timeline carries the answers whose
runs it contains. Reporting is best effort: if ster is down or not tracing, the turn is unaffected.

## History

The page keeps its own copy of each conversation it ran (`.ster/agent-app/conversations/`), which is what a live run and
a follow-up use. The history list also shows **what only ster's traces remember** (`agent_app/history.py`), marked
read-only: answers the page reported whose local copy is missing (another machine, a deleted file), and sessions an agent
ran without the page, grouped by the `com.adeo/agent-session-id` their calls carried. Each such conversation is rebuilt as a
step and a tool call per recorded run, with ster's own SPARQL and rows, then the answer, tokens and cost when an answer was
reported. Calls that carried no session id belong to nothing and are left out. A conversation kept only by ster cannot be
deleted from the page, and the composer is disabled on it (start a new conversation to ask).

## The conversation page

Each question is one card: the question as its header, then **Steps (n)** (one folded line per model call: what it did, its
new tokens, its time), then the answer, its charts and its footer. Unfolding a step shows its token split, what the model
said and each call with its SPARQL and ster's rows. Which steps are open is kept in memory (`S.open`), not in the markup, so a
streaming turn is not rebuilt, and its embedded map not reloaded, when someone unfolds a step. The right panel keeps the
summary: tokens, cost and the per-step token chart; clicking a bar opens and scrolls to that step.

Each step's title is **the tool, then what the call looks for in plain words**: the question ster recorded for it
(`agent_question`), else the call's own `question` argument. ster asks agents to send that question in MCP `_meta`
(`com.adeo/agent-question`), but `_meta` is request metadata set by the client program, not an argument the model can
fill, and most clients (Claude Code among them) do not expose it. So `run_sparql` also declares an optional `question`
string in its `inputSchema`, which any model can fill; `_meta` wins when both are given, and the trace records whichever
was used. The page's prompt asks agents to give it on every call. Without a question the title falls back to the query's
text. The closing step, which only writes the answer, is not listed: the answer is right below.
