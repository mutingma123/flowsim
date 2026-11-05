# H1 Engine event overhead

**Status: done 2026-11-05.**
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

- baseline: 485 passed @ 2b807f3
- gates (logs/2026-11-05-1122-gate-*-H1.log, logs/2026-11-05-1128-gate-bench-H1.log): check EXIT=0,
  485 passed in 300.8 s; examples EXIT=0, sentinels 3/3; GOLDEN=MATCH; coverage 98.2%; mass 109
  (12.1); bench run 4.192 s and 376 MB, compare 1.141 s and 184 MB, dashboard 4.695 s and 292 MB.
- mutation (logs/2026-11-05-1129-mutation-H1-*.log): station 430/480 (89.6%), engine 738/826,
  results metrics 745/807.

## Result

All three edits are in flowsim/station.py: pulse() returns when no callback waits on the changed
event; admit() observes only on the pending path, since dispatch() observes on every path it
takes; set_phase() pops a zero-length activity that is still the last record (engine.py's
filter stays as a backstop). Every record and exported number is unchanged (golden match). The
long run is 13.5% faster (4.848 s to 4.192 s), beyond its noise band; compare and dashboard
also fell (1.269 s to 1.141 s, 5.088 s to 4.695 s). Implemented by a Sonnet subagent and
reviewed against the scheduler by the session.

Codex adversarial review (streams/reviews/H1-codex.md): approve, no findings. Its suggested
runtime comparison across shifts, failures, transfers, and drain boundaries is what the golden
check covers through the extension and operations examples.

Choices made: the per-capacity server counters from Reader 1 finding 1 were left out, since
they pay only from capacity 50 up.
