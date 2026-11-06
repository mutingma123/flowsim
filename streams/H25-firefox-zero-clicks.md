# H25 Clickable zero-valued replication points in Firefox

**Status: done 2026-11-05.**
Depends on: H10 (run order, to keep one tree)
Branch: health-2.0 (owner ruling, 2026-11-05: chunks commit on health-2.0, which is pushed;
main is not merged or fast-forwarded until the owner approves a release)

## Goal

A replication point whose value is zero opens its run when a student clicks its centre in
Firefox. The replication chart's y axis pads below zero, and the browser tests click each
point's centre again instead of its upper quarter. Serves open item 1 of the 2026-11-05 handoff,
run on the owner's order of the same day. Changes no simulation number.

## Read first

- flowsim/reporting.py:513-567 (replication_figure) and flowsim/plots.py:84-97 (style, which
  sets rangemode "tozero" on both axes).
- tests/test_viewer_browser.py:489-500 (click_point and its workaround comment).
- flowsim/dashboard.html:152-189 (draw copies each precomputed figure into Plotly.react).

## Scope

May change:
- flowsim/reporting.py (replication_figure only)
- tests/test_viewer_browser.py (click_point, and one added autoscale test from the review)
- tests/test_reporting.py (added hand-calculated range tests)

Must not touch: anything outside the lines above, the numbers the examples print or export, any
hand-calculated expected value, and the AGENTS.md rules.

## Done check

- `bash .code-health/gate.sh H25` prints check `EXIT=0` with 522 passed (516 plus four range
  tests and one autoscale browser test in two engines); examples `EXIT=0` with sentinels 3/3; `GOLDEN=MATCH` (golden.py skips HTML, so this
  confirms that no CSV or metadata value moved); coverage at least 98.2%; mass at most 109; every
  bench line PASS.
- Mutation sample at or above station 430/480, engine 763/834, results 742/803 (the chunk adds a
  non-browser test).
- The scratch probe (probe_zero.py, below) shows centre hits on the zero-valued Check points in
  both Chromium and Firefox.
- One Codex adversarial review, findings verified and dispositioned under Result.

## Approach

Measured before the edit with probe_zero.py in the session scratchpad: under rangemode "tozero",
the Check station's two zero waits sit on the lower edge of a [0, 1] range, and Firefox missed
both centre clicks while Chromium hit both. Plotly's rangemode "normal" with
autorangeoptions.include = [0] fixed the clicks but drew an all-zero wait axis from -1 to 1 and
moved the top of other ranges (a constant 1 went from [0, 1.08] to [0, 2]), so it was rejected.
The fix sets the y range from the plotted values: from min(0, lowest) to max(0, highest), a span
of 1 when the two are equal, padded by 5% of the span at each end. A chart with no plotted value
keeps Plotly's autorange. The axis's autorangeoptions minallowed and maxallowed hold the same
bounds, so Autoscale and double-click return to the padded range (added after the review).

## Stop and ask

None beyond the standing list.

## Progress

- baseline: 516 passed @ ebc371b (H10 gate, logs/2026-11-05-1850-gate-check-H10.log).
- first version (explicit range only), gates in .code-health/gate-H25-first.txt: check EXIT=0,
  520 passed; examples EXIT=0, sentinels 3/3; GOLDEN=MATCH; coverage 98.2%; mass 103. Bench
  and mutation were stopped by PID once the review finding below changed the code.
- review fix: autorangeoptions bounds and the autoscale browser test. Without the bounds the
  new test fails in both engines (range [0, 1]); with them, 12 selected tests pass.
- final gates (logs/2026-11-05-2032-gate-*-H25.log, .code-health/gate-H25.txt): check EXIT=0,
  522 passed in 182.7 s; examples EXIT=0, sentinels 3/3; GOLDEN=MATCH; coverage 98.2%; mass 103
  (11.2); bench run 0.902, compare 0.930, dashboard 0.946, all PASS; GATE_EXIT=0.
- mutation (logs/2026-11-05-2039-mutation-H25-*.log): station 428 killed plus 2 timeouts
  (430/480), engine 762 killed plus 1 timeout (763/834, 71 survivors as at H10), results 742/803.

## Result

replication_figure sets its y range from the plotted values (min(0, lowest) to max(0, highest),
a span of 1 when equal, padded by 5% at each end) and gives autorangeoptions the same bounds.
click_point clicks each marker's centre again. Added tests: four hand-calculated range cases in
tests/test_reporting.py and test_a_zero_point_still_opens_its_run_after_autoscale in both
engines. No expected number changed, and no test was removed.

Codex adversarial review (streams/reviews/H25-codex.md), one medium finding: Autoscale discards
the explicit range and restores the zero-edge defect. Accepted after a browser probe
(probe_autoscale.py in the session scratchpad): with the explicit range alone, Autoscale and a
second double-click both returned the Check chart to [0, 1], and Firefox missed both zero points
again, while Chromium hit them. Its proposed fix (rangemode "normal" with
autorangeoptions.include = [0]) was rejected: after Autoscale it drew the all-zero Check chart
from -1 to 1 with negative tick labels. Setting autorangeoptions minallowed and maxallowed to the
padded bounds kept [-0.05, 1.05] after both Autoscale and double-click, and every centre click hit
in both engines. Its proposed browser regression was taken as
test_a_zero_point_still_opens_its_run_after_autoscale.

Left open (owner decisions, outside this chunk's scope): the replication chart's x axis shows
fractional ticks (1.2, 1.4) when a run has few replications (proposed: dtick 1 up to 10
replications); and a long y title such as "Mean station waiting time at Check (minutes)" is
taller than the 380-pixel chart, so its first letter is clipped (proposed: a line break before
the units in metric_axis_label for this chart).
Both fixed in H27 on the owner's order of 2026-11-05.
