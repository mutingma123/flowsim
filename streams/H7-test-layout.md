# H7 Test layout and shared fixtures

**Status: done 2026-11-05.**
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

- baseline: 497 passed @ 4105bc5
- moves made by a line-range script, not a subagent, so moved bodies are byte-identical: an AST
  comparison against HEAD found 85 of 94 functions identical; the other nine are the intended
  setup swaps (five compare() calls to queue_comparison, three to drained_comparison, one to the
  opened fixture) and the split test.
- first gates (logs/2026-11-05-1331-gate-*-H7.log, .code-health/gate-H7-first.txt): check EXIT=0,
  499 passed in 264.1 s (mutation sample running alongside); examples EXIT=0, sentinels 3/3;
  GOLDEN=MATCH; coverage 98.2%; mass 103 (11.3); bench against the baseline commit: run 0.869,
  compare 0.958, dashboard 1.017.
- mutation (logs/2026-11-05-1331-mutation-H7-*.log): station 430/480, engine 738/826, results
  metrics 745/807, unchanged.
- ST1 on tests/test_reporting.py: `run.py --file tests/test_reporting.py --rule ST1 --expect-none`
  exits 0; the file is 754 lines (from 1,444).
- after the review fix (logs/2026-11-05-1342-gate-*-H7.log): examples EXIT=0, sentinels 3/3;
  GOLDEN=MATCH; coverage 98.2%; mass 103 (11.3); bench run 0.897, compare 0.928, dashboard 0.961.
  Check EXIT=1, 1 failed and 498 passed: test_builder::test_builder_refuses_new_fields_the_page_
  would_not_write[chromium], a race in that test (see Result). The coverage run in the same gate
  passed the full suite. Rerun of the check on the same tree
  (logs/2026-11-05-1350-gate-check-H7-rerun.log): EXIT=0, 499 passed in 177.8 s.
  Mutation not rerun after the fix, which only adds assertions about viewer files.

## Result

tests/test_reporting.py (1,444 lines) is now test_reporting.py (754), test_diagram.py (diagram
tests, with marked, chain_nodes, and arrows defined at the top), and test_dashboard.py (the five
dashboard-page tests). producing_factory and one_stage_chain moved to tests/models.py beside a
new queue_comparison(replications, keep_records) factory, which replaces five identical
One/Two deterministic_queue compare() calls (duration 7, the same arguments as before).
test_service_day.py has one module-scoped drained_comparison used by the three tests that only
read it; test_comparison_rejects_missing_duplicate_and_unpaired_replications and
test_comparison_outputs_accept_a_baseline_and_read_current_tables edit run.summary or settings,
so they keep their own builds. test_unsaved_pages_open_from_one_file_per_kind_in_output is split
into itself plus test_a_second_unsaved_page_of_a_kind_replaces_the_first_file and
test_an_unsaved_page_path_names_its_file_after_the_directory_changes, sharing an opened fixture
(which also replaces test_saved_page_opens_from_its_saved_path's copy of the same setup); the
manual teardown is gone. 497 to 499 tests. Mass 106 to 103: the ST1 long-file finding on
test_reporting.py (checked, expect-none exits 0), the DUP3 pair between test_catalog and the
dashboard request test (checked, gone from static-H7.txt), and one CX1 decision outside the 20
listed (inferred to be the split test). Not changed: tests/test_viewer_browser.py, whose two
repeated comparisons use other scenario names and duration 3, so queue_comparison does not fit.

Codex adversarial review (streams/reviews/H7-codex.md), two medium findings, both accepted after
comparing with HEAD's test:
- The directory-change part opened a fresh viewer once, while HEAD reopened the same viewer
  after an earlier open, so a viewer that kept its first path would have passed. The test now
  opens the viewer in tmp_path first, then reopens it elsewhere.
- HEAD checked the complete file list after the replacement; the split checked it only before.
  The replacement test now asserts output/flowsim-results.html is the only file.

Found in flight, not fixed (outside Scope): test_builder.py:394-404 refuse_file waits for
"Could not load bad.json", which the previous refusal's status already shows, so the next
assertion can read the old message before the page reads the new file. It failed once in the
second gate run. Proposed fix: name each refused file uniquely (bad-1.json, bad-2.json, ...) and
wait for "Could not load <that name>"; it changes no expected message.
