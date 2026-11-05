"""FlowSim: drawing a model in the builder, in six parts.

Each part is a manim-slides Slide, so the same source renders a continuous MP4 per part
(joined into one video by ../render.sh) and a deck with a break at every pause():

    Part1Open       builder("output/builder.html"), the canvas, side panel, Checks, script
    Part2Draw       source to Desk to Exam to the exit, and a branch that must sum to one
    Part3Times      named distributions and server counts, with the script following
    Part4Behaviors  a staffing schedule whose shift_end the page leaves to the student
    Part5Types      walk-ins and appointments, the type mix, and two Desk-to-Exam arrows
    Part6Run        the downloaded script's run, the experiment dashboard, the model file

Sources: the README section "Drawing a model in the browser", flowsim/builder.html, and
capture.py, which draws the clinic in the page with Playwright (as
tests/test_builder.py's two-route test does, plus a staffing schedule), downloads the
script and the model file into snippets/, runs the script and the script with an
experiment added, and writes captured/numbers.json. The assertions below check every
displayed number against the downloaded script, the page's Checks text, and those runs.

    bash ../render.sh builder preview|review|final
"""

import ast
import hashlib
import json
import re
from pathlib import Path

from manim import (
    DOWN,
    LEFT,
    RIGHT,
    UP,
    FadeIn,
    FadeOut,
    Group,
    RoundedRectangle,
)

from explainer import (
    ALERT,
    CONTENT_Y,
    INK,
    MUTED,
    label,
    make_box,
)
from flowsim_video import (
    CodeScene,
    close,
    excerpt,
    file_lines,
    load_captured,
    module_constant,
    readme_block,
    readme_states,
    screenshot,
    t_interval,
)

# ---------------------------------------------------------------------------
# Computation layer. Every number a scene displays is computed or read here and asserted
# against its source. Nothing below depends on how the scenes draw the results.
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
CAPTURED = load_captured(HERE)
# Every screenshot is the one this capture wrote.
for _name, _image in CAPTURED["images"].items():
    _digest = hashlib.sha256((HERE / "captured" / _image["file"]).read_bytes()).hexdigest()
    assert _digest == _image["sha256"], f"{_name} changed since capture; rerun capture.py"
CAPTURE = HERE / "capture.py"
STEPS = CAPTURED["steps"]

# The README's call that saves the page, which Part 1 shows as written.
OPEN_LINE = 'page = builder("output/builder.html")'
assert OPEN_LINE in readme_block("Drawing a model in the browser").split("\n")
readme_states("A staffing schedule needs `shift_end`")
readme_states("the script writes `None` for it, so running the script raises FlowSim's own error")

# The downloaded script, read from the file the page wrote, and its literal arguments.
SCRIPT_NAME = STEPS["download_name"]
MODEL_FILE_NAME = STEPS["model_file_name"]
assert (SCRIPT_NAME, MODEL_FILE_NAME) == ("flowsim_model.py", "flowsim_model.json")
SCRIPT = file_lines(HERE / "snippets" / SCRIPT_NAME)
assert "\n".join(SCRIPT) + "\n" == STEPS["typed"]["code"] == STEPS["loaded"]["code"]
EXTENDED = file_lines(HERE / "snippets" / "flowsim_model_extended.py")
ADDED = EXTENDED[len(SCRIPT) :]
assert EXTENDED[: len(SCRIPT)] == SCRIPT


def calls(code, method):
    """The literal keyword arguments of every call to .method( in code, in order."""
    found = []
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == method:
            found.append({k.arg: ast.literal_eval(k.value) for k in node.keywords if isinstance(k.value, ast.Constant | ast.List | ast.Dict)})
    return found


def stations(code):
    return {entry["name"]: entry for entry in calls(code, "station")}


# Inputs the capture typed, read from capture.py so the video and the capture agree.
DURATION = module_constant(CAPTURE, "DURATION")
INTERARRIVAL_MEAN = module_constant(CAPTURE, "INTERARRIVAL_MEAN")
MIX = module_constant(CAPTURE, "MIX")
DESK = module_constant(CAPTURE, "DESK")
EXAM = module_constant(CAPTURE, "EXAM")
STAFFING = module_constant(CAPTURE, "STAFFING")
WRONG_BRANCH = module_constant(CAPTURE, "WRONG_BRANCH")
BRANCH = module_constant(CAPTURE, "BRANCH")
REPLICATIONS = module_constant(CAPTURE, "REPLICATIONS")
assert ADDED == [
    "",
    f"experiment = model.experiment(duration={DURATION}, replications={REPLICATIONS})",
    'experiment.viewer("output/clinic.html")',
]

# The final script states each of them.
_final = "\n".join(SCRIPT)
_stations = stations(_final)
assert _stations["Desk"] == {"name": "Desk", "capacity": DESK["capacity"], "service_time": DESK["service"]}
assert _stations["Exam"]["capacity"] == EXAM["capacity"]
assert f"low={EXAM['low']},\n        high={EXAM['high']}," in _final
assert _stations["Exam"]["staffing"] == STAFFING and _stations["Exam"]["shift_end"] == "finish"
assert f"interarrival=exponential(mean={INTERARRIVAL_MEAN})" in _final
assert calls(_final, "source")[0]["types"] == MIX
assert calls(_final, "run")[0]["duration"] == DURATION
BRANCH_LINE = f'model.branch(desk, {{exam: {BRANCH[0]}, model.exit: {BRANCH[1]}}}, types=["Appointment"])'
WALK_IN_LINE = 'model.route([desk, exam], types=["Walk-in"])'
assert BRANCH_LINE in SCRIPT and WALK_IN_LINE in SCRIPT
assert sum(MIX.values()) == 1 and close(sum(BRANCH), 1)

# The page's Checks list at each step, as the capture read it.
OPEN_CHECKS = STEPS["open"]["checks"].split("\n")
assert OPEN_CHECKS == ["Add a source, where customers arrive.", "Exit: No source reaches it."]
WRONG_SUM = round(sum(WRONG_BRANCH), 10)
WRONG_CHECK = f"Branch probabilities from Desk sum to {WRONG_SUM:g}, not 1."
assert STEPS["branch_wrong"]["checks"] == WRONG_CHECK
assert "model.branch(desk, {exam: 0.3, model.exit: 0.6})" in STEPS["branch_wrong"]["code"]
UNTYPED_BRANCH = f"model.branch(desk, {{exam: {BRANCH[0]}, model.exit: {BRANCH[1]}}})"
assert UNTYPED_BRANCH in STEPS["branch"]["code"].split("\n")
for step in ["network", "branch", "times", "chosen", "typed", "loaded"]:
    assert STEPS[step]["checks"].startswith("No problems found in the page."), step
SHIFT_CHECK = "Exam: choose what an off-duty server does with its current job (shift_end)."
assert STEPS["unchosen"]["checks"] == SHIFT_CHECK
assert "    shift_end=None," in STEPS["unchosen"]["code"].split("\n")
assert '    shift_end="finish",' in STEPS["chosen"]["code"].split("\n")
UNCHOSEN_ERROR = CAPTURED["unchosen_error"]
assert UNCHOSEN_ERROR == "Scheduled staffing requires shift_end='finish' or 'pause'."
MIX_CHECKS = STEPS["types_added"]["checks"].split("\n")
assert MIX_CHECKS == [f"Customers: probability of {name} needs a value." for name in MIX]
WALK_IN_CHECK = STEPS["walk_in_missing"]["checks"]
assert WALK_IN_CHECK == "Desk has no route for type Walk-in, which can reach it from Customers."
assert STEPS["cleared"]["code"] != STEPS["typed"]["code"]
LOADED_STATUS = STEPS["loaded"]["status"]
assert LOADED_STATUS == f"Loaded {MODEL_FILE_NAME}."
assert json.loads((HERE / "snippets" / MODEL_FILE_NAME).read_text()) == CAPTURED["model_file"]

# One run of the downloaded script, as it printed itself.
RUN = CAPTURED["run"]
assert (RUN["duration"], RUN["seed"]) == (DURATION, calls(_final, "run")[0]["seed"])
PRINTED = CAPTURED["printed"].rstrip("\n").split("\n")
SUMMARY_LINE = next(line.strip() for line in PRINTED if line.strip().startswith("Summary:"))
assert SUMMARY_LINE == (
    f"Summary: arrivals {RUN['arrivals']}, completed {RUN['completed']}, "
    f"mean_total_wait {RUN['mean_total_wait']:.3g}, mean_flow_time {RUN['mean_flow_time']:.3g}"
)
assert RUN["completed"] + RUN["remaining"] == RUN["arrivals"]
# The printed station line, checked against the run's stations table.
STATIONS_LINE = next(line.strip() for line in PRINTED if line.strip().startswith("Stations:"))
_desk = next(row for row in CAPTURED["stations"] if row["station"] == "Desk")
assert STATIONS_LINE == f"Stations: Desk: mean_wait {_desk['mean_wait']:.3g}, utilization {_desk['utilization']:.3g}"

# The experiment the two added lines run, with its interval recomputed from the runs.
EXPERIMENT = CAPTURED["experiment"]
assert EXPERIMENT["replications"] == REPLICATIONS == len(EXPERIMENT["runs"])
WAIT_INTERVAL = t_interval(EXPERIMENT["runs"])
assert all(close(a, b) for a, b in zip(WAIT_INTERVAL, (EXPERIMENT["mean"], EXPERIMENT["lower"], EXPERIMENT["upper"])))
assert len(set(EXPERIMENT["seeds"])) == REPLICATIONS

# ---------------------------------------------------------------------------
# Display layer. Colors, layout, captions, and timing live here; fonts and caption rules
# come from ../shared/explainer.py.
# ---------------------------------------------------------------------------

SCRIPT_NOTE = f"manim/builder/snippets/{SCRIPT_NAME} (downloaded from the page)"
PAGE_NOTE = "The FlowSim script on the page"


def lines_of(code, first, count=None, last=None):
    return excerpt(code.rstrip("\n").split("\n"), first, count=count, last=last)


def outline(shot, region, page_size, color=ALERT):
    """A rounded outline over one page region of a full-page screenshot."""
    image = shot.image
    scale = image.width / page_size[0]
    x, y, width, height = region
    box = RoundedRectangle(
        corner_radius=0.06,
        width=width * scale + 0.08,
        height=height * scale + 0.08,
        stroke_color=color,
        stroke_width=4,
        fill_opacity=0,
    )
    box.move_to([image.get_left()[0] + (x + width / 2) * scale, image.get_top()[1] - (y + height / 2) * scale, 0])
    return box


def checks_box(lines, color=ALERT):
    return make_box("Checks", tuple(lines), color=color)


class BuilderScene(CodeScene):
    def setup(self):
        super().setup()
        self.side = None

    def beside(self, shot_name, code_lines, shot_height=5.0, size=20):
        """A screenshot at the left and a code panel at the right, which replace the
        previous pair on one click."""
        shot = screenshot(HERE, CAPTURED, shot_name, width=5.0, height=shot_height)
        shot.move_to([-4.0, CONTENT_Y - 0.25, 0])
        self.inside_frame(shot)
        drop = () if self.side is None else (self.side,)
        self.show_code(code_lines, PAGE_NOTE, x=2.6, y=CONTENT_Y - 0.25, width=7.4, size=size, drop=drop, add=(shot,))
        self.side = shot
        return shot


class Part1Open(BuilderScene):
    def construct(self):
        self.title_card(1, "Opening the builder")
        self.say("flowsim.builder saves a page that draws a model. The page writes its FlowSim script.")
        self.show_code([OPEN_LINE], "README, Drawing a model in the browser", top=2.2, size=24)
        page = screenshot(HERE, CAPTURED, "open_page", width=3.4, height=4.3)
        page.move_to([-4.65, -1.15, 0])
        self.inside_frame(page)
        self.play(FadeIn(page), run_time=0.6)
        self.pause("page")
        regions = CAPTURED["regions"]
        size = CAPTURED["page_size"]
        marked = None
        crop = None
        for name, text in [
            ("toolbar", "The toolbar adds nodes and sets the run length, seed, and time unit."),
            ("canvas", "The canvas holds the network. It starts with the exit, where customers leave."),
            ("panel", "The side panel edits the node or arrow selected on the canvas."),
            ("checks", f"Checks lists what would stop the script. The empty page has {len(OPEN_CHECKS)} items."),
            ("script", "The FlowSim script below the checks rewrites itself after every edit."),
        ]:
            self.say(text)
            box = outline(page, regions[name], size)
            shot = screenshot(HERE, CAPTURED, f"open_{name}", width=8.0, height=4.0)
            shot.move_to([1.9, -1.15, 0])
            self.inside_frame(shot)
            gone = [FadeOut(mob) for mob in (marked, crop) if mob is not None]
            self.play(*gone, FadeIn(box), FadeIn(shot), run_time=0.5)
            marked, crop = box, shot
            self.pause(name)
        self.say("The page works offline and never runs the model. Running the script does.")
        self.pause("end", hold=3.5)


class Part2Draw(BuilderScene):
    def construct(self):
        self.title_card(2, "Drawing the network")
        self.say("Add source and Add station place nodes. Dragging from a node's dot draws a route.")
        shot = screenshot(HERE, CAPTURED, "network", width=11.5, height=5.0)
        shot.move_to([0, CONTENT_Y - 0.2, 0])
        self.play(FadeIn(shot), run_time=0.6)
        self.pause("nodes")
        self.say("Customers go to Desk, then to Exam, then to the exit.")
        self.pause("route")

        self.say("Two arrows from Desk make a branch. Each arrow carries a probability.")
        self.play(FadeOut(shot), run_time=0.4)
        shot = screenshot(HERE, CAPTURED, "branch_wrong", width=10.5, height=3.9)
        shot.move_to([0, 0.35, 0])
        self.play(FadeIn(shot), run_time=0.6)
        self.pause("branch")
        self.say(f"With {WRONG_BRANCH[0]} and {WRONG_BRANCH[1]}, Checks reports a sum of {WRONG_SUM:g} instead of 1.")
        problem = checks_box([WRONG_CHECK])
        problem.next_to(shot, DOWN, buff=0.25)
        self.inside_frame(problem)
        self.play(FadeIn(problem), run_time=0.5)
        self.pause("sum")

        self.say(f"With {BRANCH[1]} to the exit, the script writes the branch.")
        self.play(FadeOut(shot), FadeOut(problem), run_time=0.4)
        shot = screenshot(HERE, CAPTURED, "branch_right", width=10.5, height=3.6)
        shot.move_to([0, 0.35, 0])
        self.play(FadeIn(shot), run_time=0.6)
        self.show_code(
            lines_of(STEPS["branch"]["code"], "model.route([customers, desk])", 3),
            PAGE_NOTE,
            y=-2.65,
            size=20,
        )
        self.inside_frame(self.panel)
        self.highlight(1)
        self.pause("end", hold=3.5)


class Part3Times(BuilderScene):
    def construct(self):
        self.title_card(3, "Setting arrivals and service")
        self.say("Each duration is a constant or a named distribution.")
        self.beside("panel_source", lines_of(STEPS["times"]["code"], "customers = model.source(", 4), shot_height=5.4)
        self.pause("durations")
        self.say(f"Customers arrive {INTERARRIVAL_MEAN} minutes apart on average, an exponential gap.")
        self.highlight(2)
        self.pause("arrivals")

        self.say(f"Desk has {DESK['capacity']} server and takes {DESK['service']} minute.")
        code = lines_of(STEPS["times"]["code"], "desk = model.station(", last="    ),")
        code = code + [")"]
        self.beside("panel_desk", code, shot_height=5.4, size=18)
        self.highlight(1, 3)
        self.pause("desk")
        self.say(
            f"Exam has {EXAM['capacity']} servers. An exam takes {EXAM['low']} to {EXAM['high']} minutes, "
            "any length equally likely.",
        )
        self.beside("panel_exam", code, shot_height=5.4, size=18)
        self.highlight(5, 12)
        self.pause("exam")
        self.say("Choosing uniform in the menu swaps in its low and high fields.")
        self.pause("menu")
        self.say("Each field change rewrites the script at once.")
        self.pause("end", hold=3.5)


class Part4Behaviors(BuilderScene):
    def construct(self):
        self.title_card(4, "Choosing behaviors")
        self.say(
            f"Exam's staffing schedule has {STAFFING[0][1]} server on duty from {STAFFING[0][0]} "
            f"and {STAFFING[1][1]} from {STAFFING[1][0]}.",
        )
        shot = screenshot(HERE, CAPTURED, "panel_staffing", width=4.6, height=5.6)
        shot.move_to([-4.0, CONTENT_Y - 0.25, 0])
        self.inside_frame(shot)
        self.play(FadeIn(shot), run_time=0.6)
        self.pause("schedule")
        self.say("A shift change can catch a server mid-job. The page leaves that rule, shift_end, unchosen.")
        self.pause("unchosen")
        self.say("Checks names the missing choice.")
        problem = checks_box([SHIFT_CHECK])
        problem.scale_to_fit_width(min(problem.width, 7.6)).move_to([2.5, 1.2, 0])
        self.play(FadeIn(problem), run_time=0.5)
        self.pause("checks")

        self.say("Until a choice is made, the script writes None.")
        code = lines_of(STEPS["unchosen"]["code"], "exam = model.station(", last=")")
        self.show_code(code, PAGE_NOTE, x=2.5, top=0.45, width=7.6, size=18, drop=(problem,))
        self.highlight(len(code) - 2)
        self.pause("none")
        self.say("Running that script stops at FlowSim's own error.")
        error = make_box("ValueError", (UNCHOSEN_ERROR,), color=ALERT)
        error.scale_to_fit_width(min(error.width, 7.6)).move_to([2.5, 1.2, 0])
        self.play(FadeIn(error), run_time=0.5)
        self.pause("error")

        self.say('"pause" would hold the job until that server is back on duty.')
        self.pause("pause-choice")
        self.say('Choosing "finish" lets an off-duty server finish its current job.')
        chosen = screenshot(HERE, CAPTURED, "panel_staffing_chosen", width=4.6, height=5.6)
        chosen.move_to(shot.get_center())
        code = lines_of(STEPS["chosen"]["code"], "exam = model.station(", last=")")
        self.show_code(code, PAGE_NOTE, x=2.5, top=0.45, width=7.6, size=18, drop=(error, shot), add=(chosen,))
        self.highlight(len(code) - 2)
        self.pause("end", hold=3.5)


class Part5Types(BuilderScene):
    def construct(self):
        self.title_card(5, "Routing customer types")
        names = list(MIX)
        self.say(
            f"A customer type is a label each arrival draws. Here {MIX[names[0]]:.0%} are walk-ins "
            f"and {MIX[names[1]]:.0%} appointments.",
        )
        self.beside("panel_mix", lines_of(STEPS["typed"]["code"], "customers = model.source(", 5), shot_height=5.4)
        self.highlight(3)
        self.pause("mix")
        self.say("Both arrows from Desk now carry appointments only. Walk-ins have no route at Desk.")
        problem = checks_box([WALK_IN_CHECK])
        problem.scale_to_fit_width(min(problem.width, 7.2)).move_to([3.0, -2.6, 0])
        self.inside_frame(problem)
        self.play(FadeIn(problem), run_time=0.5)
        self.pause("missing")

        self.say(f"Walk-ins go from Desk to Exam. Appointments branch to Exam ({BRANCH[0]}) or the exit ({BRANCH[1]}).")
        self.drop_code(self.side, problem)
        self.side = None
        shot = screenshot(HERE, CAPTURED, "typed_canvas", width=9.0, height=4.4)
        shot.move_to([0, 0.1, 0])
        self.play(FadeIn(shot), run_time=0.6)
        self.pause("canvas")
        self.say("Two arrows join Desk and Exam, one for each type.")
        self.pause("two")
        self.say("Selecting an arrow opens a side panel that picks the types it carries.")
        self.pause("arrow-panel")
        self.say("The script writes one typed branch and one typed route.")
        self.show_code([BRANCH_LINE, WALK_IN_LINE], PAGE_NOTE, y=-2.75, size=18, width=11.5)
        self.inside_frame(self.panel)
        self.pause("end", hold=3.5)


class Part6Run(BuilderScene):
    def construct(self):
        self.title_card(6, "Running the script")
        self.say(f"Download .py saves the script as {SCRIPT_NAME}. It is ordinary FlowSim code.")
        self.show_code(SCRIPT[-7:], SCRIPT_NOTE, top=2.2, size=22)
        self.pause("download")
        self.say(
            f"Running it simulates {DURATION} minutes: {RUN['arrivals']} arrivals and "
            f"{RUN['completed']} completed.",
        )
        printed = [line for line in PRINTED if line.strip().startswith(("Results:", "Summary:", "Stations:"))]
        output = make_box(f"python {SCRIPT_NAME}", tuple(line.strip() for line in printed))
        output.scale_to_fit_width(min(output.width, 11.5)).next_to(self.panel, DOWN, buff=0.35)
        self.inside_frame(output)
        self.play(FadeIn(output), run_time=0.5)
        self.pause("run")

        self.say(f"Two added lines run {REPLICATIONS} replications and save their dashboard page.")
        self.show_code(ADDED[1:], SCRIPT_NOTE.replace(SCRIPT_NAME, "flowsim_model_extended.py"), top=2.2, size=20, width=12.0, drop=(output,))
        self.pause("experiment")
        mean, lower, upper = WAIT_INTERVAL
        self.say(
            f"Mean total wait is {mean:.2f} minutes. The 95% confidence interval (CI) "
            f"is {lower:.2f} to {upper:.2f}.",
        )
        self.drop_code()
        shot = screenshot(HERE, CAPTURED, "dashboard", width=11.5, height=5.4)
        shot.move_to([0, CONTENT_Y - 0.2, 0])
        self.inside_frame(shot)
        self.play(FadeIn(shot), run_time=0.6)
        self.pause("dashboard")
        self.say("The metric menu switches to any metric that applies to the clinic.")
        self.pause("menu")
        self.say("Each dot below is one replication's mean total wait.")
        self.drop_code(shot)
        shot = screenshot(HERE, CAPTURED, "dashboard_runs", width=10.5, height=5.4)
        shot.move_to([0, CONTENT_Y - 0.2, 0])
        self.inside_frame(shot)
        self.play(FadeIn(shot), run_time=0.6)
        self.pause("dots")
        self.say("Choosing a replication opens that run's own view on the same page.")
        self.play(FadeOut(shot), run_time=0.4)
        shot = screenshot(HERE, CAPTURED, "dashboard_run", width=10.5, height=5.4)
        shot.move_to([0, CONTENT_Y - 0.2, 0])
        self.inside_frame(shot)
        self.play(FadeIn(shot), run_time=0.6)
        self.pause("run-view")

        self.say(f"Save model file writes {MODEL_FILE_NAME}. Load model file restores the drawing.")
        self.play(FadeOut(shot), run_time=0.4)
        bar = screenshot(HERE, CAPTURED, "loaded_toolbar", width=11.0, height=1.6)
        bar.move_to([0, 0.9, 0])
        status = label(LOADED_STATUS, size=26, color=MUTED).next_to(bar, DOWN, buff=0.35)
        self.play(FadeIn(bar), FadeIn(status), run_time=0.6)
        self.pause("end", hold=3.5)
