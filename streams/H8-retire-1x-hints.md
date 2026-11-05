# H8 Retire the 1.x rename and moved-setting hints

**Status: proposed 2026-11-05.**
Depends on: H13 (run order, to keep one tree)
Branch: health-2.0 (owner ruling, 2026-11-05: chunks commit on health-2.0, which is pushed;
main is not merged or fast-forwarded until the owner approves the 2.0 release)

## Goal

Results, Experiment, and Comparison no longer carry tables of 1.x plot names and moved settings; a missing attribute still gets close-match suggestions and the dropped-records message. Serves chunk H8 (Reader 2 finding 7, Codex F24, Reader 4 API D). API-breaking: old names now get the generic close-match error.

## Read first

- flowsim/results.py (_RENAMED, moved_settings, __getattr__)
- flowsim/comparison.py:80-95
- tests/test_display.py
- AGENTS.md (via CLAUDE.md) and .code-health/scan-2026-11-05.md for the evidence.

## Scope

May change:
- flowsim/results.py
- flowsim/comparison.py
- tests/test_display.py
- README.md (a 2.0 note only, if it mentions the old names)

Shared files (`pixi.toml`, `pixi.lock`, `CLAUDE.md`, `AGENTS.md`, `conftest.py`, `README.md`)
may change only if listed above; a needed change to one that is not listed is a stop.

Must not touch:
- manim/, review-loop/, output/ contents other than by the example tasks;
- any hand-calculated expected value in tests (owner ruling, 2026-11-05);
- the numbers the examples print or export (golden check and the three sentinels);
- AGENTS.md rules (station path through _Station, tie order, no global behavior defaults,
  library tests never import examples/), and the builder never preselects a behavior.

## Done check

- `bash .code-health/gate.sh H8` prints: check `EXIT=0` with the previous count; test cases for the removed hints go with the feature passed; examples
  `EXIT=0` with sentinels 3/3 (78.634267, 3.239704, 1.093583); `GOLDEN=MATCH`;
  coverage at least 98.2%; mass at most 109 (12.1 per 1,000 statements); every bench line
  PASS (run 5.333 s and 404 MB, compare 1.396 s and 192 MB, dashboard 5.597 s and 303 MB).
- Mutation sample: `bash .code-health/mutation.sh H8 <scratch>` scores at least station 423/473 (89.4%), engine 738/826 (89.3%), and results metrics 745/807 (92.3%), or, where the mutant count changes, at least the same percentage.
- No hand-calculated expected value changes: every changed line under tests/ in
  `git diff 02c98d9 -- tests` is read by hand before commit.
- One Codex adversarial review of the chunk, findings verified and dispositioned under Result.
- `grep -nE '_RENAMED|moved_settings' flowsim` prints nothing.

## Approach

Delete the tables and their branches; keep missing_attribute. In test_display, delete only the assertions about removed hints and keep the close-match and settings-hint behavior that remains. Sonnet does this chunk.

## Stop and ask

Beyond the standing list: any change to a simulation number, any golden mismatch that a
rename map entry cannot explain, and any test removal not named in this brief.

## Progress

## Result
