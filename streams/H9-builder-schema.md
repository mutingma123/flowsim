# H9 Builder schema without eval

**Status: done 2026-11-05.**
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

- baseline: 499 passed @ ba79be6
- edit by a Sonnet subagent to an exact spec, reviewed by hand. The new test fails without the
  _call_keywords change (ValueError: malformed node or string) and passes with it.
- schema(): JSON of flowsim.builder_page.schema() (sorted keys) is byte-equal before and after.
  `grep -n 'eval(' flowsim/builder_page.py` prints only the literal_eval line.
- gates (logs/2026-11-05-1355-gate-*-H9.log): check EXIT=0, 500 passed in 259.2 s (mutation
  sample running alongside); examples EXIT=0, sentinels 3/3; GOLDEN=MATCH; coverage 98.2%;
  mass 103 (11.3); bench against the baseline commit: run 0.795, compare 0.900, dashboard 1.003.
- mutation (logs/2026-11-05-1355-mutation-H9-*.log, run because the chunk changes
  tests/test_builder.py): station 430/480, engine 738/826, results metrics 745/807, unchanged.

## Result

builder_page reads every annotation through inspect.signature(..., eval_str=True); _annotation
and both eval calls are gone. _call_keywords keeps a docstring example's literal keywords and
skips a **mapping or any value literal_eval rejects (ValueError or TypeError), so a NumPy call
in an example no longer makes schema() or builder() raise. New test:
test_a_docstring_example_skips_a_keyword_that_is_not_a_literal. A skipped keyword leaves its
field blank, as an absent one does, so the page still prefills nothing it did not before.

Codex adversarial review (streams/reviews/H9-codex.md): approve, no findings. Its one next step,
the byte-equal schema comparison, was already run (above).

Metrics: no metric moved beyond noise (mass 103 as at H7; the run bench ratio reflects H1's
engine change, since this chunk touches no simulation code), so this chunk counts as one that
improves no metric for the loop's stop rule.
