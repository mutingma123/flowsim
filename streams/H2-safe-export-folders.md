# H2 Export refuses to clear a folder FlowSim did not write

**Status: done 2026-11-05.**
Depends on: H1 (run order, to keep one tree)
Branch: health-2.0 (owner ruling, 2026-11-05: chunks commit on health-2.0, which is pushed;
main is not merged or fast-forwarded until the owner approves the 2.0 release)

## Goal

export() keeps replacing and clearing its own files on a rerun (owner ruling U25), but raises a ValueError naming the clashing files when the folder holds FlowSim export names and no FlowSim metadata.json, instead of deleting or overwriting a user's own customers.csv or runs.csv. Serves chunk H2 (Reader 2 finding 1, Reader 5 finding 3). API-breaking: a previously silent overwrite now raises.

## Read first

- flowsim/results.py: EXPORT_FILE_NAMES, remove_stale_exports, Results.export.
- flowsim/reporting.py: export_tables (the experiment and comparison exports).
- README.md: the export paragraph (around line 976).
- review-loop/2026-11-04-usability-plan/plan.md lines 44-47 (U25 ruling).
- AGENTS.md (via CLAUDE.md) and .code-health/scan-2026-11-05.md for the evidence.

## Scope

May change:
- flowsim/results.py
- flowsim/reporting.py
- README.md
- tests/test_service_day.py
- tests/test_reporting.py

Shared files (`pixi.toml`, `pixi.lock`, `CLAUDE.md`, `AGENTS.md`, `conftest.py`, `README.md`)
may change only if listed above; a needed change to one that is not listed is a stop.

Must not touch:
- manim/, review-loop/, output/ contents other than by the example tasks;
- any hand-calculated expected value in tests (owner ruling, 2026-11-05);
- the numbers the examples print or export (golden check and the three sentinels);
- AGENTS.md rules (station path through _Station, tie order, no global behavior defaults,
  library tests never import examples/), and the builder never preselects a behavior.

## Done check

- `bash .code-health/gate.sh H2` prints: check `EXIT=0` with 486 (485 plus one new refusal test) passed; examples
  `EXIT=0` with sentinels 3/3 (78.634267, 3.239704, 1.093583); `GOLDEN=MATCH`;
  coverage at least 98.2%; mass at most 109 (12.1 per 1,000 statements); every bench line
  PASS (run 5.333 s and 404 MB, compare 1.396 s and 192 MB, dashboard 5.597 s and 303 MB).
- Mutation sample: `bash .code-health/mutation.sh H2 <scratch>` scores at least station 423/473 (89.4%), engine 738/826 (89.3%), and results metrics 745/807 (92.3%), or, where the mutant count changes, at least the same percentage.
- No hand-calculated expected value changes: every changed line under tests/ in
  `git diff 02c98d9 -- tests` is read by hand before commit.
- One Codex adversarial review of the chunk, findings verified and dispositioned under Result.
- New test: a folder holding a user's customers.csv and no metadata.json makes export raise a ValueError naming customers.csv, and the file is unchanged.

## Approach

One helper checks the destination before any write: the folder is FlowSim's when it is empty of export names, or when its metadata.json parses and has a flowsim_version key. Otherwise raise, naming the clashing files and asking for an empty or FlowSim-written folder. Call it from Results.export and export_tables. The existing stale-file tests export into folders FlowSim wrote first; if one seeds a stale FlowSim name before any export, seed a FlowSim metadata.json too and note it.

## Stop and ask

Beyond the standing list: any change to a simulation number, any golden mismatch that a
rename map entry cannot explain, and any test removal not named in this brief.

## Progress

- baseline: 485 passed @ dcc4937
- first gates (logs/2026-11-05-1137-gate-*-H2.log): all passed, 486 tests.
- after the review fix (logs/2026-11-05-1143-gate-*-H2.log): check EXIT=0, 487 passed in
  218.0 s; examples EXIT=0, sentinels 3/3; GOLDEN=MATCH; coverage 98.2%; mass 109 (12.1);
  bench run 4.348 s, compare 1.143 s, dashboard 5.017 s, all inside their bands.
- mutation (logs/2026-11-05-1148-mutation-H2-*.log): station 430/480, engine 738/826,
  results metrics 745/807.

## Result

require_flowsim_folder (results.py) runs before any write in Results.export and export_tables.
A folder that holds export-named files counts as FlowSim's only when its metadata.json is a
JSON object with flowsim_version; otherwise the export raises a ValueError naming the files.
FlowSim's own folders keep the U25 behavior (overwrite, remove stale FlowSim files). New tests:
test_export_refuses_folder_with_files_flowsim_did_not_write and
test_an_interrupted_export_can_be_retried. One test's setup changed:
test_experiment_export_writes_pooled_tables_and_metadata seeds a FlowSim metadata.json, since
its folder stands for an earlier export; no asserted value changed. README's export paragraph
says what the refusal does.

Codex adversarial review (streams/reviews/H2-codex.md), one medium finding, accepted after
checking the code: Results.export wrote its tables before metadata.json and write_text is not
atomic, so an interrupted export would leave FlowSim's files unmarked and the guard would
refuse every retry. Fixed: Results.export writes metadata first (as export_tables already
did), _write_metadata writes metadata.json.partial and renames it over the old file, and the
message says FlowSim cannot tell whether it wrote the files. The retry test fails on the old
write order and passes on the new one. Codex's rejected alternative, accepting unmarked files,
was also rejected, since it restores the overwrite risk.
