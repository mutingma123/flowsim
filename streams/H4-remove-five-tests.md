# H4 Remove tests that cannot fail or duplicate a named test

**Status: proposed 2026-11-05.**
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

## Result
