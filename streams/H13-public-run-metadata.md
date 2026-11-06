# H13 Public run metadata instead of private reach-in

**Status: done 2026-11-05.**
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

- baseline: 510 passed @ 114cca7
- edit by an Opus subagent, reviewed by hand. Its checks: pixi run check EXIT=0, 510 passed;
  129 CSV and metadata.json files under output/ hash the same before and after, and 29 run and
  dashboard pages are byte-identical (11 network.html diagrams and lesson.html differ by
  Plotly's random div id, inferred, not proven).
- first gates (logs/2026-11-05-1528-gate-*-H13.log, .code-health/gate-H13-first.txt): all
  passed, but mass 104: engine.execute rose to medium cyclomatic complexity from the inline
  resources_vary expression. Fixed by lifting it into _Run.resources_vary.
- first mutation (logs/2026-11-05-1528-mutation-H13-*.log, .code-health/mutation-H13-first.txt):
  engine 735/841 (87.4%) and results metrics 741/803 (92.28%), both below baseline. Engine
  survivors: every resources_vary mutant (the decision moved from plots.py, outside the sample,
  into engine.py, and no non-browser test checked it) and the now-unread failures_enabled key.
  Results: 4 killed mutants went with the deleted _capacities property; survivors stayed 62.
- a second gate run (.code-health/gate-H13-void.txt) is void: the tree was edited while it ran.
- second mutation (.code-health/mutation-H13-second.txt), after resources_vary iterates stations
  and test_a_run_view_draws_server_states_only_where_a_station_can_vary was added: engine
  741/834 (88.85%), still below. Added
  test_export_metadata_repeats_each_behavior_argument_and_supply_setting (metadata.json values
  equal the model arguments) and test_a_stock_point_without_demand_reports_no_fill_rate (0 / 0
  is missing; confirmed it fails with demanded >= 0).
- final mutation (logs/2026-11-05-1600-mutation-H13-*.log): station 430/480, engine 763/834
  (91.5%, from 89.3%), results metrics 742/803 (92.4%, from 92.3%).
- final gates (logs/2026-11-05-1600-gate-*-H13.log): check EXIT=0, 516 passed in 270.7 s;
  examples EXIT=0, sentinels 3/3; GOLDEN=MATCH; coverage 98.2% (98.215%); mass 103 (11.2);
  bench run 0.883, compare 0.933, dashboard 0.931.
- `grep -rnE '\._(supply|records_kept|capacities)\b' flowsim tests` prints only model.py, whose
  Model._supply is Model's own field (model.py is outside Scope).

## Result

Results has three new public names: supply (a frozen, slotted SupplySettings whose chain is a
tuple and whose nested mappings are mappingproxies, or None), stock_point_names (a fresh list),
and records_kept (read-only, true while the raw tables exist). _supply, _records_kept,
_capacities, and plots.stock_point_names are gone; every reader uses the public names or
settings.capacities. The export converts SupplySettings back to plain JSON (metadata.json bytes
unchanged, golden match). The decision to draw server states reads a typed private flag,
_resources_vary, which _Run.resources_vary computes from each station's staffing, buffer, and
time_to_failure; it replaced plots' string-key read of _definitions. Tests: four private reads
became public ones with the same expected values, the expected public-name set in
test_run_settings_are_frozen_and_plumbing_is_private gained exactly supply, stock_point_names,
and records_kept (an API list, not a hand-calculated value), and three tests were added to keep
the mutation sample at or above baseline (above).

Migration (2.0): run._supply["chain"] becomes run.supply.chain (a tuple);
run._supply["chain"][1:] becomes run.stock_point_names; run._supply["stock_points"][name][key]
becomes run.supply.stock_points[name][key] (likewise period, demand, reconstructible);
run._records_kept becomes run.records_kept; run._capacities becomes run.settings.capacities;
flowsim.plots.stock_point_names(run) becomes run.stock_point_names.

Choices made on the owner's behalf: _resources_vary stays private rather than a fourth public
name (rejected: a public Results.resources_vary, a one-line rename if wanted); supply is a plain
attribute holding a frozen value, as settings is (rejected: a property, which needs a private
backing field); records_kept is computed from the tables present (rejected: a stored public
bool a user could set); README unchanged, since it has no section listing Results attributes.
The reporting.dashboard function-level PageExperiment import stays: results.py imports
reporting at module level, so a module-level import back is a cycle that
test_imports_follow_the_dependency_direction forbids.

Codex adversarial review (streams/reviews/H13-codex.md), one medium finding, accepted after
checking: supply_payload()["chain"] became a tuple where it was a list. Page JSON was identical,
but the payload now uses list(supply.chain), so the Python value is unchanged too. Its
suggested new test was rejected: the payload is internal and page bytes are already compared.

Left open (owner decisions): SupplySettings is importable from flowsim.results only, since
flowsim/__init__.py was outside Scope (proposed: add it beside Settings in the import and
__all__); reporting.locations decides "supply chain" with bool(stock_points) while
Results.report uses supply is not None (they agree today; proposed: supply=experiment.runs[0].
supply is not None in locations); tests still read _definitions in test_abandonment.py:84,
test_priorities.py:163-164, and test_distributions.py:267-268 and 357-358, since no public route
exists (the same values are public in metadata.json's definitions).
Owner decision, 2026-11-05: these _definitions reads stay. Switching them to the export
metadata would keep their expected values but tie distribution and priority tests to the
export format.

Metrics: mass 103 as at H11, bench ratios inside the range since H16, and the suite is not
faster, so by the loop's rule this chunk improves no metric. The engine mutation score rose
(89.3 to 91.5 percent), but the score is a guard in that rule, not a metric that counts.
