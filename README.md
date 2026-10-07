# ster

**Software**
[![CI](https://github.com/gbelbe/ster/actions/workflows/ci.yml/badge.svg)](https://github.com/gbelbe/ster/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/gbelbe/ster/branch/main/graph/badge.svg)](https://codecov.io/gh/gbelbe/ster/branch/main)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![PyPI](https://img.shields.io/pypi/v/ster)](https://pypi.org/project/ster/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Dependencies**
[![rdflib](https://img.shields.io/pypi/v/rdflib?label=rdflib&color=orange)](https://github.com/RDFLib/rdflib)
[![pyLODE](https://img.shields.io/pypi/v/pylode?label=pyLODE&color=blue)](https://github.com/RDFLib/pyLODE)
[![semanticlint](https://img.shields.io/pypi/v/semanticlint?label=semanticlint&color=e56b6f)](https://pypi.org/project/semanticlint/)
[![Cytoscape.js](https://img.shields.io/github/v/tag/cytoscape/cytoscape.js?label=Cytoscape.js&color=00a6a6)](https://github.com/cytoscape/cytoscape.js)
[![Textual](https://img.shields.io/pypi/v/textual?label=Textual&color=5a4fcf)](https://github.com/textualize/textual)

```
   _____ ______ ______ ____
  / ___//_  __// ____// __ \
  \__ \  / /  / __/  / /_/ /
 ___/ / / /  / /___ / _, _/
/____/ /_/  /_____//_/ |_|

  [ Breton: "Meaning" or "Sense" ]
  [  Semantic Knowledge Editor  ]
```

**ster** is a terminal editor for semantic knowledge bases. Build and explore
[SKOS](https://www.w3.org/TR/skos-reference/) taxonomies and
[OWL](https://www.w3.org/TR/owl2-overview/) ontologies together in one
full-screen TUI — then visualise them as interactive graphs, run SPARQL, and
publish HTML documentation, all from your terminal. No database required.

> *ster* is the Breton word for *meaning*, with homonyms for *river* and *star* —
> keep the flow, and follow your star.

---

## The TUI

The heart of ster is a [Textual](https://github.com/textualize/textual) terminal
app that shows your **SKOS taxonomy and OWL ontology in a single tree**:

- **One unified tree** — concept schemes, concepts, classes, named individuals,
  and properties side by side. Create, rename, delete, and edit any entity
  inline; every field is editable in a detail panel.
- **Puns (class ⇔ concept)** — an entity can be both an OWL class and a SKOS
  concept. **Promote** a concept to a class or **demote** it back with one action.
- **Tag individuals with concepts** — link named individuals to SKOS concepts
  (`dcterms:subject`), one at a time or in bulk from a checklist.
- **Live quality & coverage** — a [semanticlint](https://pypi.org/project/semanticlint/)
  pass colour-codes each tree node by its worst issue (🔴 error · 🟠 warning);
  hover for a per-entity issue count, and open the node to see the full list and
  its label/comment/property-fill coverage.
- **Markdown notes** — attach rich notes to any entity with a full-screen editor
  and a live rendered preview; markdown links are URL-checked when you open or edit them.
- **Ontology overview** — editable title/description; opening a pure-OWL file
  jumps straight to the overview.
- **Bundled demo** — a mixed SKOS + OWL sandbox you can load from the file list
  to try everything out (it resets on each load).

## Beyond the tree

Every capability below is reachable from the home menu, acting on the file you selected:

| Menu action | What it does |
|---|---|
| **TTL Viewer-Editor** | The unified SKOS + OWL tree editor described above |
| **SPARQL Query** | In-TUI query editor with autocomplete and a cache-warmed engine (no cold-start delay); export results to CSV |
| **Graph Viewer** | Opens an interactive [Cytoscape.js](https://js.cytoscape.org) VOWL-style graph in the browser — classes as circles, property edges, per-class individual toggle, drag / zoom / detail panel |
| **HTML Data Catalog** | Generates browsable [pyLODE](https://github.com/RDFLib/pyLODE) documentation, one page per language |
| **Linked Data Publish & Version** | Semver-tagged releases served over a local Linked-Data server |

### In-browser views

Three views open in the browser from the TUI, on the entity you have selected or
on the whole file. Each one refuses to open on a file that has nothing to show,
rather than presenting an empty canvas that reads as a bug:

| Key | View | What it draws |
|---|---|---|
| `g` | **Graph** | The VOWL-style class/property graph (Cytoscape) |
| `m` | **Map** | Everything the file locates — points and shapes alike, read from GeoSPARQL literals by datatype, with the tile layers the file itself declares |
| `t` | **Timeline** | Everything the file dates, as a zoomable frieze (vis-timeline): one lane per class, thumbnails and notes from the metadata, and spans only where the file declares the pair of predicates that forms one |

From the SPARQL screen the same views open on the current result — `ctrl+g` for
the map, `ctrl+t` for the timeline — and the status line says how many rows each
one can place before you try.

## Ask your AI agent about your ontology

ster exposes a **read-only [MCP](https://modelcontextprotocol.io) endpoint**, so
whichever AI agent you already use can answer questions about the ontology you
are editing. ster provides the
context; you bring your own agent, your own model and your own keys. No AI
provider is bundled, and nothing is sent anywhere by ster itself.

The endpoint comes up on its own when you open a file in the TUI (or run
`ster serve`). Point an agent at it once:

```bash
claude mcp add --transport http ster http://127.0.0.1:8765/mcp \
  --header "Authorization: Bearer $(cat ~/.config/ster/api_token)"
```

Any MCP-capable client works the same way — the endpoint is plain JSON-RPC over
HTTP, guarded by the same bearer token as the rest of the API.

| Tool | Answers |
|---|---|
| `get_overview` | "What is in this file?" — counts, schemes, languages |
| `get_entity` | Full detail for one URI (SKOS concepts *and* OWL classes) |
| `search_entities` | Resolve a name you mention into a URI |
| `get_vocabulary` | "What predicates does this file actually use?" — prefixes, types and language tags, so a query is built on the real vocabulary instead of a guess |
| `run_sparql` | Anything else — `SELECT` / `ASK` only |

**Grounded queries, any agent.** Ontologies differ in vocabulary: labels sit on
`skos:prefLabel` or `rdfs:label`, hierarchy on `skos:broader` or
`rdfs:subClassOf`, and the labels may be tagged `@fr` rather than `@en`. An agent
that assumes wrong writes a query that parses cleanly and returns nothing. ster
answers those questions from the file itself via `get_vocabulary`, and tells
every client to ask them first through the MCP `instructions` field — so this
works with any MCP-capable agent, not only the one you happen to use.

**Read-only by design.** There are no write tools, SPARQL update forms are
refused, and the endpoint rejects browser requests from foreign origins (the
DNS-rebinding defence the MCP spec requires). An agent can read your ontology
and answer questions about it; it cannot change it.

---

## Installation

ster is a CLI app, so the cleanest install is as an isolated
[uv](https://docs.astral.sh/uv/) tool — no virtualenv to manage, `ster` goes
straight on your PATH:

```bash
uv tool install ster        # install
uv tool upgrade ster        # update to the latest release
uvx ster                    # or run once, without installing
```

Prefer pip? That works too:

```bash
pip install ster            # install / upgrade with: pip install -U ster
```

That's everything — TUI editing, graph viewer, SPARQL, HTML export, and the
publish server, no extras required.

## Quick start

```bash
ster
```

The home screen lists the ontology and taxonomy files in the current directory
(plus a **Load demo** entry). Pick a file, then choose an action:

```
  Select a file:
    ☑  my-ontology.ttl
    🎒 Load demo ontology / taxonomy

  ▶  🖥  TTL Viewer-Editor
     🔍 SPARQL Query
     📦 Linked Data Publish & Version
     🌐 HTML Data Catalog
     ◈  Load Graph Viewer
     ✕  Quit
```

Arrow keys navigate; **Enter** confirms. Inside the tree editor, press **?** for
the full keymap — the essentials are `+` add, `d` delete, `e` edit,
`Enter` expand/open, `Esc` back.

---

## Supported formats

| Extension | Format |
|---|---|
| `.ttl` | Turtle (recommended) |
| `.nt` | N-Triples (fastest for large files) |
| `.rdf` / `.xml` | RDF/XML |
| `.jsonld` / `.json` | JSON-LD |
| `.owl` | OWL/XML |

### Large Files & Performance
For large ontologies or taxonomies (over 100k triples), `ster` provides several performance boosts out of the box:
- **Fast Rust Parsing**: `ster` uses the high-performance Oxigraph engine automatically for near-instant RDF parsing.
- **N-Triples Acceleration**: Reading `.nt` files is significantly faster than Turtle for massive datasets. Use `ster convert large.ttl large.nt` to switch.
- **Binary Caching**: After the first successful parse, a secure binary cache is created. Subsequent loads are near-instant (typically under 2s for 150MB+ files).

## Key dependencies

| Package | Role |
|---|---|
| [rdflib](https://github.com/RDFLib/rdflib) | RDF parsing / serialisation and the SPARQL engine |
| [Textual](https://github.com/textualize/textual) | The terminal UI framework |
| [Cytoscape.js](https://github.com/cytoscape/cytoscape.js) | Browser graph rendering (VOWL viewer) |
| [pyLODE](https://github.com/RDFLib/pyLODE) | HTML documentation export |

---

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow.

```bash
git clone https://github.com/gbelbe/ster.git
cd ster
uv sync --extra dev
bash scripts/install-hooks.sh   # git pre-push hook (once per clone)
bash scripts/ci.sh              # full local gate: lint · types · security · tests · coverage
```

The local gate mirrors GitHub Actions (ruff · mypy · bandit + pip-audit ·
pytest on Python 3.12 / 3.13), and a pre-push hook blocks any push
without a passing run in the last 24 hours. Coverage is reported to
[Codecov](https://codecov.io/gh/gbelbe/ster).

Release notes live in the [GitHub releases](https://github.com/gbelbe/ster/releases).

## Optional plugins

- `ster[semanticlint]` enables live ontology-quality checks.
- `ster[rdfdiff]` enables Semantic History, which reads a tracked RDF file's Git
  history as additions, modifications, renames, deprecations, and removals.

## License

[MIT](LICENSE)
