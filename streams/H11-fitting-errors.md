# H11 Fitting catches only fitting errors

**Status: done 2026-11-05.**
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

- baseline: 500 passed @ 7e6d568
- edit by a Sonnet subagent to an exact spec, reviewed by hand. Before the edit, the fitting,
  README, and display tests raised only _NoFit, ValueError (a gamma solver failure), and
  RuntimeError (the test's injected "bad start") from a family fit (recorded with a pytest
  plugin wrapping _fit_duration and _fit_count). scipy.stats.FitError subclasses RuntimeError
  and numpy.linalg.LinAlgError subclasses ValueError, so both stay caught.
- first gates (logs/2026-11-05-1450-gate-*-H11.log, .code-health/gate-H11-first.txt): check
  EXIT=0, 506 passed; examples EXIT=0, sentinels 3/3; GOLDEN=MATCH; mass 103; bench PASS; but
  coverage 98.1% (98.087%): both "sequence of numbers" branches in _data were uncovered, since
  text now stops at the kind check. Not committed.
- mutation (logs/2026-11-05-1450-mutation-H11-*.log): station 430/480, engine 738/826, results
  metrics 745/807, unchanged. Not rerun after the fix, which changes fitting.py (outside the
  sample) and adds tests.
- after the review fix and the coverage test (logs/2026-11-05-1501-gate-*-H11.log): check
  EXIT=0, 510 passed in 201.8 s; examples EXIT=0, sentinels 3/3; GOLDEN=MATCH; coverage 98.2%
  (98.199%, 3,665 statements, 66 missed; the baseline was 98.226%, 3,608 and 64, and fitting.py
  misses only lines it missed before); mass 103 (11.3); bench run 0.911, compare 0.938,
  dashboard 0.938.
- `grep -n 'except Exception' flowsim/fitting.py` prints nothing.

## Result

fit_all now marks a family as failed only for _NoFit, ValueError, RuntimeError,
FloatingPointError, OverflowError, ZeroDivisionError, and numpy.linalg.LinAlgError; any other
error propagates. _data refuses text and booleans: by dtype kind (only integer, unsigned, float,
and object pass), then item by item for a list, tuple, or object array, so None still reaches
the "only finite numbers" message. The caller's array stays writeable (astype copies). New
tests: test_a_programming_error_in_a_family_fit_is_raised,
test_text_and_boolean_fitting_data_is_refused (7 cases), and
test_fitting_data_that_is_not_a_flat_sequence_of_numbers_is_refused (2 cases, which cover both
"sequence of numbers" branches). No family that fit or failed on the README, example, or test
data now raises (check, examples, and golden all pass). API change: fit_all and best_fit now
raise ValueError for text or boolean data that 1.x converted to floats.

Codex adversarial review (streams/reviews/H11-codex.md), one medium finding, accepted after
checking: np.asarray([True, 2, 4]) is int64, so a mixed boolean and number list passed the kind
check and was fitted as [1, 2, 4]. _data now checks a list's or tuple's items before NumPy's
promotion, and the test has [True, 2.0, 4.0] and (1.5, np.True_, 4.0) cases. Confirmed:
fit_all([True, 2, 4], families=["uniform"]) raises "not text or booleans (got int64 values)".
