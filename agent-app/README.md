# Ask the ontology

A web page to ask questions about the open ontology in plain language and watch how the answer is found: every
step the agent takes, every SPARQL query it runs against ster, the tokens it spends, and the result as a chart,
a map or a chronology. Questions can be followed up, and past ones stay browsable.

It is a view of the graph like ster's map, graph and timeline views: **graph query**. It runs your own coding
agent; no model or key is bundled.

```bash
python -m agent_app                          # http://127.0.0.1:8780, about the ster project in the current folder
python -m agent_app --project ~/work/my-project --port 8780
```

It ships inside ster's download as its own package (`agent_app`, in `agent-app/`), so there is nothing extra to install.
The page is about one ster project at a time. If ster is not running it starts one for that project (its first file,
the others read-only) with query tracing on, so every query shows its rows and duration. The project's conversations,
traces and the agent's working folder are inside the project (`.ster/`), so its history stays with it. If a ster is
already running but serves a different file, the header says so instead of quietly answering about the wrong ontology.

## How it fits together

```
browser ── page (static/: index.html, viz.js, render.js, i18n.js) ── server.py ── agent command ── ster MCP
                                                     └────────── ster trace files (every SPARQL query, rows, duration)
```

- **The server knows no agent.** It runs a command and reads what it prints (`runner.py`), or, with a model server such as Ollama and no agent product at all, runs the agent loop itself (`native.py`). A *recipe* in `recipes/`
  (or `ASK_AGENT_CMD`) says which command; see `recipes/README.md`. With no agent set up the page is read-only:
  history, replay, charts and maps still work from saved traces.
- **Queries come from ster, not from the agent.** ster traces every SPARQL query it serves, so rows and durations
  are known whichever agent ran them. What an agent reports on top (steps, tokens, cost, sessions) is shown when
  present and marked "not reported" when not. The header check measures this on the last real run.
- **Maps and chronologies use ster.** The map is ster's own page, served with the agent's query already in its box;
  places and dates are found by ster's `/api/locate` and `/api/timeline`.
- **Language follows the browser.** Text is in `locales/<lang>.json`; add a file to add a language.

| File | Role |
|---|---|
| `agent_app/server.py` | HTTP bridge: runs, history, the map page, a read-only pass-through to ster |
| `agent_app/runner.py` | Recipes, command building, the neutral event contract, the ster check |
| `agent_app/rules.py` | The rules a recipe uses to turn an agent's own output into events |
| `agent_app/native.py` | The page's own agent loop, for a model server such as Ollama |
| `agent_app/recipes/` | One JSON file per agent command, with the rules for reading its output: pure data |
| `agent_app/static/index.html` | The page |
| `agent_app/static/viz.js` | Which chart fits a result, the frise model (no DOM) |
| `agent_app/static/render.js` | Escaping, markdown, SPARQL highlighting (no DOM) |
| `agent_app/static/i18n.js`, `static/locales/` | Language loading and catalogs |

## Settings (environment)

| Variable | Meaning |
|---|---|
| `ASK_PROJECT` | The ster project the page is about (default: the folder it is run from; or `--project`) |
| `ASK_PORT` | Port of the page (default 8780) |
| `ASK_STER_HOST`, `ASK_STER_PORT` | Where ster listens, or is started (default 127.0.0.1:8765) |
| `ASK_AGENT_CMD`, `ASK_AGENT_OUTPUT`, `ASK_AGENT_LABEL`, `ASK_AGENT_STDIN` | Any command as the agent (see `recipes/README.md`) |
| `ASK_MODEL_URL` | A model server (Ollama or OpenAI-compatible) used directly, with no agent |
| `ASK_RECIPES`, `ASK_RECIPE` | Another recipes folder; the recipe to use |
| `ASK_MODEL` | The model: passed to recipes that accept one, or chosen on the model server |
| `ASK_NUM_CTX` | Context window requested from Ollama (default 16384) |

Conversations are saved in the project's `.ster/agent-app/conversations/`. In this repository that folder is git-ignored; keep it out of version control in any other project too.

## Tests

```bash
uv run pytest agent-app/tests -n auto      # Python
node --test agent-app/tests/*.test.js      # JavaScript (node's built-in runner, no dependency)
```

The bridge tests start the real server against a fake ster and fake agents, in a temp folder: they never touch
your history or a real model. `tests/fixtures/*.jsonl` are real, scrubbed recordings used to test the recipes. The
page's own script (`static/index.html`) is not unit-tested; what it needs to be correct lives in `viz.js`, `render.js`
and `i18n.js`, which are.
