# ster

[![CI](https://github.com/gbelbe/ster/actions/workflows/ci.yml/badge.svg)](https://github.com/gbelbe/ster/actions/workflows/ci.yml)

```
   _____ ______ ______ ____
   / ___//_  __// ____// __ \
   \__ \  / /  / __/  / /_/ /
  ___/ / / /  / /___ / _, _/
 /____/ /_/  /_____//_/ |_|

  [ Breton: "Meaning" or "Sense" ]
  [  Simple Taxonomy EditoR   ]
```

**ster** is an interactive CLI for creating and editing [SKOS](https://www.w3.org/TR/skos-reference/) taxonomy files — directly from your terminal.

> *ster* is the Breton word for "meaning", with homonyms meaning "river" and "star" it will guide you in the creation and evolution of your semantic web voyage, keeping the flow and always following your star!

---

## Features

- **Step-by-step wizard** (`ster init`) to create a new taxonomy with name, description, base URI, languages, and author
- **Auto file detection** — omit the file argument and ster finds the taxonomy in the current directory; once confirmed, it is remembered for the whole session
- **ASCII tree view** of the full taxonomy or any subtree, with short auto-generated handles (`[BC]`, `[SP]`, …)
- **Handle-based editing** — reference any concept by its short handle instead of typing full URIs
- **Default labels** — omit `--en`/`--fr` and ster derives a human-readable label from the concept name (`SpadeRudder` → `"Spade Rudder"`)
- **Full SKOS support** — `prefLabel`, `altLabel`, `definition`, `scopeNote`, `broader`, `narrower`, `related`, `topConceptOf`
- **Multi-language** labels and definitions out of the box
- **Round-trip safe** — reads and writes `.ttl` (Turtle), `.rdf` (RDF/XML), and `.jsonld` (JSON-LD)
- **SKOS integrity validation** — detects missing labels, orphan concepts, broken references, and circular hierarchies

---

## Installation

```bash
pip install ster
```

Or install from source:

```bash
git clone https://github.com/gbelbe/ster.git
cd ster
pip install -e .
```

---

## Quick start

### Create a new taxonomy

```bash
ster init my-taxonomy.ttl
```

The wizard will guide you through:

```
Step 1/6 — Output file
Step 2/6 — Languages
Step 3/6 — Taxonomy name
Step 4/6 — Short description
Step 5/6 — Base URI
Step 6/6 — Creator / author
```

At every step, press **Enter** to accept the default, type **skip** to leave an optional field blank, or type **quit** to cancel.

### View the taxonomy tree

```bash
ster show                    # auto-detects the .ttl file in current directory
ster show -f my-taxonomy.ttl # explicit file (remembered for the session)
```

```
My Taxonomy
├── [BC]    Boat Characteristic
│   ├── [RC]    Rudder Characteristic
│   │   ├── [RT]    Rudder Type
│   │   │   ├── [THR]   Transom-Hung Rudder
│   │   │   ├── [SHR]   Skeg-Hung Rudder
│   │   │   └── [SPR]   Spade Rudder
│   │   └── [RCO]   Rudder Compensation
│   │       ├── [BR]    Balanced Rudder
│   │       ├── [SBR]   Semi-Balanced Rudder
│   │       └── [UBR]   Unbalanced Rudder
│   └── ...
```

If multiple taxonomy files are found, an interactive picker is shown (with Tab completion):

```
Multiple taxonomy files found:

   1  windvane.ttl
   2  materials.ttl

Select file (number or filename, Tab to complete): _
```

Once selected, the file is used automatically for all subsequent commands in the session.

### Show a subtree or concept detail

```bash
ster show -c BC          # subtree rooted at [BC]
ster show -c BC --detail # full detail panel
ster show --handles      # list all handles
```

### Add a concept

```bash
# Labels auto-derived from the name when omitted
ster add SpadeRudder --parent RT

# Explicit labels
ster add NewConcept --parent BC --en "New Concept" --fr "Nouveau Concept" \
  --def-en "A new concept under Boat Characteristic."
```

### Remove a concept

```bash
ster remove SHR           # remove leaf
ster remove RC --cascade  # remove with all descendants
```

### Move a concept

```bash
ster move SHR --parent TC   # move [SHR] under [TC]
ster move SHR               # promote to top level
```

### Edit labels and definitions

```bash
ster label  BR en "Balanced Rudder"
ster label  BR fr "Safran Équilibré" --alt
ster define BR en "A rudder with area forward of the pivot axis."
```

### Add a related link

```bash
ster relate SP OAR          # add skos:related
ster relate SP OAR --remove # remove it
```

### Rename a URI

```bash
ster rename OldName NewName
```

### Validate

```bash
ster validate
```

---

## Command reference

All commands accept an optional `--file / -f` flag. When omitted, ster auto-detects a taxonomy file in the current directory and remembers the choice for the session.

| Command | Description |
|---|---|
| `ster init [file]` | Interactive wizard to create a new taxonomy |
| `ster show` | Display the full taxonomy tree |
| `ster show -c HANDLE` | Display a subtree |
| `ster show -c HANDLE -d` | Display concept detail |
| `ster show -H` | List all handles |
| `ster add NAME` | Add a new concept (label auto-derived if omitted) |
| `ster remove HANDLE` | Remove a concept |
| `ster move HANDLE` | Move a concept |
| `ster label HANDLE <lang> <text>` | Set a label |
| `ster define HANDLE <lang> <text>` | Set a definition |
| `ster relate HANDLE_A HANDLE_B` | Add/remove a related link |
| `ster rename HANDLE <new-name>` | Rename a concept URI |
| `ster handles` | Print handle index table |
| `ster validate` | Check SKOS integrity |

---

## Architecture

```
ster/
├── model.py        # Pure dataclasses — Concept, ConceptScheme, Taxonomy
├── handles.py      # Handle generation from camelCase URIs
├── store.py        # RDF I/O via rdflib (.ttl / .rdf / .jsonld)
├── operations.py   # Business logic — all SKOS mutations
├── display.py      # Rich terminal rendering (tree, detail, table)
├── wizard.py       # Step-by-step init wizard
└── cli.py          # Typer CLI commands
```

Each layer depends only on the layers below it, making every module independently testable.

---

## Development

```bash
pip install -e ".[dev]"
pytest
```

112 tests, all passing.

---

## Supported formats

| Extension | Format |
|---|---|
| `.ttl` | Turtle (recommended) |
| `.rdf` / `.xml` | RDF/XML |
| `.jsonld` / `.json` | JSON-LD |

---

## License

MIT
