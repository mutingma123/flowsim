# H6 Split results.py and remove the import cycle

**Status: proposed 2026-11-05.**
Depends on: H3 (run order, to keep one tree)
Branch: health-2.0 (owner ruling, 2026-11-05: chunks commit on health-2.0, which is pushed;
main is not merged or fast-forwarded until the owner approves the 2.0 release)

## Goal

results.py keeps Results, Experiment, and the per-run metric computation; the metric and column catalog moves to flowsim/catalog.py with keyword Metric entries and one table of scope facts, and the record dataclasses and schemas move to flowsim/records.py, so plots and reporting no longer force imports inside 10 methods. Serves chunk H6 (Reader 2 findings 3, 5, 6; Codex F01, F02, F25; Reader 5 finding 4). API-breaking for import paths; the owner approved the matching AGENTS.md line edit.

## Read first

- flowsim/results.py in full; flowsim/reporting.py and flowsim/plots.py imports.
- tests/test_simulation.py:1230-1265 (the import-policing test).
- AGENTS.md 'Adding a station or source behavior', step 3.
- AGENTS.md (via CLAUDE.md) and .code-health/scan-2026-11-05.md for the evidence.

## Scope

May change:
- flowsim/results.py
- flowsim/catalog.py (new)
- flowsim/records.py (new)
- flowsim/reporting.py
- flowsim/plots.py
- flowsim/model.py
- flowsim/engine.py
- flowsim/station.py
- flowsim/comparison.py
- flowsim/__init__.py
- flowsim/builder_page.py
- flowsim/fitting.py
- tests/ (import lines only, plus the import-policing test)
- README.md (module references only)
- AGENTS.md (step 3's module names only, approved by the owner 2026-11-05)

Shared files (`pixi.toml`, `pixi.lock`, `CLAUDE.md`, `AGENTS.md`, `conftest.py`, `README.md`)
may change only if listed above; a needed change to one that is not listed is a stop.

Must not touch:
- manim/, review-loop/, output/ contents other than by the example tasks;
- any hand-calculated expected value in tests (owner ruling, 2026-11-05);
- the numbers the examples print or export (golden check and the three sentinels);
- AGENTS.md rules (station path through _Station, tie order, no global behavior defaults,
  library tests never import examples/), and the builder never preselects a behavior.

## Done check

- `bash .code-health/gate.sh H6` prints: check `EXIT=0` with the previous count passed; examples
  `EXIT=0` with sentinels 3/3 (78.634267, 3.239704, 1.093583); `GOLDEN=MATCH`;
  coverage at least 98.2%; mass at most 109 (12.1 per 1,000 statements); every bench line
  PASS (run 5.333 s and 404 MB, compare 1.396 s and 192 MB, dashboard 5.597 s and 303 MB).
- Mutation sample: `bash .code-health/mutation.sh H6 <scratch>` scores at least station 423/473 (89.4%), engine 738/826 (89.3%), and results metrics 745/807 (92.3%), or, where the mutant count changes, at least the same percentage.
- No hand-calculated expected value changes: every changed line under tests/ in
  `git diff 02c98d9 -- tests` is read by hand before commit.
- One Codex adversarial review of the chunk, findings verified and dispositioned under Result.
- `grep -nE '^ +(from|import) flowsim' flowsim/results.py` prints nothing (no function-level FlowSim imports).
- results.py is under 2,000 lines (from 3,213).
- The import-policing test asserts dependency direction (catalog and records import no other FlowSim module except validation) instead of listing the workaround.

## Approach

Move code without changing expressions. catalog.py: Metric, the window constants, METRICS built from keyword Metric(...) entries, COLUMNS, EXCLUDED, metrics(), explain(), metric_error, unknown, inapplicable, and one SCOPES mapping that replaces _SCOPE_TABLES, _SCOPE_LABELS, and the per-scope dicts in reporting. records.py: the schemas, the slotted record dataclasses, and _frame. Keep `flowsim.results` re-exporting nothing old; update every import. flowsim.metrics and flowsim.explain stay public from the package. Opus does this chunk.

## Stop and ask

Beyond the standing list: any change to a simulation number, any golden mismatch that a
rename map entry cannot explain, and any test removal not named in this brief. An import cycle that the move cannot break without changing behavior is a stop.

## Progress

## Result
