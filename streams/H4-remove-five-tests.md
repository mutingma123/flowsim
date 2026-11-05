# H4 Remove tests that cannot fail or duplicate a named test

**Status: done 2026-11-05.**
Depends on: H6 (run order, to keep one tree)
Branch: health-2.0 (owner ruling, 2026-11-05: chunks commit on health-2.0, which is pushed;
main is not merged or fast-forwarded until the owner approves the 2.0 release)

## Goal

Five test ids the owner approved for removal are gone, and the one unique assertion among them is kept in another test. Serves chunk H4; evidence in .code-health/scan-2026-11-05.md, Test evidence. Saves about 2.5 s.

## Read first

- .code-health/scan-2026-11-05.md, section Test evidence.
- AGENTS.md (via CLAUDE.md) and .code-health/scan-2026-11-05.md for the evidence.

## Scope

May change:
- tests/test_inventory.py
- tests/test_builder.py
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

- `bash .code-health/gate.sh H4` prints: check `EXIT=0` with the previous count minus 5 passed; examples
  `EXIT=0` with sentinels 3/3 (78.634267, 3.239704, 1.093583); `GOLDEN=MATCH`;
  coverage at least 98.2%; mass at most 109 (12.1 per 1,000 statements); every bench line
  PASS (run 5.333 s and 404 MB, compare 1.396 s and 192 MB, dashboard 5.597 s and 303 MB).
- Mutation sample: `bash .code-health/mutation.sh H4 <scratch>` scores at least station 423/473 (89.4%), engine 738/826 (89.3%), and results metrics 745/807 (92.3%), or, where the mutant count changes, at least the same percentage.
- No hand-calculated expected value changes: every changed line under tests/ in
  `git diff 02c98d9 -- tests` is read by hand before commit.
- One Codex adversarial review of the chunk, findings verified and dispositioned under Result.
- Removed exactly: test_inventory::test_policies_are_part_of_the_public_package; test_builder::test_builder_with_a_path_writes_the_page; test_reporting::test_compare_passes_keep_records_to_each_scenario; test_builder::test_builder_edits_every_station_and_source_argument[chromium] and [firefox].
- test_schema_reads_model_arguments_from_their_signatures asserts `set(data['supported'][kind]) == set(names)`, and test_builder_builds_and_edits_a_model_from_the_keyboard asserts `#excluded-arguments` is empty.

## Approach

Delete the four functions; tighten `<=` to `==` in the schema test; add the excluded-arguments assertion right after the keyboard test opens the builder. Remove imports left unused. Sonnet does this chunk.

## Stop and ask

Beyond the standing list: any change to a simulation number, any golden mismatch that a
rename map entry cannot explain, and any test removal not named in this brief.

## Progress

- baseline: 502 passed @ fbfc410
- first gates (logs/2026-11-05-1301-gate-*-H4.log): all passed, 497 tests.
- mutation (logs/2026-11-05-1308-mutation-H4-*.log, before the review fix, which only adds an
  assertion): station 430/480, engine 738/826, results metrics 745/807, unchanged, so the
  removed tests killed no mutant that no other test kills.
- after the review fix (logs/2026-11-05-1318-gate-*-H4.log): check EXIT=0, 497 passed in
  183.4 s; examples EXIT=0, sentinels 3/3; GOLDEN=MATCH; coverage 98.2%; mass 106 (11.7);
  bench against the baseline commit: run 0.957, compare 0.887, dashboard 0.988.

## Result

Removed five test ids: test_inventory::test_policies_are_part_of_the_public_package (cannot
fail), test_builder::test_builder_with_a_path_writes_the_page (every builder browser test
writes the page through open_builder), test_reporting::test_compare_passes_keep_records_to_
each_scenario, and test_builder::test_builder_edits_every_station_and_source_argument in both
engines. Kept assertions: test_schema_reads_model_arguments_from_their_signatures now asserts
the supported argument list equals the signature (was a subset), and
test_builder_builds_and_edits_a_model_from_the_keyboard asserts #excluded-arguments is empty.

Codex adversarial review (streams/reviews/H4-codex.md), one medium finding, accepted after
checking reporting.py:766: the dashboard's records flag is all(...) over every run, so the
remaining dashboard test proved only that some run dropped its records, not every run in every
scenario. The removed test's per-run loop now sits in
test_dashboard_without_records_holds_no_runs, so no check is lost and the removed test id
stays removed. The evidence in the scan called that test a full duplicate; that was half
right, and this finding corrects it.

Also recorded here: H6's mass line was corrected (its scan left out the then-untracked
catalog.py and records.py; the true value is 106).
