# ster

[![CI](https://github.com/gbelbe/ster/actions/workflows/ci.yml/badge.svg)](https://github.com/gbelbe/ster/actions/workflows/ci.yml)

```
     _
    | |
 ___| |_ ___ _ __
/ __| __/ _ \ '__|
\__ \ ||  __/ |
|___/\__\___|_|

  [ Breton: "Meaning" or "Sense" ]
  [  Druidic Knowledge Command   ]
```

**ster** is an interactive CLI for creating and editing [SKOS](https://www.w3.org/TR/skos-reference/) taxonomy files — directly from your terminal.

> *ster* is the Breton word for "meaning", with homonyms meaning "river" and "star" it will guide you in the creation and evolution of your semantic web voyage, keeping the flow and always following your star!

---

## Features

- **Step-by-step wizard** (`ster init`) to create a new taxonomy with name, description, base URI, languages, and author
- **ASCII tree view** of the full taxonomy or any subtree, with short auto-generated handles (`[BC]`, `[SP]`, …)
- **Handle-based editing** — reference any concept by its short handle instead of typing full URIs
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
ster show my-taxonomy.ttl
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

### Show a subtree or concept detail

```bash
ster show my-taxonomy.ttl -c BC          # subtree rooted at [BC]
ster show my-taxonomy.ttl -c BC --detail # full detail panel
ster show my-taxonomy.ttl --handles      # list all handles
```

### Add a concept

```bash
ster add my-taxonomy.ttl https://example.org/vocab/NewConcept \
  --parent BC \
  --en "New Concept" \
  --fr "Nouveau Concept" \
  --def-en "A new concept under Boat Characteristic."
```

### Remove a concept

```bash
ster remove my-taxonomy.ttl SHR           # remove leaf
ster remove my-taxonomy.ttl RC --cascade  # remove with all descendants
```

### Move a concept

```bash
ster move my-taxonomy.ttl SHR --parent TC   # move [SHR] under [TC]
ster move my-taxonomy.ttl SHR               # promote to top level
```

### Edit labels and definitions

```bash
ster label  my-taxonomy.ttl BR en "Balanced Rudder"
ster label  my-taxonomy.ttl BR fr "Safran Équilibré" --alt
ster define my-taxonomy.ttl BR en "A rudder with area forward of the pivot axis."
```

### Add a related link

```bash
ster relate my-taxonomy.ttl SP OAR          # add skos:related
ster relate my-taxonomy.ttl SP OAR --remove # remove it
```

### Rename a URI

```bash
ster rename my-taxonomy.ttl OLD https://example.org/vocab/NewURI
```

### Validate

```bash
ster validate my-taxonomy.ttl
```

---

## Command reference

| Command | Description |
|---|---|
| `ster init [file]` | Interactive wizard to create a new taxonomy |
| `ster show <file>` | Display the full taxonomy tree |
| `ster show <file> -c HANDLE` | Display a subtree |
| `ster show <file> -c HANDLE -d` | Display concept detail |
| `ster show <file> -H` | List all handles |
| `ster add <file> <uri>` | Add a new concept |
| `ster remove <file> HANDLE` | Remove a concept |
| `ster move <file> HANDLE` | Move a concept |
| `ster label <file> HANDLE <lang> <text>` | Set a label |
| `ster define <file> HANDLE <lang> <text>` | Set a definition |
| `ster relate <file> HANDLE_A HANDLE_B` | Add/remove a related link |
| `ster rename <file> HANDLE <new-uri>` | Rename a concept URI |
| `ster handles <file>` | Print handle index table |
| `ster validate <file>` | Check SKOS integrity |

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

90 tests, all passing.

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
