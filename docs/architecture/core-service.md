# Architecture: a shared core for all taxonomy/ontology mutations

Status: **proposed** (design agreed, not yet implemented)
Audience: ster maintainers

## 1. Why

Today every mutation to a TTL/ontology file is orchestrated **inline in the
curses controller** (`ster/nav/viewer.py`, ~6,900 lines). The "mutate →
rebuild → save → fan-out → reposition" sequence is repeated across ~55
handlers, each entangling four concerns: domain mutation, persistence,
side-effects (git/viz/cache/analysis), and curses view-state.

There is **no seam** another front-end can call. We want a second front-end —
a **web UI over an HTTP API** — that has *strictly the same effect* as the TUI,
and we want logic changes (e.g. a new quality check on TTL changes) to apply to
**every** front-end automatically.

The domain itself is already clean: `operations.py` / `workspace_ops.py` are
pure model mutations (no curses, no I/O); `store.py` is pure load/save. The
work is to extract the orchestration into a shared application core.

## 2. Goal

One **application core** that owns every mutation pipeline — mutation, quality
checks, persistence, side-effects — so that the curses TUI, the HTTP API, and
the CLI are all **thin adapters** calling the same core. "Same effect as
curses" then holds *by construction*.

## 3. Target architecture (hexagonal / ports-and-adapters)

```
        ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
        │  curses TUI  │   │   HTTP API   │   │     CLI      │   ADAPTERS (thin):
        │  viewer.py   │   │   api.py     │   │   cli.py     │   build a Command,
        └──────┬───────┘   └──────┬───────┘   └──────┬───────┘   render the Result
               └──────────────────┼──────────────────┘
                          Command │ (dataclass: intent only)
                          ┌───────▼──────────────────────────────┐
                          │          TaxonomyService              │  APPLICATION CORE (new):
                          │  execute(change, base_version)        │  the ONE pipeline
                          │   1 lock + version (OCC) check        │
                          │   2 clone → apply mutation(s)         │──► operations.py (pure, exists)
                          │   3 validate (quality checks)         │──► validator + lint_runner + ster_checks
                          │   4 atomic commit OR rollback         │──► Persistence port  → store.py
                          │   5 bump version + emit event         │──► VersionControl port → GitManager
                          └───────────────────────────────────────┘    EventSink port      → viz/SSE/cache
```

Layers:

- **Domain** — `model.py`, `operations.py`, `workspace_ops.py`. Pure. Keep.
- **Application/core** — `service.py`, `commands.py`, `ports.py` (new). No
  curses, no FastAPI. Fully unit-testable.
- **Ports** — injected interfaces (`Persistence`, `VersionControl`,
  `EventSink`, `Validator`). The core decides *what* happens; adapters carry it
  out.
- **Adapters** — curses (`viewer.py`), HTTP (`api.py`), CLI (`cli.py`).

### 3.1 Commands

One small frozen dataclass per user action — *intent only*. These map ~1:1 onto
the existing public functions in `operations.py`, so the vocabulary is mostly
discovered, not invented. They double as API request bodies.

```python
@dataclass(frozen=True)
class MoveClass:                 # OWL reparent (rdfs:subClassOf)
    target_path: Path
    source_uri: str
    new_parent_uri: str | None
    replace: bool = True

@dataclass(frozen=True)
class AddConcept: ...
@dataclass(frozen=True)
class SetLabel: ...
# ~30 total, mirroring operations.py
```

A `ChangeSet` is an ordered list of commands committed atomically (one
transaction).

### 3.2 Service + result

```python
def execute(self, change: Command | ChangeSet,
            *, base_version: int | None = None) -> CommandResult: ...
```

`CommandResult` carries: `ok | rejected | failed`, the new `version`, the
affected URIs, and a `ValidationReport`. This is the single seam every adapter
calls.

### 3.3 Ports

```python
class Persistence(Protocol):     def save(self, tax, path) -> None          # atomic
class VersionControl(Protocol):  def stage(self, path) -> None; ...
class EventSink(Protocol):       def changed(self, event: ChangedEvent) -> None
class Validator(Protocol):       def check(self, tax) -> ValidationReport
```

Curses injects adapters that also nudge the screen; the API injects an SSE sink;
tests inject fakes. The core is unaware of any of them.

## 4. Transactions

**Boundary** = one command, or a `ChangeSet` (batch) — all-or-nothing.

**Rollback strategy: clone-apply-swap** (cleanest for in-memory dataclasses):

```python
with self._lock_for(change.target_path):          # serialize writers (§5)
    entry = self._authority[change.target_path]
    self._check_version(entry, base_version)       # OCC gate (§5)

    working = deepcopy(entry.taxonomy)             # BEGIN: isolated copy
    try:
        for cmd in change.commands:
            apply_domain_mutation(working, cmd)    # operations.py — may raise
        report = self._validate(working)
        if report.blocks():                        # policy: block on error
            return CommandResult.rejected(report)  #   discard clone; model untouched
    except DomainError as e:
        return CommandResult.failed(e)             #   discard clone; model untouched

    atomic_save(working, change.target_path)       # COMMIT: temp file + os.replace + fsync
    entry.taxonomy = working                        # swap in new authority
    entry.version += 1; entry.mtime = stat()
    self._emit(ChangedEvent(change.target_path, entry.version, affected_uris))
    return CommandResult.ok(entry.version, report, affected_uris)
```

ACID mapping:

- **Atomic** — clone + single `os.replace` (atomic on POSIX); a crash leaves the
  *old* file intact, never a half-written one.
- **Consistent** — the validation gate is the invariant check; a change that
  violates quality rules never reaches disk (**block-on-error**, decided).
- **Isolated** — each transaction works on its own clone; the write lock
  serializes commits.
- **Durable** — `fsync` + rename before returning success.

Prerequisites / notes:

- **`atomic_save`**: change `store.save` to write `path.tmp` then
  `os.replace(tmp, path)` (+ fsync). Today it serializes directly to the
  destination — a crash or concurrent read mid-serialize can truncate the file.
  Small, standalone, independently shippable; hard prerequisite for
  transactions.
- **Clone cost**: `deepcopy` per transaction is fine for typical taxonomies
  (hundreds–thousands of nodes, human-paced edits). If profiling later shows it
  hurts on very large ontologies, switch to an **inverse-operation journal**
  without changing the public contract. YAGNI for now.
- **Undo/redo bonus**: once every mutation is a transactional command, a stack
  of committed `ChangeSet`s gives undo/redo nearly for free — serving both the
  TUI (`self._history` becomes this) and a web client's Ctrl-Z.

## 5. Concurrency

ster is a **single-user app**: one person uses *either* the TUI *or* the web UI,
both in the **same process** (the API/viz server already runs as a daemon thread
via uvicorn inside the ster process). So concurrency splits into two axes:

| Axis | Who | Mechanism |
|---|---|---|
| **Intra-instance** | this user's TUI ⇄ web UI | in-memory authority + per-file `threading.Lock` + OCC version token |
| **Inter-instance** | other users running their own ster on the same ontology | git pull/push + TTL merge + external-change detection (mtime/hash) |

Consequence: **no cross-process file locking** (`filelock`) is needed. The
inter-instance axis is git's job and is largely handled already by
`GitManager.check_and_pull` / `pre_edit_check`.

### 5.1 Authority + serialized writes

`TaxonomyService` owns the loaded `Workspace` as the single source of truth, with
a **per-file** `threading.Lock` (decided: per-file granularity). Per-file so
editing file A never blocks file B; cross-file ops (mappings) take both locks in
URI order to avoid deadlock. The API thread and the curses loop share the same
service object, so one lock governs all writers.

### 5.2 Optimistic concurrency control (OCC)

Each loaded file carries a monotonic `version`. Reads return it; writes carry the
version they were based on. Maps directly onto HTTP ETag / `If-Match`:

```
GET /files/foo.ttl/classes/Dog          → 200  ETag: "v7"
PUT /classes/Dog/superclass {Mammal}      If-Match: "v7"
        ├─ current == v7 → commit, ETag "v8"
        └─ current != v7 → 409 Conflict + current state   (client re-bases, retries)
```

Prevents lost updates between the web UI and TUI without user-visible locking.
The TUI holds the authority object directly so its edits always bump the version
— a stale web `PUT` is rejected, i.e. **the human's in-flight edits win**.

### 5.3 Live cross-front-end sync (free property)

Because it is one in-process model, an API write mutates the shared authority and
the `EventSink` fires a `ChangedEvent`. Subscribers react: the curses adapter
sets a "needs rebuild" flag its loop reads on the next tick (web edit shows up
live in the terminal); an SSE endpoint pushes to web clients. `api.py` already
has `SSEBroadcaster` and a viz push channel — `EventSink` generalizes them into
the single notification the core emits after every commit. (Thread-safety: the
curses loop must touch the model under the same lock, or act only on the posted
flag.)

### 5.4 External changes

On read, the service compares `mtime`/hash to what it loaded; if drifted, it
reloads or raises a conflict. Fold `GitManager.check_and_pull` into the service
read path so the API inherits the same protection as the TUI.

## 6. Decisions (locked)

1. **In-process, single-user** — intra-instance concurrency only; inter-instance
   handled by git. No cross-process locking.
2. **OCC granularity: per file.**
3. **Quality-check policy: block on error**, commit on warning.

## 7. Refactor inventory (full-code map)

| Area | Today | Change |
|---|---|---|
| `operations.py`, `workspace_ops.py` | pure, good | keep as the domain layer the service calls |
| **`service.py`** (new) | — | `TaxonomyService` + transactional pipeline + lock/OCC |
| **`commands.py`** (new) | — | ~30 Command dataclasses + `ChangeSet` + dispatch table |
| **`ports.py`** (new) | — | `Persistence` / `VersionControl` / `EventSink` / `Validator` |
| `store.save` | direct write | `atomic_save` (temp + `os.replace` + fsync) |
| `viewer.py::_save_file` (55 callers) | inline save+git+viz+analysis+cache | extract into service persist+emit; `_save_file` becomes one call |
| `viewer.py` ~18 direct `operations.*` + `_confirm_*` handlers | mutate+rebuild+save inline | each becomes `service.execute(Command(...))` then render; delete inline orchestration |
| `state.py` `Effect` types (defined, **unused**) | dead scaffolding | consume them as the curses render-effect channel, or fold into `CommandResult` — don't leave half-built |
| validation (`validator.py`, `lint_runner.py`, `ster_checks.py`) | called ad-hoc | invoked uniformly as pipeline step 3 |
| `api.py` | read-only GET + viz | add mutation router: endpoint → Command → `execute` → JSON(Result); ETag/`If-Match`; SSE on `ChangedEvent` |
| `cli.py` `cmd_move`/`cmd_subclass`/`cmd_remove` | call `operations.*` then save separately | route through the same service so the CLI can't diverge |
| `viewer.py` size (6.9k lines) | god-object | as handlers thin out, split per-mode controllers into modules |

## 8. Step-by-step plan (strangler-fig; tests green at every step)

Discipline: no big-bang rewrite. Build the core beside existing code, migrate one
action at a time, prove equivalence.

- **Phase 0 — Characterization tests.** ~5 representative mutations (move class,
  add concept, set label, remove concept, rename URI): starting TTL + action →
  resulting TTL bytes + git-staged state. The golden contract the refactor must
  not break.
- **Phase 1 — Atomic save** (standalone, shippable). `store.save` → temp +
  `os.replace` + fsync. Value on its own: no more truncated TTLs. Prerequisite
  for transactions.
- **Phase 2 — Vertical slice: `MoveClass`.** Add the command, the transactional
  `execute()` (clone→apply→validate→commit/rollback) + per-file lock + `version`
  in result. Re-point `_confirm_owl_reparent` / `_confirm_move` at it.
  Equivalence test: same command via service vs. old handler → identical TTL.
  Bake in `version` (result) and `base_version` (command) now.
- **Phase 3 — Quality-check step.** `Validator` port over `lint_runner`/
  `validator`; `CommandResult.validation` populated on every command; curses
  renders it; enforce block-on-error. Fold `check_and_pull` into the read path.
- **Phase 4 — Migrate remaining ~30 actions** command by command. Each handler
  becomes build-Command → execute → render; delete inline `operations.*` +
  `_save_file`; add an equivalence test. `Effect` types become the
  service→curses "rebuild/reposition" channel.
- **Phase 5 — API as a thin adapter.** Mutation router over the *same* service;
  OCC wired to ETag/`If-Match` (409 on conflict); `EventSink` → SSE for live web
  updates. Cross-adapter equivalence tests: same command via API vs. curses →
  identical TTL + git state.
- **Phase 6 — Tidy.** Undo/redo on the committed-ChangeSet stack; split the
  thinned `viewer.py` into per-mode modules; remove dead scaffolding; document
  the "Command in, Result out" contract.

## 9. Deferred / revisit

- Inverse-operation journal instead of deepcopy, **if** clone cost is measured to
  matter on large ontologies.
- Per-entity (finer) OCC, **if** single-user per-file conflicts prove too coarse
  (unlikely for one user).
- Standalone-server API (separate process) — would require cross-process locking
  + a notification channel and would lose live in-process TUI sync. Out of scope
  while ster stays single-process.
