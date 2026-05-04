# ster

[![CI](https://github.com/gbelbe/ster/actions/workflows/ci.yml/badge.svg)](https://github.com/gbelbe/ster/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/gbelbe/ster/graph/badge.svg)](https://codecov.io/gh/gbelbe/ster)
[![PyPI](https://img.shields.io/pypi/v/ster)](https://pypi.org/project/ster/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

[![rdflib](https://img.shields.io/pypi/v/rdflib?label=rdflib&color=orange)](https://pypi.org/project/rdflib/)
[![typer](https://img.shields.io/pypi/v/typer?label=typer&color=brightgreen)](https://pypi.org/project/typer/)
[![rich](https://img.shields.io/pypi/v/rich?label=rich&color=purple)](https://pypi.org/project/rich/)
[![pylode](https://img.shields.io/pypi/v/pylode?label=pylode+%5Boptional%5D&color=blue)](https://pypi.org/project/pylode/)

```
   _____ ______ ______ ____
  / ___//_  __// ____// __ \
  \__ \  / /  / __/  / /_/ /
 ___/ / / /  / /___ / _, _/
/____/ /_/  /_____//_/ |_|

  [ Breton: "Meaning" or "Sense" ]
  [  Semantic Knowledge Editor  ]
  v0.3.3
```

**ster** is a terminal tool for building and exploring semantic knowledge bases.
Edit [SKOS](https://www.w3.org/TR/skos-reference/) taxonomies and [OWL](https://www.w3.org/TR/owl2-overview/) ontologies in a full-screen TUI, explore them as interactive D3 force graphs, and export HTML documentation — all from your terminal, no database required.

> *ster* is the Breton word for *meaning*, with homonyms for *river* and *star*.
> Let it guide your semantic voyage, keeping the flow and always following your star.

---

## What's inside

| Layer | What ster does |
|---|---|
| **Edit** | Full-screen TUI for SKOS concepts and OWL classes / individuals / properties |
| **Visualise** | Interactive D3 v7 force graph — colour-coded clusters, drag, zoom, filter, detail panel |
| **AI assist** | LLM-powered concept suggestions (online or local via Ollama) |
| **Git** | Stage, commit, push without leaving the terminal |
| **Export** | pyLODE HTML documentation; SPARQL query runner |

---

## Features

### Interactive TUI — SKOS and OWL in one view

- Full-screen tree browser for SKOS concept schemes and OWL class hierarchies
- Inline concept creation, renaming, deletion, and label editing
- Detail panel: view and edit all SKOS fields (labels, definitions, scope notes, related links…)
- OWL layer: browse classes, named individuals, object/datatype properties, axioms
- Visual `⇔` indicator for concepts with cross-scheme mapping links
- Fold / unfold subtrees; hidden-concept count shown
- Scheme dashboard: completion rates, quality issues, concept counts at a glance

### D3 force graph visualisation

Open any ontology or taxonomy as an interactive force graph in the browser:

- Colour-coded node clusters per root class or top concept
- Node types rendered distinctly: OWL classes (rectangles), individuals (ellipses), SKOS concepts (small ellipses), schemes (rounded rects)
- Representative images embedded inside nodes when `schema:image` is set
- Drag, zoom, and pin nodes; hover tooltips; highlight neighbourhoods on click
- Lane-based hierarchical layout option for SKOS concept trees

### AI-assisted concept creation

When adding a concept (`+` key), choose between entering a name manually or letting AI suggest up to 20 ordered concept names:

- **AI Auto Suggest** — the AI acts as a professional taxonomist who knows your domain.
  It proposes names ranked by relevance, you pick one (or ask for more), and the form is pre-filled.
- Before generating, ster shows you the exact prompt so you can review and adjust it.
- Supports any LLM via the [`llm`](https://llm.datasette.io/) library — including local models via [Ollama](https://ollama.com/).
- Pull Ollama models directly from the **⚙ Setup / Options** wizard without leaving ster.
- **Copy-paste mode** — no local LLM needed: ster displays the prompt, copies it to the clipboard, and you paste the model's response from any web AI (ChatGPT, Claude, Gemini…).

### Multi-file workspace

- Open several `.ttl` files at once and see a merged taxonomy view
- Edits are always written to the correct source file automatically

### Cross-scheme mapping

- Add `exactMatch`, `closeMatch`, `broadMatch`, `narrowMatch`, `relatedMatch` links between concepts in different files
- Remove links from the detail view — works even when the target file has been deleted
- Both source and target files are saved and staged in git on every change

### Git integration

- Stage, commit, and push changes without leaving the terminal
- Browse full commit history with diffs inside the TUI

### HTML export

- Generate a browsable, wiki-style HTML page from any taxonomy via [pyLODE](https://github.com/RDFLib/pyLODE)
- One HTML file per language detected in the taxonomy
- Sticky language-switcher bar links between language versions
- Available from the main menu or `ster export`

---

## Installation

### Minimal (TUI + editing)

```bash
pip install ster
```

### With AI features

```bash
pip install "ster[ai]"
```

Then configure your model from the main menu: **⚙ Setup / Options**.
No model needed if you use copy-paste mode.

### With HTML export

```bash
pip install "ster[html]"
```

### From source

```bash
git clone https://github.com/gbelbe/ster.git
cd ster
pip install -e .           # core only
pip install -e ".[ai]"     # with AI features
pip install -e ".[html]"   # with HTML export
pip install -e ".[dev]"    # with test suite
```

---

## Dependencies

| Group | Package | Purpose |
|---|---|---|
| core | `rdflib>=7.0` | RDF parsing and serialisation |
| core | `typer[all]>=0.12` | CLI framework |
| core | `rich>=13.0` | Terminal rendering, prompts, tables |
| `[ai]` | `llm>=0.19` | LLM abstraction layer (online & offline models) |
| `[html]` | `pylode>=3.0` | HTML generation from SKOS / OWL (VocPub / OntPub profiles) |
| `[dev]` | `pytest>=8.0` | Test suite |
| `[dev]` | `pytest-cov>=5.0` | Coverage reporting |

Both `llm` and `pylode` are **not** installed by default. When you trigger a feature that needs them, ster will offer to install the package automatically.

---

## Quick start

### Launch the interactive editor

```bash
ster
```

The home screen lists all ontology and taxonomy files in the current directory.
Use arrow keys to navigate the action menu, then press **Enter** to confirm.

```
       ✓  my-ontology.ttl
       ✓  products.ttl

 ▶  1  ↵  Open Tree View
    2  ◈  Open Graph Viz
    3  🌐 Generate Web-Documentation
    4  ⎇  Browse git history
    5  🔍 Query Graph SPARQL (Beta)
    6  ⚙  Setup / Options
    7  ✕  Quit
```

### Keyboard shortcuts (TUI)

| Key | Action |
|---|---|
| `↑` `↓` | Navigate tree / fields |
| `Enter` | Expand/collapse node or open detail |
| `+` | Add concept — opens a menu: enter name manually or use AI Auto Suggest |
| `d` | Delete selected concept |
| `e` | Edit selected field in detail panel |
| `m` | Add a mapping link to another concept |
| `g` | Commit & push changes |
| `?` | Help screen |
| `q` / `Esc` | Back / quit |

### AI Auto Suggest

Press `+` on any concept or scheme, then select **✦ AI Auto Suggest**:

1. ster renders the prompt and shows it for review — edit `prompts.py` to customise the wording
2. Press **Enter** to generate; the AI suggests up to 20 concept names ranked by relevance
3. Navigate the list and press **Enter** to pick a name (pre-fills the creation form)
4. Select **Suggest more** to get a fresh batch with deduplication

In copy-paste mode the prompt is displayed and copied to the clipboard; paste the model's response back and press **Enter** on an empty line.

### Export to HTML

```bash
ster export my-taxonomy.ttl          # generates ./html/my-taxonomy_en.html …
ster export my-taxonomy.ttl -l en,fr # specific languages only
ster export my-taxonomy.ttl -o /tmp  # custom output directory
```

Or use the **🌐 Generate Web-Documentation** option from the main menu.

### Validate

```bash
ster validate my-taxonomy.ttl
```

---

## Annotating entities with rich media

ster reads `schema:image`, `schema:video`, and `schema:url` triples and uses them in the graph visualiser's detail panel:

```turtle
@prefix schema: <https://schema.org/> .

<https://example.org/MyClass> a owl:Class ;
    rdfs:label "My Class"@en ;
    schema:image <https://upload.wikimedia.org/wikipedia/commons/thumb/.../500px-image.png> ;
    schema:video <https://www.youtube.com/watch?v=...> ;
    schema:url   <https://en.wikipedia.org/wiki/My_Class> .
```

Images appear as thumbnails inside D3 node circles; videos open in a popup window; URLs render as link buttons in the detail panel.

---

## Architecture

```
ster/
├── model.py          — Pure dataclasses: Concept, ConceptScheme, Taxonomy, RDFClass, OWLIndividual…
├── store.py          — RDF I/O via rdflib (.ttl / .rdf / .jsonld); loads SKOS + OWL layers
├── operations.py     — All SKOS mutations (add, remove, move, relate…)
├── workspace.py      — Multi-file workspace: merged view + per-file saves
├── workspace_ops.py  — Cross-file mapping operations
├── nav.py            — Full-screen TUI (curses): tree, detail, inline edit; SKOS + OWL modes
├── nav_state.py      — Typed state machine: one dataclass per viewer mode
├── nav_logic.py      — Pure functions: tree flattening, field builders, OWL node rendering
├── cli.py            — Typer entry-points (ster, ster export…)
├── ai.py             — LLM abstraction: model routing, copy-paste mode, Ollama integration
├── prompts.py        — All AI prompt templates (string.Template)
├── html_export.py    — pyLODE HTML export (VocPub / OntPub profiles)
├── viz.py            — Standalone D3 graph: writes HTML, opens in browser
├── owl_analysis.py   — OWL axiom analysis and statistics
├── sparql_query.py   — SPARQL query runner against the loaded taxonomy
├── git_manager.py    — Git staging, commit, push
├── git_log.py        — Git history browser (TUI)
├── git_log_logic.py  — Pure functions: diff parsing, field extraction for git log viewer
├── handles.py        — Short handle generation from camelCase URIs
└── validator.py      — SKOS integrity checks
```

Each layer depends only on the layers below it, keeping every module independently testable.
AI prompts live in `prompts.py` as plain `string.Template` objects — edit them freely without touching any logic.

---

## Supported formats

| Extension | Format |
|---|---|
| `.ttl` | Turtle (recommended) |
| `.rdf` / `.xml` | RDF/XML |
| `.jsonld` / `.json` | JSON-LD |
| `.owl` | OWL/XML |

---

## Development

```bash
pip install -e ".[dev]"
pytest
pytest --cov=ster --cov-report=term-missing
```

---

## CI / CD

Every push and pull request runs four parallel jobs via GitHub Actions:

| Job | Tool | What it checks |
|---|---|---|
| **Lint** | [ruff](https://docs.astral.sh/ruff/) | Code style, import order, common bugs |
| **Type check** | [mypy](https://mypy.readthedocs.io/) | Static type correctness |
| **Security** | [bandit](https://bandit.readthedocs.io/) + [pip-audit](https://pypi.org/project/pip-audit/) | SAST + known CVEs in dependencies |
| **Tests** | [pytest](https://pytest.org/) × Python 3.11 / 3.12 / 3.13 | Full test suite + coverage report |

Coverage is uploaded to [Codecov](https://codecov.io/gh/gbelbe/ster) on every run.

### Run checks locally

```bash
pip install -e ".[dev]"

ruff check .            # lint
ruff format --check .   # format
mypy ster/              # types
bandit -r ster/ -c pyproject.toml   # security
pip-audit               # dependency CVEs
pytest --cov=ster       # tests + coverage
```

Or install the pre-commit hooks to run ruff automatically on every commit:

```bash
pip install pre-commit
pre-commit install
```

---

## Changelog

### 0.3.2
- Show update notice with release notes summary when a new version is available on PyPI
- Restructured main menu: new icons (◈ graph, ⎇ git), reordered items, renamed "Configure AI" → "Setup / Options", added "Query Graph SPARQL (Beta)"
- Tree view auto-detects file content: OWL-only files open in ontology mode, SKOS-only in taxonomy mode
- D3 graph: root OWL classes visually distinct (brighter fill, glow ring, bolder text); legend adapts to content actually present in the file
- Fixed: Escape key in graph viz now always returns to global view
- Fixed: OWL individuals correctly nested under their parent classes in the tree
- Fixed: multiline `rdfs:comment` values no longer bleed across TUI panels
- Fixed: global tree view no longer renders OWL classes twice
- Extend git diff view to detect all field changes: broader/narrower/related, match properties, schema:image/video/url, subClassOf, rdf:type, property assertions, OWL properties
- Removed "Generate Browsable Website" menu option (use `ster export` CLI instead)

### 0.3.1
- Auto-publish to PyPI via GitHub Actions (OIDC trusted publishing) on every passing CI run
- Animate AI suggestion spinners during generation
- Handle missing Ollama gracefully; stream pull output with progress updates

### 0.3.0
- Full-screen TUI for SKOS concept schemes and OWL class hierarchies
- Interactive D3 force graph visualisation in the browser with entity detail panel
- AI-assisted concept creation via `llm` library (online and local via Ollama)
- Git integration: stage, commit, push without leaving the terminal
- HTML export via pyLODE (VocPub and OntPub profiles)
- SPARQL query runner against the loaded taxonomy

---

## License

MIT
