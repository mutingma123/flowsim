# H1 Engine event overhead

**Status: proposed 2026-11-05.**
Depends on: none
Branch: health-2.0 (owner ruling, 2026-11-05: chunks commit on health-2.0, which is pushed;
main is not merged or fast-forwarded until the owner approves the 2.0 release)

## Goal

The engine stops queueing change events nobody waits on, stops recording a second state row at the same instant in admit(), and stops recording zero-length BLOCKED activity rows, so a long run is faster with identical records. Serves code-health chunk H1 (scan 2026-11-05, Reader 1 findings 1, 2, and 8).

## Read first

- flowsim/scheduler.py: how step() pops events and runs callbacks.
- flowsim/station.py:60-140 (pulse, set_phase, count_down) and :245-310 (state, admit).
- flowsim/engine.py:280-300 (observe) and :670-690 (the zero-length activity filter).
- AGENTS.md (via CLAUDE.md) and .code-health/scan-2026-11-05.md for the evidence.

## Scope

May change:
- flowsim/station.py
- flowsim/engine.py

Shared files (`pixi.toml`, `pixi.lock`, `CLAUDE.md`, `AGENTS.md`, `conftest.py`, `README.md`)
may change only if listed above; a needed change to one that is not listed is a stop.

Must not touch:
- manim/, review-loop/, output/ contents other than by the example tasks;
- any hand-calculated expected value in tests (owner ruling, 2026-11-05);
- the numbers the examples print or export (golden check and the three sentinels);
- AGENTS.md rules (station path through _Station, tie order, no global behavior defaults,
  library tests never import examples/), and the builder never preselects a behavior.

## Done check

- `bash .code-health/gate.sh H1` prints: check `EXIT=0` with 485 passed; examples
  `EXIT=0` with sentinels 3/3 (78.634267, 3.239704, 1.093583); `GOLDEN=MATCH`;
  coverage at least 98.2%; mass at most 109 (12.1 per 1,000 statements); every bench line
  PASS (run 5.333 s and 404 MB, compare 1.396 s and 192 MB, dashboard 5.597 s and 303 MB).
- Mutation sample: `bash .code-health/mutation.sh H1 <scratch>` scores at least station 423/473 (89.4%), engine 738/826 (89.3%), and results metrics 745/807 (92.3%), or, where the mutant count changes, at least the same percentage.
- No hand-calculated expected value changes: every changed line under tests/ in
  `git diff 02c98d9 -- tests` is read by hand before commit.
- One Codex adversarial review of the chunk, findings verified and dispositioned under Result.
- bench run median below the 4.848 s baseline (target about 10% lower; an A/B probe measured 3.66 s to 3.09 s at half the duration).

## Approach

In `_Server.pulse`, return when `self.changed.callbacks` is empty; an event with no callbacks moves neither the clock nor any other event's order. Drop the observe in `admit()` only on the placed path, where `dispatch()` already observed at the same time (engine.observe merges same-time rows, so the records match). In `set_phase`, when the closing activity ends where it started and is the last entry of `run.activities`, pop it; keep the end-of-run filter as a backstop. The golden check is the proof that nothing moved.

## Stop and ask

Beyond the standing list: any change to a simulation number, any golden mismatch that a
rename map entry cannot explain, and any test removal not named in this brief.

## Progress

## Result
