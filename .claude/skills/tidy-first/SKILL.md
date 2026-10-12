---
name: tidy-first
description: Before writing a feature or fix, check the code you're about to touch against the craftsmanship catalog (Beck's Tidy First, Fowler's Refactoring smells, Clean Code, Feathers' legacy-code method) and tidy it first as its own commit, separate from the behavioral one. Use before starting any change to an existing file, class, or function, before writing new code (as a design checklist), and when the tidy-ratchet (pre-push hook / CI) blocks a push for missing a tidy(<type>): or test(characterize): commit.
---

# Tidy First

This is a thin wrapper. **The actual content — the full catalog, the
procedure, the commit convention, the legacy-code workflow — lives in
`CRAFTSMANSHIP.md` at the repo root** (no relative link here on purpose:
this file's own depth changes when copied — e.g. `bootstrap.sh` deploys it
to `.claude/skills/tidy-first/SKILL.md` in a consuming repo — so "repo root"
stays correct regardless of where this copy lives). It's written to be read
by a human contributor or any other tool too, not just here.

Read `CRAFTSMANSHIP.md` in full before acting on this skill. What follows is
only the Claude-Code-specific part: how to run its procedure in this tool.

## Running the procedure here

`CRAFTSMANSHIP.md`'s procedure says "ask the developer to confirm before
touching anything." In Claude Code, that means the `AskUserQuestion` tool,
not a plain chat question:

- **One candidate tidying**: ask a single go/no-go question, with the smell,
  its source, and the value it brings in the option description.
- **Several candidates**: ask one question with one option per candidate,
  each option's description carrying its own smell/source/value — plus an
  implicit "none of these" (the user can always decline).

Never decide silently and never skip the ask because a candidate looks
obvious — the catalog names *what* to consider, not *whether* it's worth it
here, and that judgment call is the developer's.

**Exception**: for the subset of the catalog craftCov can detect (`scripts/craftcov.py --list-detectors`),
skip the ask entirely and follow `CRAFTSMANSHIP.md`'s "Refactor First"
section instead — scope craftCov to the touched file, fix one instance of
every heuristic it finds present, bundle all of it into one `tidy(multi):`
commit. No judgment call needed there: presence (count > 0) *is* the
decision, and CI's `refactor-first` gate checks the outcome mechanically.

**Same exception** for cyclomatic/cognitive complexity, invariant return,
and duplicated string literal (CG032-CG035) — `scripts/
check_complexity_ratchet.py` (CI's `complexity` gate) checks these
mechanically too, independent of craftCov; see CRAFTSMANSHIP.md's "The
complexity ratchet."

## Before you push

Read `CRAFTSMANSHIP.md`'s **"What to expect before you push"** first. It lists what the gates do that is easy to
miss: new files must start at 0 detectable smells, a touched file must end lower than it began, framework-called
code needs a vulture `noqa` code, the refactor gate prints nothing on uncommitted changes, and a failing test
hides the patch-coverage step. Run the gates on the *committed* range, then push once.

## Where the mechanical parts live

- `scripts/check_tidy_ratchet.sh` — the pre-push/CI ratchet (commit-message
  pattern check, covers the whole catalog).
- `scripts/check_refactor_first.py` — the pre-push/CI count-based gate for
  just the 8 craftCov-detectable heuristics (see "Refactor First" above).
- `scripts/check_complexity_ratchet.py` — the pre-push/CI diff-aware gate
  for complexity/invariant-return/duplicated-literal (see "The complexity
  ratchet" above) — independent of craftCov.
- `scripts/craftcov.py --file <path> [--class <name>]` — what heuristics
  (and how many) are currently present in one file, to work through.
- `scripts/report_tidy_history.sh` — the periodic exemption-ratio and
  cited-sources report (see `CRAFTSMANSHIP.md`'s "Don't let the exemption
  become the rule").
- `catalog.yaml` — machine-readable mirror of the catalog table, for tooling
  that wants to consume it programmatically rather than parse markdown.
