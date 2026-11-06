# H26 Faster figure styling for dashboards

**Status: done 2026-11-05.**
Depends on: H25 (run order, to keep one tree)
Branch: health-2.0 (owner ruling, 2026-11-05: chunks commit on health-2.0, which is pushed;
main is not merged or fast-forwarded until the owner approves a release)

## Goal

plots.style builds one fresh Layout from the figure's own layout merged with the shared style,
instead of calling Plotly's update_layout (twice outside a page). Every page keeps the same
values, so the service-day dashboard is faster with nothing else changed. Serves open item 2 of
the 2026-11-05 handoff, run on the owner's order of the same day. Changes no simulation number.

## Read first

- flowsim/plots.py:84-97 (style), 102-128 (station_menu, which runs before style in four
  figures), and 1396-1407 (page_figure, which drops each page figure's template).
- flowsim/fitting.py:470-500 (a make_subplots figure styled after its second axes exist).

## Scope

May change:
- flowsim/plots.py (style and one merge helper)
- tests/test_reporting.py (one added test of what style keeps and overrides)

Must not touch: the numbers the examples print or export, any hand-calculated expected value,
the AGENTS.md rules, and Plotly's trace_values list-or-array choice.

## Done check

- `bash .code-health/gate.sh H26` prints check `EXIT=0` with 523 passed (522 plus the new test);
  examples `EXIT=0` with sentinels 3/3; `GOLDEN=MATCH`; coverage at least 98.2%; mass at most
  109; every bench line PASS, with the dashboard ratio below H25's 0.946.
- The scratch page comparison (diffpages.py, below) finds every embedded JSON block of the
  service-day dashboard and its first run page equal by value, and the HTML outside them equal.
- One Codex adversarial review, findings verified and dispositioned under Result.
- No mutation sample: the chunk touches plots.py and tests/test_reporting.py, not station.py,
  engine.py, results.py, or tests those modules depend on.

## Approach

Measured before the edit (scripts in the session scratchpad). In one dashboard build, style runs
540 times at 2.6 ms each (1.40 s of 4.5 s). Every call meets a layout that already holds
Plotly's default template, which go.Figure() adds, and 120 of them also hold a station menu.
update_layout costs about 2.2 to 2.5 ms per call with or without that template, while building
and assigning a Layout costs about 0.85 ms. Merging the whole existing layout, template included,
cost 12 ms, since Plotly validates the 7 kB template again. The template is therefore dropped
before the merge: page_figure drops it from every page figure, and outside a page style replaces
it with plotly_white, as update_layout(template=...) did.

The merge matches update_layout: a nested dict merges into an existing nested dict, and any other
value replaces the old one (e.g., an axis title string replaces the title object). Interleaved
A/B of five dashboard builds: current median 4.184 s, merged 3.708 s (about 0.48 s, 11%). The
pages differed only in the order of layout keys, since a fresh Layout writes keys in its property
order.

## Stop and ask

None beyond the standing list.

## Progress

- baseline: 522 passed @ 91931b9 (H25 gate, logs/2026-11-05-2032-gate-check-H25.log).
- edit made inline. The new test passes against both the old style (HEAD's plots.py) and the
  new one, so the merge keeps and replaces what update_layout did. Plotly puts its default
  template back when a layout is assigned, so a page figure still carries it until page_figure
  drops it, as before; the test's first page check assumed otherwise and was corrected.
- page comparison (compare_html.py and compare_network.py in the session scratchpad): every
  example run in an exported HEAD tree and in the working tree. Of 31 HTML pages, builder.html
  is byte-equal; the 19 viewer and comparison pages have every JSON block equal by value and
  equal HTML around them; the 11 network.html pages, which Plotly writes with a random div id,
  have equal figure values. Only layout key order differs.
- gates (logs/2026-11-05-2100-gate-*-H26.log, .code-health/gate-H26.txt): check EXIT=0,
  523 passed in 171.3 s; examples EXIT=0, sentinels 3/3; GOLDEN=MATCH; coverage 98.2%; mass 103
  (11.1); bench run 0.909, compare 0.948, dashboard 0.834 (H25: 0.946), all PASS; GATE_EXIT=0.

## Result

style builds one Layout from the figure's layout, without its template, merged with the shared
values by _merged, which follows update_layout's rule. The dashboard bench ratio fell from 0.946
to 0.834 against the baseline tree (4.076 s against 4.885 s in this run). Every example page
keeps its values; only the order of layout keys changed. Added
test_style_keeps_earlier_layout_and_replaces_what_it_sets, which passes against both the old and
the new style. No expected number changed, and no test was removed.

Codex adversarial review (streams/reviews/H26-codex.md): approve, no findings. Its next step,
a test comparing full layouts against the previous implementation (with fitting subplots,
annotations, shapes, and magic-underscore inputs), was not taken: it would keep the old style in
the tests, the 31-page comparison above already checks page equality, tests/test_fitting.py
covers the subplot figures, and no underscore key reaches the merge, since to_plotly_json
returns nested keys and the shared values use none.
