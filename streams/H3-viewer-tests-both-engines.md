# H3 Every viewer browser test in both engines

**Status: proposed 2026-11-05.**
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

## Result
