# H16 Column-wise run data and array-backed figures

**Status: done 2026-11-05.**
Depends on: H9 (run order, to keep one tree)
Branch: health-2.0 (owner ruling, 2026-11-05: chunks commit on health-2.0, which is pushed;
main is not merged or fast-forwarded until the owner approves the 2.0 release)

## Goal

Run views receive customers, visits, timeline, failures, and supply tables column by column, and figures carry NumPy arrays so Plotly writes compact data, which makes run pages and dashboards smaller and faster to build. Serves chunk H16 (Reader 3 finding 1); measured one service-day run's data at 281 kB row-wise and 154 kB column-wise. Changes page structure, not numbers.

## Read first

- flowsim/plots.py: service_payload, supply_payload, figure_data, page_json.
- flowsim/service_run.html and flowsim/supply_run.html: table, download, byId, spansById.
- flowsim/dashboard.html: how a run's script element is parsed.
- AGENTS.md (via CLAUDE.md) and .code-health/scan-2026-11-05.md for the evidence.

## Scope

May change:
- flowsim/plots.py
- flowsim/service_run.html
- flowsim/supply_run.html
- flowsim/dashboard.html
- flowsim/run.html
- tests/ (payload readers only)

Shared files (`pixi.toml`, `pixi.lock`, `CLAUDE.md`, `AGENTS.md`, `conftest.py`, `README.md`)
may change only if listed above; a needed change to one that is not listed is a stop.

Must not touch:
- manim/, review-loop/, output/ contents other than by the example tasks;
- any hand-calculated expected value in tests (owner ruling, 2026-11-05);
- the numbers the examples print or export (golden check and the three sentinels);
- AGENTS.md rules (station path through _Station, tie order, no global behavior defaults,
  library tests never import examples/), and the builder never preselects a behavior.

## Done check

- `bash .code-health/gate.sh H16` prints: check `EXIT=0` with the previous count passed; examples
  `EXIT=0` with sentinels 3/3 (78.634267, 3.239704, 1.093583); `GOLDEN=MATCH`;
  coverage at least 98.2%; mass at most 109 (12.1 per 1,000 statements); every bench line
  PASS (run 5.333 s and 404 MB, compare 1.396 s and 192 MB, dashboard 5.597 s and 303 MB).
- Mutation sample: not rerun, since the chunk changes neither station.py, engine.py, results.py, nor any test the sample runs (it changes plots.py and pages only).
- No hand-calculated expected value changes: every changed line under tests/ in
  `git diff 02c98d9 -- tests` is read by hand before commit.
- One Codex adversarial review of the chunk, findings verified and dispositioned under Result.
- The service-day comparison page is at most 16 MB (from 22.6 MB).
- bench dashboard median below 5.088 s.
- Every browser test passes in both engines; CSV downloads keep export column order and null handling.

## Approach

Use frame.to_dict(as_series=False) for embedded tables and one small JavaScript helper that turns columns into row objects where the page needs rows. Pass arrays (to_numpy) instead of lists to Plotly traces built for pages. Opus does this chunk, since the JavaScript and Python must change together.

## Stop and ask

Beyond the standing list: any change to a simulation number, any golden mismatch that a
rename map entry cannot explain, and any test removal not named in this brief.

## Progress

- baseline: 500 passed @ 4dceef6
- edit by an Opus subagent, reviewed by hand. Its checks: payloads of 8 runs (service with and
  without drain, two combined-line runs, repair failures, job shop, beer chain, producing chain)
  decoded back to rows and plain arrays are byte-identical to HEAD's (240 typed arrays); pages
  from HEAD and from the change for 6 runs, including an empty run, give byte-identical CSV
  downloads, chart arrays, and table cells in Chromium and Firefox; 129 output CSV and JSON
  files hash the same. Scratch scripts: dump.py, browser_check.py, measure.py in the session
  scratchpad (not kept).
- first gates (logs/2026-11-05-1429-gate-*-H16.log, .code-health/gate-H16-first.txt): all
  passed, 500 tests; mass 105, from a new B905 finding (zip without strict) in
  tests/models.py:table_rows, fixed by adding strict=True.
- mutation (logs/2026-11-05-1429-mutation-H16-*.log): station 428 killed plus 2 timeouts
  (430/480 counting timeouts as detected), engine 738/826, results metrics 745/807. Not rerun
  after the strict=True fix, which changes only a test reader.
- after the fix (logs/2026-11-05-1440-gate-*-H16.log): check EXIT=0, 500 passed in 190.9 s;
  examples EXIT=0, sentinels 3/3; GOLDEN=MATCH; coverage 98.2%; mass 103 (11.3); bench against
  the baseline commit: run 0.916, compare 0.935, dashboard 0.928 with memory 0.892.
- service-day comparison page: 22,602,556 to 14,083,042 bytes (output/service-day/comparison.html).
  One service-day run page: 5,110,905 to 4,985,080 bytes; its embedded data about 263 kB to 137 kB.

## Result

service_payload and supply_payload embed every record table with to_dict(as_series=False);
summary stays one row object. service_run.html defines tableRows(columns), which both run views
use to rebuild, once per view, the rows they read (every page holds both views); downloads read
the columns directly with the same quoting and export column order. plots.trace_values gives a
trace a NumPy array only while a page is built (the existing _BUILDING_PAGE flag), so Plotly
writes base64 typed arrays; a column with a null or NaN stays a list, and the figures plot_*
returns to users still hold lists. The one test change is a reader: tests/models.py table_rows,
used by test_customer_timeline_spans_feed_the_plot_and_the_viewer, compares the same expected
value. dashboard.html and run.html needed no change.

Done check: the comparison page is 14.1 MB (limit 16 MB), and every browser test passes in both
engines. The line "bench dashboard median below 5.088 s" (9 percent under the quiet-machine
5.597 s) is one of the absolute bench limits the owner's bench-ab ruling supersedes, so it was
read as a ratio of about 0.909 against the baseline commit. Measured ratios are 0.922 and 0.928
in the two gate runs, and the subagent's interleaved timing of comparison.viewer() was 4.903 s
to 4.626 s (5.6 percent). That target is therefore not met; it was not treated as a gate, which
is a choice made on the owner's behalf (the alternative was to revert this chunk and mark it
blocked). The remaining time is mostly reporting.metric_entry (7.7 of 11.3 s profiled) and
plots.style (2.5 to 6.7 ms per figure across about 540 figures).

Choices made by the subagent, accepted after review: arrays are set where traces are built,
not converted in page_figure, because assigning an array to an existing trace stores a list
(checked by the subagent: type(trace._props["x"]) is list), so page_figure would have to rebuild
every figure; downloads read columns rather than rebuilt visit rows; one tableRows in
service_run.html rather than a copy per view or a new file (which would need a package-data
change outside Scope).

Codex adversarial review (streams/reviews/H16-codex.md): approve, no findings. Its next steps
(both-engine browser suite, decoded chart values against the baseline) are the gate's check and
the subagent's 8-run and 6-page comparisons above.

Proposed, not done (owner decisions):
- Dashboard build time: in plots.style, assign a fresh go.Layout instead of update_layout
  (0.85 ms against 2.46 ms per figure in the subagent's scratch test, identical layout JSON),
  about 0.9 s over 540 figures. It must merge with layout set earlier (station_menu's
  updatemenus), so it is its own refactor.
- The dashboard's own figures (reporting.replication_figure and interval_figure) still embed
  lists; compacting them needs reporting.py, outside Scope, and is estimated (not measured) to
  save well under 0.6 MB of the 649 kB dashboard data. Recommended: skip.
