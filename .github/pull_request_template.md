<!--
  ster PR checklist — see CLAUDE.md for the mandatory development workflow.
  CI enforces the mechanical parts (patch coverage, complexity ratchet, import
  contracts, feature bindings, signed commits). The boxes below cover the parts
  CI can't see — tick what applies, delete what doesn't.
-->

## What & why

<!-- One or two sentences: what this changes and the problem it solves. -->

## Checklist

- [ ] **Clarified & simplified** — rephrased the request and applied **YAGNI** to cut scope to the simplest thing that works
- [ ] **Tests first** — wrote the Gherkin `.feature` / unit tests before the implementation; new behaviour is covered (patch coverage ≥ 90%)
- [ ] **Bug fix?** added a regression test that fails without the fix, plus the related edge cases
- [ ] **Touched existing code?** refactored toward lower complexity instead of adding branches, and updated the affected tests
- [ ] **New dependency?** justified below, kept minimal, and isolated behind a single adapter module
- [ ] `bash scripts/ci.sh` is green locally (lint, types, security, tests, complexity, import contracts)
- [ ] Commits are GPG-signed

## Notes

<!-- Trade-offs, follow-ups, screenshots, or anything reviewers should know. -->
