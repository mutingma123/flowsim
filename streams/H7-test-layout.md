# H7 Test layout and shared fixtures

**Status: proposed 2026-11-05.**
Depends on: H4 (run order, to keep one tree)
Branch: health-2.0 (owner ruling, 2026-11-05: chunks commit on health-2.0, which is pushed;
main is not merged or fast-forwarded until the owner approves the 2.0 release)

## Goal

tests/test_reporting.py is split into reporting, diagram, and dashboard files; helpers sit before their first use; one_stage_chain, producing_factory, and a queue_comparison factory live in tests/models.py; test_service_day.py's identical deterministic comparisons share one module-scoped fixture; and the six-behavior unsaved-page test is split. No assertion changes. Serves chunk H7 (Reader 4 findings 3, 4, 11; Reader 5 findings 8, 11).

## Read first

- tests/test_reporting.py
- tests/test_service_day.py
- tests/models.py
- AGENTS.md (via CLAUDE.md) and .code-health/scan-2026-11-05.md for the evidence.

## Scope

May change:
- tests/test_reporting.py
- tests/test_diagram.py (new)
- tests/test_dashboard.py (new)
- tests/test_service_day.py
- tests/models.py
- tests/test_viewer_browser.py (shared setup only)

Shared files (`pixi.toml`, `pixi.lock`, `CLAUDE.md`, `AGENTS.md`, `conftest.py`, `README.md`)
may change only if listed above; a needed change to one that is not listed is a stop.

Must not touch:
- manim/, review-loop/, output/ contents other than by the example tasks;
- any hand-calculated expected value in tests (owner ruling, 2026-11-05);
- the numbers the examples print or export (golden check and the three sentinels);
- AGENTS.md rules (station path through _Station, tie order, no global behavior defaults,
  library tests never import examples/), and the builder never preselects a behavior.

## Done check

- `bash .code-health/gate.sh H7` prints: check `EXIT=0` with the previous count, plus the parts of the split unsaved-page test passed; examples
  `EXIT=0` with sentinels 3/3 (78.634267, 3.239704, 1.093583); `GOLDEN=MATCH`;
  coverage at least 98.2%; mass at most 109 (12.1 per 1,000 statements); every bench line
  PASS (run 5.333 s and 404 MB, compare 1.396 s and 192 MB, dashboard 5.597 s and 303 MB).
- Mutation sample: `bash .code-health/mutation.sh H7 <scratch>` scores at least station 423/473 (89.4%), engine 738/826 (89.3%), and results metrics 745/807 (92.3%), or, where the mutant count changes, at least the same percentage.
- No hand-calculated expected value changes: every changed line under tests/ in
  `git diff 02c98d9 -- tests` is read by hand before commit.
- One Codex adversarial review of the chunk, findings verified and dispositioned under Result.
- `wc -l tests/test_reporting.py` under 1,000 (from 1,455), and the suite's ST1 finding on it is gone (`run.py --root . --file tests/test_reporting.py --rule ST1 --expect-none` exits 0).
- Every moved test keeps its name and body; a fixture shared across tests is never mutated by one of them.

## Approach

Move, do not rewrite. A module-scoped fixture is only safe where no test edits the comparison's runs; tests that edit run.summary keep their own build. Sonnet does the moves; the session reviews the fixture sharing.

## Stop and ask

Beyond the standing list: any change to a simulation number, any golden mismatch that a
rename map entry cannot explain, and any test removal not named in this brief.

## Progress

## Result
