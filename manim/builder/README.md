# FlowSim: drawing a model in the builder

A six-part teaching video. The continuous video is `output/Builder.mp4`, and the deck is
`output/deck/Builder.html` (both rebuilt by `pixi run render builder final` from the
`manim/` folder, after `pixi run python manim/builder/capture.py` from the project root).

| Scene | Part | Starts at slide | Source |
|---|---|---|---|
| `Part1Open` | Saves the page with `builder("output/builder.html")` and points to the toolbar, canvas, side panel, Checks list, and live script | 1 | README "Drawing a model in the browser", `flowsim/builder.html` |
| `Part2Draw` | Draws the source, Desk, Exam, and the exit, then a branch from Desk whose probabilities Checks rejects until they sum to one | 8 | `captured/numbers.json` (the page's Checks text and script at each step) |
| `Part3Times` | Sets the arrival gap and each station's servers and service time from named distributions, with the script beside the panel | 13 | `snippets/flowsim_model.py` (the downloaded script) |
| `Part4Behaviors` | Adds a staffing schedule at Exam, shows that the page leaves `shift_end` unchosen, the Checks entry, the `None` in the script and FlowSim's error, then chooses `"finish"` | 19 | `captured/numbers.json`, README "Drawing a model in the browser" |
| `Part5Types` | Adds walk-ins and appointments with their mix, the Checks entry for walk-ins without a route, and the two arrows from Desk to Exam | 26 | `snippets/flowsim_model.py`, `captured/numbers.json` |
| `Part6Run` | Downloads and runs the script, adds two lines for 20 replications and the dashboard, opens a replication, and saves and loads the model file | 32 | `snippets/flowsim_model.py`, `snippets/flowsim_model_extended.py`, `snippets/flowsim_model.json`, `captured/numbers.json` |

The deck has 39 slides. The slide numbers change if a part gains or loses a break.
Every displayed number is asserted against the sources above when the module is imported.

## Plan

Profile: teaching, about four minutes. The viewer knows FlowSim's sources, stations, and
routes from the core video or the README but has not used the builder page. The owner
approved the six parts below in the session brief of 2026-11-05 and asked that the plan be
recorded here rather than approved again. The model is the README's Desk and Exam clinic
with walk-ins and appointments, i.e., the model that
`tests/test_builder.py::test_builder_draws_two_routes_between_the_same_nodes_for_different_types`
builds, plus a staffing schedule at Exam for part 4. The approved parts are:

1. Opening the builder: `builder("output/builder.html")`, the canvas, side panel, Checks
   list, and live script.
2. Drawing the network: source to Desk to Exam to exit, and a branch whose probabilities
   must sum to one.
3. Setting arrivals and service: named distributions and server counts. The script
   updates as you edit.
4. Choosing behaviors: a staffing schedule leaves `shift_end` unselected. Checks names it,
   and the script writes `None` until the student picks.
5. Routing customer types: walk-ins and appointments, the type mix, and two arrows between
   Desk and Exam.
6. Running the script and exploring: download the `.py`, run it, open the experiment
   dashboard, and save and reload the JSON.

### Capture

`capture.py` saves the page with `flowsim.builder`, then drives it in Chrome through
Playwright as a student would: the toolbar buttons add nodes, a drag from a node's dot draws
each route, the side panel sets every field, and the page's own Download .py and Save model
file buttons write `snippets/flowsim_model.py` and `snippets/flowsim_model.json`. After
New model, Load model file reads the JSON back, and the capture asserts that the page then
writes the same script. It records the Checks text and the script after each step, runs the
script with `shift_end` still unchosen to record FlowSim's error, runs the downloaded script,
and runs it again with two added lines (`snippets/flowsim_model_extended.py`) that build a
20-replication experiment and its dashboard. Screenshots of the canvas and the side panel are
cropped to the nodes and fields a slide discusses, so they stay legible.

### Grounding

| Term on screen | Plain-language definition | Source | First part |
|---|---|---|---|
| builder page | An offline web page that draws a model and writes its FlowSim script | README "Drawing a model in the browser" | 1 |
| toolbar, canvas, side panel | The row of buttons and run settings, the drawing area, and the form for the selected node or arrow | `flowsim/builder.html` | 1 |
| Checks | The page's list of problems that would stop the script | README "Drawing a model in the browser" | 1 |
| source, station, exit | Taught in the core video; the page labels each node with its kind | README "A first model" | 2 |
| route, branch, probability | An arrow sends customers onward; two arrows from one node make a branch, with a probability on each that must sum to one | README "Branches and shared stations" | 2 |
| constant, named distribution, exponential, uniform | A duration is a fixed number or a distribution with its parameters; an exponential gap has the given mean, and a uniform time is equally likely anywhere between low and high | README "Durations and distributions", the page's field help | 3 |
| server, capacity | The number of parallel servers at a station | README "A first model" | 3 |
| staffing schedule | Servers on duty from each start time | the page's field help | 4 |
| `shift_end`, `"finish"`, `"pause"` | What a server going off duty does with its job: finish it, or pause it until back on duty | the page's field help, README "Demand and staffing schedules" | 4 |
| `None` | The script's placeholder for an unchosen behavior, which FlowSim rejects | README "Drawing a model in the browser" | 4 |
| customer type, type mix | A label each arrival draws, and the share of arrivals with each label | README "Customer types" | 5 |
| replication, 95% confidence interval (CI) | One independent run, and the mean across runs plus or minus a Student t multiple of its standard error | README "Replications" | 6 |
| dashboard | The experiment's saved page of every metric, whose replications open their own run view | README "Replications" | 6 |
| model file | The page's own JSON file, which Load model file reads back | README "Drawing a model in the browser" | 6 |

### Parts

Numbers come from `captured/numbers.json` and the snippet files, which `capture.py` writes;
`builder.py` asserts each one as listed.

| Scene | Shows | Numbers and their check | Breaks |
|---|---|---|---|
| `Part1Open` | The README call, a small map of the empty page with an outline, and a legible crop of each outlined region | the empty page's 2 Checks items (asserted against the captured Checks text) | after the page and each of the five regions |
| `Part2Draw` | The canvas after three nodes and three routes, the branch at 0.3 and 0.6 with the Checks entry, and the branch at 0.3 and 0.7 with its script line | 0.3, 0.6, their sum 0.9 (asserted against the Checks text and the script), 0.7 (asserted against the script) | after the nodes, the route, the branch, the sum, and the script |
| `Part3Times` | The source and Exam panels beside the script lines they write | mean 3, Desk 1 server and 1 minute, Exam 2 servers and 3 to 6 minutes (each asserted against the downloaded script and capture.py's inputs) | after each duration and station |
| `Part4Behaviors` | The staffing fields with both `shift_end` choices unselected, the Checks entry, the `None` line, FlowSim's error, and the `"finish"` line | staffing (0, 1) and (60, 2) (asserted against the script); the error text (captured by running the script) | after the schedule, the choice, Checks, `None`, the error, "pause", and "finish" |
| `Part5Types` | The type mix panel and source lines, the walk-in Checks entry, the typed canvas, and the typed route and branch lines | 60% and 40% (asserted against the script's `types=`), 0.3 and 0.7 for appointments (asserted against the typed branch line) | after the mix, the missing route, the canvas, the two arrows, the arrow panel, and the script |
| `Part6Run` | The script's last lines and its printed summary, the two added lines, the dashboard's overview and replication chart, a replication's run view, and the model file | the run length, arrivals, and completed customers (asserted against the printed summary and the run's tables); mean total wait and its 95% CI over 20 replications (recomputed from the 20 run values with t = 2.093 and asserted against `experiment.intervals`) | after each step |

## Review

The review render's contact sheets showed the full-page screenshot of part 1 too small to
read, and the canvas and side-panel screenshots carried empty space around small text. The
capture now crops the canvas to its nodes and arrows and the panel to the fields a slide
discusses, and part 1 pairs a small page map with a crop of each region. The first cut ran
188 seconds against the planned four minutes, so six captions were added, each stating what
the page shows (the toolbar, the distribution menu's fields, the "pause" choice, per-arrow
types, the dashboard's metric menu, and its replication chart). The second review showed the
Desk caption beside the Exam panel, the type-mix crop too tall, and the opened run view (a
whole page) too small to read; part 3 now shows the Desk panel first, the mix crop holds only
the two mix fields, and the run view shows its queue and waiting-time section.
