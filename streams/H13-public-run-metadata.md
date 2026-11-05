# H13 Public run metadata instead of private reach-in

**Status: proposed 2026-11-05.**
Depends on: H11 (run order, to keep one tree)
Branch: health-2.0 (owner ruling, 2026-11-05: chunks commit on health-2.0, which is pushed;
main is not merged or fast-forwarded until the owner approves the 2.0 release)

## Goal

Results exposes `supply` (a frozen SupplySettings or None), `stock_point_names`, and `records_kept`; plots, reporting, Experiment, and tests read these instead of _supply, _definitions keys, _records_kept, and _capacities (settings.capacities replaces the last). Serves chunk H13 (Reader 1 finding 3 in part, Reader 2 finding 10, Reader 3 finding 3, Reader 5 finding 7). API-breaking: adds public names, removes private ones.

## Read first

- flowsim/results.py (Results constructor, export)
- flowsim/plots.py
- flowsim/reporting.py
- flowsim/engine.py:600-720
- AGENTS.md (via CLAUDE.md) and .code-health/scan-2026-11-05.md for the evidence.

## Scope

May change:
- flowsim/results.py
- flowsim/plots.py
- flowsim/reporting.py
- flowsim/engine.py
- flowsim/comparison.py
- README.md (Results attributes)
- tests/ (private reads replaced by public ones)

Shared files (`pixi.toml`, `pixi.lock`, `CLAUDE.md`, `AGENTS.md`, `conftest.py`, `README.md`)
may change only if listed above; a needed change to one that is not listed is a stop.

Must not touch:
- manim/, review-loop/, output/ contents other than by the example tasks;
- any hand-calculated expected value in tests (owner ruling, 2026-11-05);
- the numbers the examples print or export (golden check and the three sentinels);
- AGENTS.md rules (station path through _Station, tie order, no global behavior defaults,
  library tests never import examples/), and the builder never preselects a behavior.

## Done check

- `bash .code-health/gate.sh H13` prints: check `EXIT=0` with the previous count passed; examples
  `EXIT=0` with sentinels 3/3 (78.634267, 3.239704, 1.093583); `GOLDEN=MATCH`;
  coverage at least 98.2%; mass at most 109 (12.1 per 1,000 statements); every bench line
  PASS (run 5.333 s and 404 MB, compare 1.396 s and 192 MB, dashboard 5.597 s and 303 MB).
- Mutation sample: `bash .code-health/mutation.sh H13 <scratch>` scores at least station 423/473 (89.4%), engine 738/826 (89.3%), and results metrics 745/807 (92.3%), or, where the mutant count changes, at least the same percentage.
- No hand-calculated expected value changes: every changed line under tests/ in
  `git diff 02c98d9 -- tests` is read by hand before commit.
- One Codex adversarial review of the chunk, findings verified and dispositioned under Result.
- `grep -rnE '\._(supply|records_kept|capacities)\b' flowsim tests` prints nothing outside results.py's own definitions.
- metadata.json bytes are unchanged (golden).

## Approach

Add the public names first, switch every reader, then delete the private ones. Keep the export JSON keys. The stock-point-names one-liner exists three times; keep one. Opus does this chunk.

## Stop and ask

Beyond the standing list: any change to a simulation number, any golden mismatch that a
rename map entry cannot explain, and any test removal not named in this brief.

## Progress

## Result
