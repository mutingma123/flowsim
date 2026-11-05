# H9 Builder schema without eval

**Status: proposed 2026-11-05.**
Depends on: H7 (run order, to keep one tree)
Branch: health-2.0 (owner ruling, 2026-11-05: chunks commit on health-2.0, which is pushed;
main is not merged or fast-forwarded until the owner approves the 2.0 release)

## Goal

builder_page reads annotations with inspect.signature(..., eval_str=True) instead of eval, and a non-literal docstring example no longer crashes builder(). The schema the page receives is unchanged. Serves chunk H9 (Reader 3 finding 4).

## Read first

- flowsim/builder_page.py
- AGENTS.md (via CLAUDE.md) and .code-health/scan-2026-11-05.md for the evidence.

## Scope

May change:
- flowsim/builder_page.py
- tests/test_builder.py (one new case)

Shared files (`pixi.toml`, `pixi.lock`, `CLAUDE.md`, `AGENTS.md`, `conftest.py`, `README.md`)
may change only if listed above; a needed change to one that is not listed is a stop.

Must not touch:
- manim/, review-loop/, output/ contents other than by the example tasks;
- any hand-calculated expected value in tests (owner ruling, 2026-11-05);
- the numbers the examples print or export (golden check and the three sentinels);
- AGENTS.md rules (station path through _Station, tie order, no global behavior defaults,
  library tests never import examples/), and the builder never preselects a behavior.

## Done check

- `bash .code-health/gate.sh H9` prints: check `EXIT=0` with the previous count plus 1 passed; examples
  `EXIT=0` with sentinels 3/3 (78.634267, 3.239704, 1.093583); `GOLDEN=MATCH`;
  coverage at least 98.2%; mass at most 109 (12.1 per 1,000 statements); every bench line
  PASS (run 5.333 s and 404 MB, compare 1.396 s and 192 MB, dashboard 5.597 s and 303 MB).
- Mutation sample: not rerun, since the chunk changes neither station.py, engine.py, results.py, nor any test the sample runs (it changes builder_page.py only).
- No hand-calculated expected value changes: every changed line under tests/ in
  `git diff 02c98d9 -- tests` is read by hand before commit.
- One Codex adversarial review of the chunk, findings verified and dispositioned under Result.
- `grep -n 'eval(' flowsim/builder_page.py` prints only literal_eval.
- `flowsim.builder_page.schema()` is equal before and after (compare the JSON).

## Approach

Replace both eval calls; in _call_keywords skip keywords whose value is not a literal. Add one test that a docstring example with a non-literal keyword is skipped rather than raising. Sonnet does this chunk.

## Stop and ask

Beyond the standing list: any change to a simulation number, any golden mismatch that a
rename map entry cannot explain, and any test removal not named in this brief.

## Progress

## Result
