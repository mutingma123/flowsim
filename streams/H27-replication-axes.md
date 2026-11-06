# H27 Whole replication ticks and a two-line value title

**Status: done 2026-11-06.**
Depends on: H26 (run order, to keep one tree)
Branch: health-2.0 (owner ruling, 2026-11-05: chunks commit on health-2.0, which is pushed;
main is not merged or fast-forwarded until the owner approves a release)

## Goal

The dashboard's replication chart labels only whole replications when it has 10 or fewer, and
its value axis title puts the units on a second line, so a title such as "Mean station waiting
time at Check (minutes)" fits the 380-pixel chart. Serves the two display items left open in
H25's Result, run on the owner's order of 2026-11-05 (one chunk for both, before a release).
Changes no simulation number.

## Read first

- flowsim/reporting.py:377-384 (metric_axis_label) and 513-580 (replication_figure).
- flowsim/plots.py style, which escapes its labels, so a line break is set after it.

## Scope

May change:
- flowsim/reporting.py (metric_axis_label, one parts helper, replication_figure, whose left
  margin grows from 85 to 95 pixels for the two-line title)
- tests/test_reporting.py (added hand-calculated tests)

Must not touch: the interval charts' titles (the dashboard moves those below narrow charts), the
numbers the examples print or export, any hand-calculated expected value, and the AGENTS.md
rules.

## Done check

- `bash .code-health/gate.sh H27` prints check `EXIT=0` with 529 passed (523 plus six);
  examples `EXIT=0` with sentinels 3/3; `GOLDEN=MATCH`; coverage at least 98.2%; mass at most
  109; every bench line PASS.
- Screenshots of the replication chart in Chromium and Firefox show whole-number ticks and an
  unclipped two-line title for mean_wait at Check, read back as images.
- One Codex adversarial review, findings verified and dispositioned under Result.
- No mutation sample: the chunk touches reporting.py and tests/test_reporting.py only.

## Approach

Owner's accepted proposal (2026-11-05): a tick step of 1 when a chart has 10 or fewer
replications, with Plotly choosing above that, and a line break before the units on this chart
only. A fraction metric has no units, so its title stays on one line.

## Stop and ask

None beyond the standing list.

## Progress

- baseline: 523 passed @ 13749fb (H26 gate, logs/2026-11-05-2100-gate-check-H26.log).
- edit made inline. Browser probe (probe_axes.py in the session scratchpad), mean_wait at Check
  with 2 runs, mean_wait with 12, and utilization at Finishing with 2: every title fits inside
  the chart, at least 18 pixels from its top and bottom and 14 from the tick labels. Ticks
  read 1, 2 at two runs and 2, 4, ..., 12 at twelve. At the old 85-pixel margin the two-line
  title's left edge was 1.25 pixels from the chart's edge in Firefox, so the margin is 95, which
  leaves 11 (Firefox) and 19 (Chromium). Screenshots read back as images.
- gates (logs/2026-11-06-0421-gate-*-H27.log, .code-health/gate-H27.txt): check EXIT=0,
  529 passed in 187.5 s; examples EXIT=0, sentinels 3/3; GOLDEN=MATCH; coverage 98.2%; mass 103
  (11.1); bench run 0.903, compare 0.934, dashboard 0.839, all PASS; GATE_EXIT=0.

## Result

metric_axis_parts returns a metric's axis name (with its location) and its units, or None for a
fraction; metric_axis_label joins them as before, so the interval charts are unchanged.
replication_figure puts the units on a second line, each part escaped, sets a tick step of 1
when its longest scenario has 10 or fewer runs, and has a 95-pixel left margin. Added six
hand-written tests in tests/test_reporting.py (three titles, three tick cases). No expected
number changed, and no test was removed.

Codex adversarial review (streams/reviews/H27-codex.md): approve, no findings. It could not run
the tests or a browser; the gate and the probe above cover both.
