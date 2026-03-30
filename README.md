# ster

[![CI](https://github.com/gbelbe/ster/actions/workflows/ci.yml/badge.svg)](https://github.com/gbelbe/ster/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

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
- Step-by-step **init wizard** (`ster init`)
- Auto-detection of taxonomy files in the current directory
- Round-trip safe: reads and writes `.ttl`, `.rdf`, `.jsonld`
- SKOS integrity validation

---

## Installation

### Minimal (TUI + editing)

```bash
pip install ster
```

### With HTML export

```bash
pip install "ster[html]"
```

### From source

```bash
git clone https://github.com/gbelbe/ster.git
cd ster
pip install -e .          # core only
pip install -e ".[html]"  # with HTML export
pip install -e ".[dev]"   # with test suite
```

---

## Dependencies

| Group | Package | Purpose |
|---|---|---|
| core | `rdflib>=7.0` | RDF parsing and serialisation |
| core | `typer[all]>=0.12` | CLI framework |
| core | `rich>=13.0` | Terminal rendering, prompts, tables |
| `[html]` | `pylode>=3.0` | HTML generation from SKOS (VocPub profile) |
| `[dev]` | `pytest>=8.0` | Test suite |
| `[dev]` | `pytest-cov>=5.0` | Coverage reporting |

pyLODE is **not** installed by default. When you trigger an HTML export, ster will offer to install it automatically.

---

## Quick start

### Launch the interactive editor

```bash
ster
```

The home screen lists all taxonomy files in the current directory. Use arrow keys to check files, then press **Enter** to open them.

```
  ┌─────────────────────────────────────────────────────┐
  │  [ ] equipement.ttl          7 concepts             │
  │  [x] windvane-taxonomy.ttl  23 concepts             │
  └─────────────────────────────────────────────────────┘
  ↵  Open checked files
  ⎇  Browse git history
  🌐 Generate webpage
  +  Create new taxonomy
  ✕  Quit
```

### Keyboard shortcuts (TUI)

| Key | Action |
|---|---|
| `↑` `↓` | Navigate tree / fields |
| `Enter` | Expand/collapse node or open detail |
| `a` | Add a child concept |
| `A` | Add a top-level concept |
| `d` | Delete selected concept |
| `e` | Edit selected field in detail panel |
| `m` | Add a mapping link to another concept |
| `g` | Commit & push changes |
| `?` | Help screen |
| `q` / `Esc` | Back / quit |

### Create a new taxonomy

```bash
ster init my-taxonomy.ttl
```

The wizard walks you through name, description, base URI, languages, and author.

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
├── cli.py           — Typer entry-points (ster, ster init, ster export…)
├── html_export.py   — HTML generation via pyLODE VocPub
├── git_manager.py   — Git staging, commit, push
├── git_log.py       — Git history browser (TUI)
├── wizard.py        — Init wizard
├── handles.py       — Short handle generation from camelCase URIs
└── validator.py     — SKOS integrity checks
```

Each layer depends only on the layers below it, keeping every module independently testable.

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

## License

MIT
