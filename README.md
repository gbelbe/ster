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
  [  Simple Taxonomy EditoR     ]
```

**ster** is an interactive terminal editor for [SKOS](https://www.w3.org/TR/skos-reference/) taxonomy files.
Browse, create, and edit concepts in a full-screen TUI — no GUI, no database, just clean Turtle files.

> *ster* is the Breton word for *meaning*, with homonyms for *river* and *star*.
> Let it guide your semantic voyage, keeping the flow and always following your star.

---

## Features

### Interactive TUI
- Full-screen tree browser with keyboard navigation
- Inline concept creation, renaming, deletion, and label editing
- Detail panel: view and edit all SKOS fields (labels, definitions, scope notes, related links…)
- Fold / unfold subtrees; shows hidden-concept count
- Visual `⇔` indicator for concepts that carry cross-scheme mapping links
- Scheme dashboard: completion rates, quality issues, and concept counts at a glance

### AI-assisted concept creation
When adding a concept (`+` key), choose between entering a name manually or letting AI suggest up to 20 ordered concept names:

- **AI Auto Suggest** — the AI acts as a professional taxonomist who knows your domain.
  It proposes names ranked by relevance, you pick one (or ask for more), and the form is pre-filled.
- Before generating, ster shows you the exact prompt so you can review and adjust it.
- Supports any LLM via the [`llm`](https://llm.datasette.io/) library (online or local/offline models).
- **Copy-paste mode** — no local LLM needed: ster displays the prompt, copies it to the clipboard,
  and you paste the model's response from any web AI (ChatGPT, Claude, Gemini…).

Configure AI from the **⚙ Configure AI** menu entry (sets model, provider, and copy-paste mode).

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

### Other
- Auto-detection of taxonomy files in the current directory
- Round-trip safe: reads and writes `.ttl`, `.rdf`, `.jsonld`
- SKOS integrity validation

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

Then configure your model from the main menu: **⚙ Configure AI**.
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
| `[html]` | `pylode>=3.0` | HTML generation from SKOS (VocPub profile) |
| `[dev]` | `pytest>=8.0` | Test suite |
| `[dev]` | `pytest-cov>=5.0` | Coverage reporting |

Both `llm` and `pylode` are **not** installed by default. When you trigger a feature that needs them, ster will offer to install the package automatically.

---

## Quick start

### Launch the interactive editor

```bash
ster
```

The home screen lists all taxonomy files in the current directory as a read-only ✓ display.
Use arrow keys to navigate the action menu, then press **Enter** to confirm.

```
       ✓  equipement.ttl
       ✓  windvane-taxonomy.ttl

 ▶  1  ↵  Open Tree View
    2  ⎇  Browse git history
    3  🌐 Generate webpage
    4  ⚙  Configure AI
    5  ✕  Quit
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

Or use the **🌐 Generate webpage** option from the main menu.

### Validate

```bash
ster validate my-taxonomy.ttl
```

---

## Architecture

```
ster/
├── model.py         — Pure dataclasses: Concept, ConceptScheme, Taxonomy
├── store.py         — RDF I/O via rdflib (.ttl / .rdf / .jsonld)
├── operations.py    — All SKOS mutations (add, remove, move, relate…)
├── workspace.py     — Multi-file workspace: merged view + per-file saves
├── workspace_ops.py — Cross-file mapping operations
├── nav.py           — Full-screen TUI (curses): tree, detail, inline edit
├── nav_state.py     — Typed state machine: one dataclass per viewer mode
├── nav_logic.py     — Pure functions: tree flattening, field builders
├── cli.py           — Typer entry-points (ster, ster export…)
├── ai.py            — LLM abstraction: model routing, copy-paste mode
├── prompts.py       — All AI prompt templates (string.Template)
├── html_export.py   — HTML generation via pyLODE VocPub
├── git_manager.py   — Git staging, commit, push
├── git_log.py       — Git history browser (TUI)
├── handles.py       — Short handle generation from camelCase URIs
└── validator.py     — SKOS integrity checks
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

## License

MIT
