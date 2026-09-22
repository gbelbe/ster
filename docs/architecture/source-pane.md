# The source pane — reading the file as code

The right-hand slot of the TUI has two faces. The detail panel composes an
entity into labelled, editable rows; the **source pane** shows the same entity
as Turtle. `r` swaps between them. Navigate the trees on the left as usual and
the pane follows the selection, so the loop is: move down the tree, read the
RDF beside it.

It is a *reading* surface. Editing the text is a separate piece of work — see
"Why editing is not here" below.

## What "the entity's source" means

`ster.entity_source.entity_source(graph, uri)` returns the text and the line
range the entity's own statements occupy:

1. **Its own triples**, plus the blank nodes it owns. A blank node has no name,
   so stopping the closure at one would print `[ ]` and lose everything inside
   it — the restriction, the address, the list.
2. **The triples that point at it**, below a marked separator.

The second half is why the pane is worth opening on a graph rather than just
opening the file. `ant:depot` carries no statement about belonging to a dossier,
because that fact is written on the dossier. Without inbound statements the pane
could never answer "what is this part of".

It is also the unbounded half: a hub class can be the object of thousands of
triples. So it is capped at `MAX_INCOMING` and the cap says so in the text
rather than trailing off silently. The pane's border title carries the count,
since that is the one fact the text does not give you at a glance.

## Why the text is highlighted the way it is

Textual's `TextArea` highlights through tree-sitter, and ships grammars for
bash, css, go, html, java, javascript, json, markdown, python, regex, rust,
sql, toml, xml and yaml. **No RDF among them** — the same wall
`ster.tui.sparql_highlight` was written against for the query editor.

A read-only pane does not have to climb it. Pygments has carried a Turtle lexer
for years and Rich renders it, so the view is a `Static` holding a
`rich.syntax.Syntax`. Line numbers come from `Syntax`, and the entity's own
block is passed as `highlight_lines` so the inbound half below reads as context
rather than as more of the same subject.

> **Trap:** Pygments' `ttl` alias resolves to *Tera Term macro*, not Turtle.
> Ask for `turtle` by name. The wrong lexer produces plausible-looking colour
> that is nonsense.

The theme is `ansi_dark` / `ansi_light`, chosen from the Textual theme's own
`dark` flag, so the pane draws from the 16 ANSI colours the terminal and ster's
theme already agreed on instead of importing a second palette.

## The graph behind it, and when it is built

The text is cut from the session's whole graph — model + residue + context
files — because inbound statements are only answerable there.

That costs a full `full_graph_rdflib` pass, far too much to repeat on every
arrow keypress. So:

* it is built **on first use**, not at startup;
* it is **never built at all** for a reader who does not press `r`
  (`_refresh_source` returns immediately while the detail face is showing);
* it is **dropped on every edit**, beside the lint cache, in `_busy_save`.

Remembered scroll positions are dropped with it: they are line offsets, and
after an edit the same number points at a different statement. The entity on
screen is the exception — the refresh re-remembers where it is, because throwing
the reader to the top of the file for an edit they just made is the more jarring
half of that trade.

## Where the code lives

| | |
|---|---|
| `ster/entity_source.py` | graph → Turtle. Pure: no widget, no Textual, no theme. |
| `ster/tui/source_view.py` | the `SourceView` widget: `Syntax`, scroll memory, copy. |
| `ster/tui/app/_source.py` | the `_SourceMixin`: the `r` switch, the cached graph, invalidation. |
| `ster/tui/app/_lifecycle.py` | the `ContentSwitcher` holding both faces of the right slot. |

`entity_source` sits at the top level beside `geo_shapes` / `time_shapes` /
`viz_shared` — the family of pure, graph-in, view-data-out modules shared by the
TUI, the HTTP layer and the tests. It is deliberately not in `store/`: `store`
is the file boundary (load, save, convert, normalise, cache), and this module
never touches a file.

## Why editing is not here

Showing the text needs a lexer. *Applying* an edit needs something else
entirely: parsing arbitrary Turtle and reconciling it against a structured
`Taxonomy`. Every edit the TUI performs today goes through a typed action —
`label`, `define`, `relate`, `move` — each of which knows what it changed and
what to revalidate. Free text can express things none of those can, including
deleting the entity out from under the tree that is displaying it.

The pieces that would be needed: a `turtle_highlight.py` twin of
`sparql_highlight.py` (the `TextArea` path, since tree-sitter has no grammar), a
parse-and-diff step, and a reconciliation into the model. The model is already
built for the last part — `Concept.annotations` and `taxonomy.residue` exist so
unmodelled predicates round-trip — but none of it is written yet.

## Extending it

- **Another serialisation** (JSON-LD, N-Triples) — `entity_source` builds a
  small `rdflib.Graph` and calls `serialize`; the format is one argument, and
  Pygments has lexers for both.
- **A wider slice** — `MAX_INCOMING` bounds the inbound half; `_BNODE_DEPTH`
  bounds the closure. Both are module constants, not scattered literals.
