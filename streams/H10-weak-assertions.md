# H10 Strengthen vacuous and weak assertions

**Status: done 2026-11-05.**
Depends on: H8 (run order, to keep one tree)
Branch: health-2.0 (owner ruling, 2026-11-05: chunks commit on health-2.0, which is pushed;
main is not merged or fast-forwarded until the owner approves the 2.0 release)

## Goal

Assertions that cannot fail or barely check anything assert the real value. Serves chunk H10 (Reader 5 finding 13, Reader 4 finding 12, Codex F26). Removes no test.

## Read first

- tests/test_service_day.py:700-720
- tests/test_examples.py:240-252
- tests/test_production.py:240-252
- tests/test_reporting.py (stationless viewer)
- tests/test_fitting.py:335-342
- tests/test_display.py:140-152
- tests/test_distributions.py (lognormal _sigma)
- AGENTS.md (via CLAUDE.md) and .code-health/scan-2026-11-05.md for the evidence.

## Scope

May change:
- tests/test_service_day.py
- tests/test_examples.py
- tests/test_production.py
- tests/test_reporting.py
- tests/test_dashboard.py
- tests/test_fitting.py
- tests/test_display.py
- tests/test_distributions.py
- tests/test_extensions.py

Shared files (`pixi.toml`, `pixi.lock`, `CLAUDE.md`, `AGENTS.md`, `conftest.py`, `README.md`)
may change only if listed above; a needed change to one that is not listed is a stop.

Must not touch:
- manim/, review-loop/, output/ contents other than by the example tasks;
- any hand-calculated expected value in tests (owner ruling, 2026-11-05);
- the numbers the examples print or export (golden check and the three sentinels);
- AGENTS.md rules (station path through _Station, tie order, no global behavior defaults,
  library tests never import examples/), and the builder never preselects a behavior.

## Done check

- `bash .code-health/gate.sh H10` prints: check `EXIT=0` with the previous count passed; examples
  `EXIT=0` with sentinels 3/3 (78.634267, 3.239704, 1.093583); `GOLDEN=MATCH`;
  coverage at least 98.2%; mass at most 109 (12.1 per 1,000 statements); every bench line
  PASS (run 5.333 s and 404 MB, compare 1.396 s and 192 MB, dashboard 5.597 s and 303 MB).
- Mutation sample: `bash .code-health/mutation.sh H10 <scratch>` scores at least station 423/473 (89.4%), engine 738/826 (89.3%), and results metrics 745/807 (92.3%), or, where the mutant count changes, at least the same percentage.
- No hand-calculated expected value changes: every changed line under tests/ in
  `git diff 02c98d9 -- tests` is read by hand before commit.
- One Codex adversarial review of the chunk, findings verified and dispositioned under Result.
- The '95%' check asserts the page's embedded confidence text for 0.95; the `required == 3` line is gone; the 'famil' match names the message; the lognormal test checks `.sd` against its hand value instead of `_sigma`; the mappingproxy match is dropped while TypeError stays.

## Approach

Each change makes an assertion stricter or removes a line that restates the line above; none edits an expected number. Sonnet does this chunk.

## Stop and ask

Beyond the standing list: any change to a simulation number, any golden mismatch that a
rename map entry cannot explain, and any test removal not named in this brief.

## Progress

- baseline: 516 passed @ 383a68c. Run on the owner's ruling (2026-11-05) after the 2.0.1 release.
- edits made inline (five short test changes whose exact text was the spec).
- first gates (logs/2026-11-05-1839-gate-*-H10.log, .code-health/gate-H10-first.txt): all passed,
  516 tests.
- mutation (logs/2026-11-05-1839-mutation-H10-*.log): station 428 killed plus 2 timeouts
  (430/480), engine 763/834, results metrics 742/803, unchanged. Not rerun after the fix, which
  changes only tests/test_distributions.py.
- after the review fix (logs/2026-11-05-1850-gate-*-H10.log): check EXIT=0, 516 passed in 186.4 s;
  examples EXIT=0, sentinels 3/3; GOLDEN=MATCH; coverage 98.2%; mass 103 (11.2); bench run
  0.921, compare 0.933, dashboard 0.939.

## Result

- test_comparison_viewer_prints_a_fractional_confidence_level checks the dashboard's embedded
  confidence_text (97.5%, 95%, 90%) instead of a substring anywhere in the page, which "95%"
  always matched.
- test_worked_exercise_preserves_customer_accounting_and_target_rule no longer asserts
  required == 3 on the line after computing it; the comment keeps the hand calculation.
- test_family_names_are_validated matches each case's own message (one string, an empty list,
  a count family for durations with the discrete=True pointer, an unknown name, a near miss)
  instead of "famil".
- test_lognormal_keeps_a_small_coefficient_of_variation reads sigma through the public call: a
  recording generator captures the sigma passed to rng.lognormal, checked against the same hand
  values (about 1e-9, and sqrt(log 2)). Confirmed it fails when log1p is replaced by log(1 + x).
- test_underscore_names_get_a_plain_error keeps pytest.raises(TypeError) for deepcopy and pickle
  but drops match="mappingproxy", which named an implementation detail.
No test was added, removed, or renamed, and no expected number changed.

The brief's done check said to check .sd against its hand value instead of _sigma. That item
was struck: Lognormal.sd is the stored constructor argument, so the check could never fail. The
first version of this chunk did exactly that, and the Codex adversarial review
(streams/reviews/H10-codex.md, one medium finding, accepted after reading
flowsim/distributions.py:408-424) caught it independently of the session's own check; its
proposed recording generator is the fix above.

Not changed (in Scope, not in the done check): the stationless viewer's "FlowSim" in html check
in test_reporting.py, test_extensions.py:817's one[0] != two[0], and test_production.py's
stock_point list that repeats its argument. Stronger versions need expected values that only a
simulator run would supply, which AGENTS.md asks tests not to rely on alone.
