# Agent recipes

The bridge does not know any agent. It runs a command and reads what it prints; ster's own trace files supply
every SPARQL query, its rows and its duration, whichever agent ran it.

## The simplest agent: any command that prints its answer

```bash
ASK_AGENT_CMD='myagent --prompt {prompt}' python -m agent_app        # plain text output
```

That is enough for: asking, the answer, history, and the SPARQL / charts / map / chronology for every query the agent
ran against ster (read from ster's traces). The agent must be pointed at ster (`{ster_url}`, `{ster_token}`,
`{ster_mcp_json}` are available as placeholders when the command can take them; otherwise configure it in the agent).
Not available without more: live steps, tokens, cost, follow-ups.

## A recipe: a JSON file in this folder

| Field | Meaning |
|---|---|
| `label`, `binary` | Name shown, and the program that must be on the PATH for the recipe to count as set up |
| `command` | argv template. Placeholders: `{prompt}` `{system_prompt}` `{session}` `{model}` `{ster_url}` `{ster_token}` `{ster_mcp_json}` `{recipes}` |
| `resume` / `model_args` | Appended when a session id exists / a model is chosen |
| `stdin` | `prompt` (default) or `none` |
| `output` | `events` (neutral protocol below) or `text` |
| `stream` | Rules that turn the agent's own lines into neutral events (below). No code needed |
| `translate` | Escape hatch: a command that reads the agent's stream on stdin and prints neutral events, for a format the rules cannot express |
| `env` | Extra environment variables for the agent, with the same placeholders as `command` |
| `verified` | `true` only if you ran the recipe against the real agent |

If no recipe's program is on the PATH and `ASK_AGENT_CMD` is unset, the page runs read-only: history and replay still work.

## Neutral protocol (what `events` output, or a translator, prints: one JSON object per line)

```
{"e":"session","session_id":"…"}                       enables follow-up questions
{"e":"step_start","step":"s1"}                          one model call
{"e":"usage","step":"s1","input":n,"output":n,"cache_read":n,"cache_write":n}   any subset
{"e":"text_delta","step":"s1","text":"…"}
{"e":"tool_call","step":"s1","id":"c1","name":"run_sparql","input":{…}}
{"e":"tool_result","id":"c1","text":"<ster's reply, unmodified>","is_error":false}
{"e":"done","status":"completed","answer":"…","cost_usd":n,"usage":{…},"session_id":"…"}
```

Send ster's reply unmodified in `tool_result`: it carries the trace id that links the query to its rows.
What an agent leaves out is simply shown as "not reported"; the header check measures what each run delivered.

## Rules: no code per agent

An agent that prints its own JSON lines needs no script. Its recipe lists rules; each says "when a line looks like this,
print events built from these fields":

```json
"stream": [
  {"when": {"type": "system", "subtype": "init"}, "emit": {"e": "session", "session_id": "$.session_id"}},
  {"when": {"type": "result"},
   "emit": {"e": "done", "answer": "$.result", "status": {"if": "$.is_error", "then": "error", "else": "completed"}}}
]
```

`when` matches paths in the line; `$.a.b[0]` reads a field (an absent field is left out, never null); `{"state": ...}`
remembers a value across lines (`set`); `begin` / `append` / `flush` assemble pieces such as tool arguments that
arrive in fragments; `each` repeats an `emit` for every item of a list; `{"join": ...}`, `{"any": ...}` and `{"if": ...}`
combine values. The full list is at the top of `rules.py`, and `claude-code.json` is a complete worked example.
Text the agent prints in colour is cleaned of terminal codes automatically.

## Recipes shipped here

| Recipe | Checked | Reports | Notes |
|---|---|---|---|
| `claude-code.json` | run for real | steps, tokens per step, cost, sessions | Claude's own tools are switched off; only ster is allowed |
| `ollama.json` | run for real, with a local 3B model | steps, tokens per step, follow-ups | Not an agent: a model server. The page runs the loop itself (see below). Only models that can call tools are used |
| `opencode.json` | run for real, with a local model | steps, tokens per step, sessions | No cost is reported. OpenCode uses the model from its own configuration, or `ASK_MODEL=provider/model`. Its built-in tools are denied; only ster is allowed. It ends without a final event, so the answer is the text of its last step |

Both were checked by recording a real run (kept, scrubbed, in `tests/fixtures/`) and by running the whole page against the
agent. To add another agent, copy the closest recipe, run the agent once to see its JSON lines, and write the rules.

## No agent at all: a model server

A recipe with `"type": "model"` has an `endpoint` instead of a command. The page itself runs the loop: it shows the model
ster's read-only tools, runs the ones the model asks for, and repeats until there is an answer. It follows ster's own
usage instructions (trimmed of what only desktop agents need), fills in the request metadata ster asks for, keeps the
conversation for follow-ups, and does not run an identical call twice in one question.

```bash
ASK_MODEL_URL=http://localhost:11434/v1 python -m agent_app     # no recipe needed
ASK_MODEL=qwen2.5:7b ...                                             # which model; default: the first able to call tools
```

- **Ollama** is detected (its own API is used, so the context window can be set: `ASK_NUM_CTX`, default 16384) and only models
  that report the `tools` capability are used. Others are listed in the check but never chosen.
- **Any OpenAI-compatible server** (LM Studio, llama.cpp, vLLM, ...) works through `/chat/completions`. Such a server does not say
  which models can call tools, so the one you name is simply tried and a refusal is reported as it comes.
- Small models are slow and often wrong at SPARQL; a larger tool-capable model is the practical choice.

## Examples that are not loaded

`recipes/examples/` holds recipes that have **not** been run, so they are not active. Copy one up into `recipes/` after
trying it. They are starting points, written from the agent's documentation:

| Example | What it assumes | What is unchecked |
|---|---|---|
| `codex.json` | `codex exec` prints its final answer on stdout; ster is given per run with `-c mcp_servers.ster.url=...` and a token read from an environment variable, so your own Codex config is untouched | every flag (run `codex exec --help`), and the output: it is read as plain text, so you get the answer and ster's queries but no steps or tokens until you write rules from `codex exec --json` |

**Gemini CLI** has no recipe: it reads its MCP servers from settings files, and no way to give it a server for one run
was found, so a recipe would have to edit your own configuration. That is not done.
