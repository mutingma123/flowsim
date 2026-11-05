# H5 Reuse one browser per engine

**Status: done 2026-11-05.**
Depends on: H2 (run order, to keep one tree)
Branch: health-2.0 (owner ruling, 2026-11-05: chunks commit on health-2.0, which is pushed;
main is not merged or fast-forwarded until the owner approves the 2.0 release)

## Goal

Browser tests launch Chromium and Firefox once per test session and give each test a fresh context with the same offline routes and page-error check, instead of launching a browser per test (44 s of the 205.7 s quiet suite is setup and teardown). The builder's ruff format check fails instead of silently skipping when ruff is missing. Serves chunk H5 (Codex F19, Reader 5 finding 10, Reader 4 finding 5).

## Read first

- tests/conftest.py (offline_pages, offline_page, engine_page).
- tests/test_builder.py:158-176 (run_script).
- AGENTS.md (via CLAUDE.md) and .code-health/scan-2026-11-05.md for the evidence.

## Scope

May change:
- tests/conftest.py
- tests/test_builder.py

Shared files (`pixi.toml`, `pixi.lock`, `CLAUDE.md`, `AGENTS.md`, `conftest.py`, `README.md`)
may change only if listed above; a needed change to one that is not listed is a stop.

Must not touch:
- manim/, review-loop/, output/ contents other than by the example tasks;
- any hand-calculated expected value in tests (owner ruling, 2026-11-05);
- the numbers the examples print or export (golden check and the three sentinels);
- AGENTS.md rules (station path through _Station, tie order, no global behavior defaults,
  library tests never import examples/), and the builder never preselects a behavior.

## Done check

- `bash .code-health/gate.sh H5` prints: check `EXIT=0` with the previous count passed; examples
  `EXIT=0` with sentinels 3/3 (78.634267, 3.239704, 1.093583); `GOLDEN=MATCH`;
  coverage at least 98.2%; mass at most 109 (12.1 per 1,000 statements); every bench line
  PASS (run 5.333 s and 404 MB, compare 1.396 s and 192 MB, dashboard 5.597 s and 303 MB).
- Mutation sample: not rerun, since the chunk changes neither station.py, engine.py, results.py, nor any test the sample runs (conftest's browser fixtures are skipped there).
- No hand-calculated expected value changes: every changed line under tests/ in
  `git diff 02c98d9 -- tests` is read by hand before commit.
- One Codex adversarial review of the chunk, findings verified and dispositioned under Result.
- The pytest summary in the check log is at least 30 s faster than the 276 s phase-1 check gate (logs/2026-11-05-1048-gate-check-phase1.log), or the quiet `pytest --durations=0` total is at least 30 s below 205.7 s.

## Approach

A session-scoped fixture per engine starts sync_playwright and launches the browser once (same executable rules, same skips). The function-scoped fixtures open a new context per test, route http and https to abort, collect page errors, close the context, and assert no errors. Keep both fixture names and signatures so no test changes. In run_script, call pytest.fail when ruff is not found.

## Stop and ask

Beyond the standing list: any change to a simulation number, any golden mismatch that a
rename map entry cannot explain, and any test removal not named in this brief.

## Progress

- baseline: 487 passed @ 9ae5c76, suite 218.0 s inside the H2 gate.
- first gates (logs/2026-11-05-1159-gate-*-H5.log): all passed, suite 152.2 s.
- after the review fix (logs/2026-11-05-1204-gate-*-H5.log): check EXIT=0, 487 passed in
  155.1 s; examples EXIT=0, sentinels 3/3; GOLDEN=MATCH; coverage 98.2%; mass 109 (12.0);
  bench run 4.389 s, compare 1.159 s, dashboard 4.938 s, all inside their bands.
- mutation: not rerun; the sample skips the browser fixtures, and run_script serves only
  browser tests.

## Result

tests/conftest.py launches each engine's browser once per session, on first use, and gives
each test a fresh context with the offline routes and the page-error check; fixture names and
behavior are unchanged, so no test changed. The two browser test files fell from 224.8 s to
136.9 s in the implementer's run, and the suite inside the gate from 218.0 s to 155.1 s
(closure: at least 30 s faster). run_script now fails when ruff is missing instead of skipping
the formatting check. One behavior difference: pages opened within one test now share that
test's context, where each page had its own; all 72 browser tests pass that way.

Codex adversarial review (streams/reviews/H5-codex.md), one medium finding, accepted after
checking the code: a crashed browser stayed cached, so every later test in that engine would
fail. Fixed: a cached browser is reused only while is_connected(), otherwise replaced. A
temporary probe closed the cached Chromium and confirmed the next request launched a working
one; it was deleted afterward. Codex's proposed permanent regression test was not added, since
it would launch an extra browser in every suite run to test the test harness.
