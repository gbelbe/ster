# Test flakiness — what the three failures actually were

> Findings and fixes. The last section lists what is *not* done, so the next
> person starts from the evidence rather than from scratch.

## The observation

Four consecutive runs of `scripts/ci.sh` on one unchanged branch:

| Run | Machine | Result | Test |
|---|---|---|---|
| 1 | browser + a local server running | ✗ | `test_create_reveals_new_individual_survives_background_lint` |
| 2 | same | ✗ | `test_scan_on_open` ×2 |
| 3 | idle | ✓ | — |
| 4 | idle | ✓ | — |

No source changed between runs 2 and 3. Red then green on identical content is
the definition of a flaky test, and three full gate runs — eighteen minutes —
bought one push.

## What CI history says, and why it is misleading

Of the last 100 `ci.yml` runs: 99 distinct commits, one commit ever re-run,
**zero cases of the same commit failing and then passing**. By that metric the
project has no flakiness at all.

It has plenty. The pre-push gate absorbs it *before* the push, so the cost is
paid locally, by whoever is pushing, and leaves no record anywhere. The
ratchet's own docstring predicted the consequence: *"the habit is to re-run
rather than to look"*. That is exactly what happened here — twice, before
looking.

## Cause 1 — a flake reporting a real race

`test_app_create_reveal` waited for a background lint with:

```python
for _ in range(6):
    await pilot.pause()
```

Six turns of the event loop, for work scheduled behind a **1.5 s debounce**.
The turns never reached it, so the test returned with the worker still in
flight, the app tore down, and the worker's callback then ran
`_rebuild_tree()` against a screen that no longer had a tree:

```
textual.worker.WorkerFailed: Worker raised exception:
NoMatches("No nodes match '#tree' on Screen(id='_default')")
```

**That is a production bug, not a test bug.** `_on_lint_ready` assumed the UI it
started with still existed. In the wild it is a crash on quit for anyone who
exits within a second or two of an edit. `_panes_are_mounted()` now guards it,
the twin of the guard `_refresh_busy` already had at the other end of the same
lifecycle.

The test was also testing nothing: it never reached the rebuild it is named
after. It now waits for `_on_lint_ready` itself, takes 2.2 s, and fails if the
re-reveal is removed — verified by removing it.

A first attempt waited on `app._lint_computed`, which looked like the right
signal and was not: something recomputes synchronously during the rebuild, so
the flag is already `True` when the command returns and the wait held
immediately. That is the **third** vacuous predicate in this repo's history
(#181, #184, `d0af901`), and it was caught only by timing the test — 1.46 s for
a wait that should cross a 1.5 s debounce.

## Cause 2 — a wait that stops one callback short

Both `scan_on_open` failures were:

```python
shown = await settle(pilot, lambda: isinstance(app.screen, ProblemsModal))
assert shown
assert len(app.screen.query(ProblemRow)) == 1     # assert 0 == 1
```

Textual swaps the screen, then mounts its children on a later turn. The wait
returns with the modal open and **empty**.

`settle` fixed the *deadline* half of the problem — a wall clock instead of a
turn count — and left the harder half untouched: **what** is being waited for.
A wall-clock wait on the wrong condition is still wrong; it just fails later.

The step-defs copy of this was already fixed on `main` by #202. The unit copy
was not — the fix landed on the instance, not the class. Since it has now been
fixed twice, it gets a rule: `test_no_new_timing_guesses.py` fails on any
`settle` whose predicate names a screen when the lines that follow query that
screen's children. Unlike the count ratchet beside it, this one starts at zero.

## A third thing, found on the way

One of the three failures was a **stale-branch artefact**: the branch stack was
based on `feat/working-file-switcher`, which is several commits behind `main`
and predates #202. Part of what looked like flakiness was a bug already fixed
upstream, met again because the base was old. Rebasing a long-lived branch is a
flakiness measure too.

## The gate answers the wrong question — and the obvious fix does not work

`scripts/pre-push.sh` accepts any sentinel less than 24 hours old. That
answers *"did a run happen recently?"*, not *"was this content checked?"* — so
one can run the gate, edit code, and push inside the window with nothing
rechecked. The banner promises a guarantee the hook does not give.

The obvious fix is to record the tree the gate passed on and compare it at push
time. It was implemented and it **misfires**, for two reasons found by using it:

1. **prek stashes before the check runs.** The pre-push hook chain sets
   unstaged changes aside into `~/.cache/prek/patches/` and only then runs the
   gate check, so the check sees a tree the gate never saw. Any developer with
   unrelated work in progress is blocked from pushing anything.

2. **The gate and the push are about different objects.** `ci.sh` validates the
   *working tree*, usually before committing; the push ships *commits*. In the
   ordinary flow — edit, run the gate, commit, push — HEAD changes in between,
   so an identity anchored on HEAD blocks every push, and one anchored on file
   contents breaks as soon as anything unrelated is dirty.

The attempt is kept on `backup/ci-tree-gate` rather than merged. What would
actually work is narrower: compare the *committed tree being pushed* against the
tree the gate ran on, treating a dirty tree as "gate result does not apply" and
saying so — or moving the check out of the prek chain so it runs before the
stash. Both are more design than this branch should carry.

## Not done — and worth doing

**Measure flakiness instead of absorbing it.** `pytest-report.xml` (JUnit) is
already produced and archived by CI, and nothing reads it. A scheduled job that
runs the suite N times and publishes the tests that were not deterministic would
turn the remaining 66 fixed-count waits from an estimate of risk into a ranked
list of actual offenders.

**Isolate the population that flakes.** Textual app tests are nearly all of it,
and they are fast. `@pytest.mark.xdist_group("tui")` with `--dist loadgroup`
would stop them competing with seven other workers for very little wall time.

**Add `pytest-timeout`.** A hung UI test should fail with a stack, not by
exhausting a 15 s settle deadline somewhere unrelated.

**Fix the gate properly** — see the section above for why the first attempt was
backed out, and what a working version has to account for.

**Do not add blanket reruns.** `pytest-rerunfailures` across the suite would
turn these reds green and destroy the signal that found a real race in
`_on_lint_ready`. If reruns are ever added, they belong in the local gate only,
loudly, and feeding the measurement above.
