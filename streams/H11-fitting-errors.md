# H11 Fitting catches only fitting errors

**Status: proposed 2026-11-05.**
Depends on: H16 (run order, to keep one tree)
Branch: health-2.0 (owner ruling, 2026-11-05: chunks commit on health-2.0, which is pushed;
main is not merged or fast-forwarded until the owner approves the 2.0 release)

## Goal

fit_all records a family as failed only for errors a SciPy fit raises on bad data, so a programming error surfaces, and fitting data that is text or booleans is refused with a message. Serves chunk H11 (Reader 3 findings 6 and 13).

## Read first

- flowsim/fitting.py:540-650 and :820-860
- tests/test_fitting.py
- AGENTS.md (via CLAUDE.md) and .code-health/scan-2026-11-05.md for the evidence.

## Scope

May change:
- flowsim/fitting.py
- tests/test_fitting.py

Shared files (`pixi.toml`, `pixi.lock`, `CLAUDE.md`, `AGENTS.md`, `conftest.py`, `README.md`)
may change only if listed above; a needed change to one that is not listed is a stop.

Must not touch:
- manim/, review-loop/, output/ contents other than by the example tasks;
- any hand-calculated expected value in tests (owner ruling, 2026-11-05);
- the numbers the examples print or export (golden check and the three sentinels);
- AGENTS.md rules (station path through _Station, tie order, no global behavior defaults,
  library tests never import examples/), and the builder never preselects a behavior.

## Done check

- `bash .code-health/gate.sh H11` prints: check `EXIT=0` with the previous count plus any new validation cases passed; examples
  `EXIT=0` with sentinels 3/3 (78.634267, 3.239704, 1.093583); `GOLDEN=MATCH`;
  coverage at least 98.2%; mass at most 109 (12.1 per 1,000 statements); every bench line
  PASS (run 5.333 s and 404 MB, compare 1.396 s and 192 MB, dashboard 5.597 s and 303 MB).
- Mutation sample: not rerun, since the chunk changes neither station.py, engine.py, results.py, nor any test the sample runs (it changes fitting.py only).
- No hand-calculated expected value changes: every changed line under tests/ in
  `git diff 02c98d9 -- tests` is read by hand before commit.
- One Codex adversarial review of the chunk, findings verified and dispositioned under Result.
- `grep -n 'except Exception' flowsim/fitting.py` prints nothing.

## Approach

Catch _NoFit, ValueError, RuntimeError, FloatingPointError, OverflowError, ZeroDivisionError, and numpy.linalg.LinAlgError; run test_fitting and the README fit examples to confirm no family that failed before now raises. Check the array dtype kind is integer, unsigned, or float before converting. Sonnet does this chunk.

## Stop and ask

Beyond the standing list: any change to a simulation number, any golden mismatch that a
rename map entry cannot explain, and any test removal not named in this brief. A family that now raises on the README or test data is a stop.

## Progress

## Result
