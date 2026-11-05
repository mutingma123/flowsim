# H16 Column-wise run data and array-backed figures

**Status: proposed 2026-11-05.**
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

## Result
