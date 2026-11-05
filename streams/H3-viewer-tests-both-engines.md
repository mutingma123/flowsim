# H3 Every viewer browser test in both engines

**Status: done 2026-11-05.**
Depends on: H5 (run order, to keep one tree)
Branch: health-2.0 (owner ruling, 2026-11-05: chunks commit on health-2.0, which is pushed;
main is not merged or fast-forwarded until the owner approves the 2.0 release)

## Goal

All 16 viewer tests in tests/test_viewer_browser.py run in Chromium and Firefox, as the owner's two-engine ruling intends, and the Chromium-only offline_page fixture is gone. Serves chunk H3 (Readers 4 and 5). Adds 13 Firefox test runs.

## Read first

- tests/conftest.py
- tests/test_viewer_browser.py
- AGENTS.md (via CLAUDE.md) and .code-health/scan-2026-11-05.md for the evidence.

## Scope

May change:
- tests/conftest.py
- tests/test_viewer_browser.py

Shared files (`pixi.toml`, `pixi.lock`, `CLAUDE.md`, `AGENTS.md`, `conftest.py`, `README.md`)
may change only if listed above; a needed change to one that is not listed is a stop.

Must not touch:
- manim/, review-loop/, output/ contents other than by the example tasks;
- any hand-calculated expected value in tests (owner ruling, 2026-11-05);
- the numbers the examples print or export (golden check and the three sentinels);
- AGENTS.md rules (station path through _Station, tie order, no global behavior defaults,
  library tests never import examples/), and the builder never preselects a behavior.

## Done check

- `bash .code-health/gate.sh H3` prints: check `EXIT=0` with 499 (486 plus 13 Firefox runs) passed; examples
  `EXIT=0` with sentinels 3/3 (78.634267, 3.239704, 1.093583); `GOLDEN=MATCH`;
  coverage at least 98.2%; mass at most 109 (12.1 per 1,000 statements); every bench line
  PASS (run 5.333 s and 404 MB, compare 1.396 s and 192 MB, dashboard 5.597 s and 303 MB).
- Mutation sample: not rerun, since the chunk changes neither station.py, engine.py, results.py, nor any test the sample runs (browser tests are skipped there).
- No hand-calculated expected value changes: every changed line under tests/ in
  `git diff 02c98d9 -- tests` is read by hand before commit.
- One Codex adversarial review of the chunk, findings verified and dispositioned under Result.
- `grep -c offline_page tests/*.py` prints 0 for every file.

## Approach

Switch each offline_page test to engine_page and delete offline_page. A test that fails only in Firefox is a real page defect or a timing assumption: fix the page only if the fix is plainly right, otherwise stop and report the failing case.

## Stop and ask

Beyond the standing list: any change to a simulation number, any golden mismatch that a
rename map entry cannot explain, and any test removal not named in this brief. A Firefox-only failure whose fix would change a page's behavior is a stop.

## Progress

- baseline: 487 passed @ 334134d
- gates (logs/2026-11-05-1217-gate-*-H3.log): check EXIT=0, 502 passed in 186.5 s (15 Firefox
  runs added: 13 tests, one parametrized over drain); examples EXIT=0, sentinels 3/3;
  GOLDEN=MATCH; coverage 98.2%; mass 109 (12.0).
- bench: the absolute band failed for the dashboard (5.616 s, then 5.684 s, against 5.597 s)
  with load average 49 to 53 from other projects' jobs; the benchmarked code is identical to
  334134d (`git diff --stat 334134d -- flowsim benchmarks examples` is empty). Interleaved
  against the baseline commit under the same load (logs/2026-11-05-1223-gate-benchab-H3.log,
  EXIT=0): run 0.880, compare 0.910, dashboard 0.998 of baseline, memory within 1.003. From
  here on the gate uses that comparison.
- mutation: not rerun; the sample skips browser tests.

## Result

All 16 viewer tests run in Chromium and Firefox; offline_page is gone and its helper is renamed
saved_pages. One test-side change: click_point clicks a marker's upper quarter instead of its
centre, because a value-0 replication point sits on the bottom edge of the chart's drag layer
and Firefox gives a click at that exact pixel to the SVG container, so Plotly never sees it.

Codex adversarial review (streams/reviews/H3-codex.md), one medium finding: the click change
hides a real Firefox defect, since a student clicking the lower half of a zero-valued point
cannot open its run. Verified in the implementer's Firefox probe (marker centre and drag-layer
edge both at y = 732.6). Accepted as a finding and deferred to the owner: its fix edits
flowsim/reporting.py, outside this chunk's scope. Open question, recommended answer yes:
give replication_figure's y axis padding below zero (rangemode "normal" with a small negative
lower bound for all-zero series), restore centre clicks, and assert the run opened in both
engines. It changes the chart's axis range only, no number.
