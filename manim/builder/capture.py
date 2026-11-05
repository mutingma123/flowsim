"""Draw the clinic in the builder page, run the script it writes, and capture both.

    pixi run python manim/builder/capture.py

Runs in the project environment. It saves the builder page with flowsim.builder, drives
it through Playwright and Chrome as a student would (adding nodes, routes, a branch,
durations, a staffing schedule, customer types), screenshots the page at each step,
downloads the script and the model file, runs the script, and runs it again with an
experiment added. Writes captured/numbers.json and captured/*.png, which builder.py
reads and asserts in the manim environment, and snippets/flowsim_model.py
(the download), snippets/flowsim_model.json (the saved model file), and
snippets/flowsim_model_extended.py (the download with two lines added), which the video
shows.
"""

import json
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "shared"))

import flowsim  # noqa: E402
from capture_tools import (  # noqa: E402
    ROOT,
    SCALE,
    _browser,
    column,
    digest,
    png_size,
    relative,
    run_snippet,
    shoot,
    write_numbers,
)

OUT = HERE / "captured"
SNIPPETS = HERE / "snippets"
PAGE = ROOT / "output" / "builder.html"
# The clinic, as tests/test_builder.py draws it, plus a staffing schedule at Exam.
DURATION = 240
INTERARRIVAL_MEAN = 3
MIX = {"Walk-in": 0.6, "Appointment": 0.4}
DESK = {"capacity": 1, "service": 1}
EXAM = {"capacity": 2, "low": 3, "high": 6}
STAFFING = [(0, 1), (60, 2)]
WRONG_BRANCH = (0.3, 0.6)
BRANCH = (0.3, 0.7)
REPLICATIONS = 20
# Canvas positions (SVG units) that spread the nodes so both Desk-to-Exam arrows read.
LAYOUT = {"Customers": (40, 230), "Desk": (250, 230), "Exam": (520, 110), "Exit": (720, 330)}
EXPERIMENT_LINES = [
    "",
    f"experiment = model.experiment(duration={DURATION}, replications={REPLICATIONS})",
    'experiment.viewer("output/clinic.html")',
]


class Builder:
    """The open builder page and the steps a student takes in it."""

    def __init__(self, page):
        self.page = page
        self.ids = {}

    def code(self):
        return self.page.locator("#code").text_content()

    def checks(self):
        return self.page.locator("#problems").inner_text()

    def add(self, kind, name):
        self.page.click(f"#add-{kind}")
        node = self.page.locator("#panel").get_attribute("data-node-id")
        self.page.fill("#field-name", name)
        self.ids[name] = node
        return node

    def select(self, name):
        node = self.ids[name]
        self.page.locator(f'g.node[data-node-id="{node}"] rect.body').click(position={"x": 8, "y": 8})

    def node_box(self, name):
        node = "exit" if name == "Exit" else self.ids[name]
        return self.page.locator(f'g.node[data-node-id="{node}"] rect.body').bounding_box()

    def drag(self, start, end):
        self.page.mouse.move(*start)
        self.page.mouse.down()
        self.page.mouse.move(*end, steps=8)
        self.page.mouse.up()

    def route(self, origin, target):
        """Drag from the origin's handle to the target, as the canvas help says."""
        handle = self.page.locator(f'g.node[data-node-id="{self.ids[origin]}"] .handle').bounding_box()
        box = self.node_box(target)
        self.drag(
            (handle["x"] + handle["width"] / 2, handle["y"] + handle["height"] / 2),
            (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2),
        )

    def panel_route(self, origin, target):
        """Add a route from the side panel, which the page offers for a second arrow."""
        self.select(origin)
        self.page.select_option("#route-target", "exit" if target == "Exit" else self.ids[target])
        self.page.click("#add-route")

    def move(self, name, x, y):
        """Drag a node so its top-left corner sits at (x, y) in canvas units."""
        canvas = self.page.locator("#canvas").bounding_box()
        view = float(self.page.locator("#canvas").get_attribute("viewBox").split()[2])
        scale = canvas["width"] / view
        box = self.node_box(name)
        start = (box["x"] + 20, box["y"] + 10)
        end = (canvas["x"] + x * scale + 20, canvas["y"] + y * scale + 10)
        self.drag(start, end)

    def edges(self, origin, target):
        target_id = "exit" if target == "Exit" else self.ids[target]
        return self.page.locator(
            f'.edge-hit[data-from="{self.ids[origin]}"][data-to="{target_id}"]'
        ).evaluate_all("items => items.map((item) => item.dataset.edge)")

    def probability(self, edge, value):
        self.page.fill(f'.edge-prob[data-edge="{edge}"]', str(value))

    def types_of(self, edge, chosen):
        self.page.focus(f'.edge-hit[data-edge="{edge}"]')
        self.page.check("#edge-types-some")
        for type_id in ["t1", "t2"]:
            if type_id in chosen:
                self.page.check(f"#edge-type-{type_id}")
            else:
                self.page.uncheck(f"#edge-type-{type_id}")

    def deselect(self):
        """Click an empty corner of the canvas, which clears the selection."""
        self.page.locator("#canvas").click(position={"x": 6, "y": 6})

    def region(self, selectors, closest=None):
        """The page-coordinate box around every match of the selectors, each widened to
        its closest container when one is given (a panel field or fieldset)."""
        return self.page.evaluate(
            """([selectors, closest]) => {
                const boxes = [];
                for (const selector of selectors) {
                    for (const found of document.querySelectorAll(selector)) {
                        const item = closest ? (found.closest(closest) || found) : found;
                        const box = item.getBoundingClientRect();
                        if (box.width && box.height) boxes.push(box);
                    }
                }
                return [
                    Math.min(...boxes.map(b => b.left)) + scrollX,
                    Math.min(...boxes.map(b => b.top)) + scrollY,
                    Math.max(...boxes.map(b => b.right)) + scrollX,
                    Math.max(...boxes.map(b => b.bottom)) + scrollY,
                ];
            }""",
            [selectors, closest],
        )

    def crop(self, name, box, record, pad=14):
        """Screenshot one page region, so a slide shows it large enough to read."""
        path = OUT / f"{name}.png"
        self.page.wait_for_timeout(300)
        left, top, right, bottom = box
        self.page.screenshot(
            path=str(path),
            full_page=True,
            clip={"x": left - pad, "y": top - pad, "width": right - left + 2 * pad, "height": bottom - top + 2 * pad},
        )
        record(name, path)
        return path

    def canvas_crop(self, name, record):
        """The nodes, arrows, and probability boxes, without the empty grid around them."""
        self.crop(name, self.region(["#canvas g.node", "#canvas path.edge", "#canvas foreignObject", "#canvas text"]), record, pad=24)

    def panel_crop(self, name, fields, record):
        """The panel fields that hold the given inputs, with the panel's scroll limit
        lifted so every field is on the page."""
        self.page.evaluate("document.getElementById('panel').style.maxHeight = 'none'")
        self.crop(name, self.region(fields, closest=".field, fieldset"), record)
        self.page.evaluate("document.getElementById('panel').style.maxHeight = ''")

    def shot(self, name, selector, record):
        path = OUT / f"{name}.png"
        self.page.wait_for_timeout(300)
        self.page.locator(selector).first.screenshot(path=str(path))
        record(name, path)
        return path


def drive(numbers, record):
    """Draw the clinic step by step, recording the page after each step."""
    from playwright.sync_api import sync_playwright

    flowsim.builder(PAGE)
    steps = numbers["steps"] = {}
    with sync_playwright() as driver:
        browser = _browser(driver)
        page = browser.new_page(
            viewport={"width": 1400, "height": 1000},
            device_scale_factor=SCALE,
            accept_downloads=True,
        )
        page.route("http*://**/*", lambda route: route.abort())
        page.goto(PAGE.resolve().as_uri())
        clinic = Builder(page)

        # Part 1: the empty page, with the box of each region the video points to.
        path = OUT / "open_page.png"
        page.screenshot(path=str(path), full_page=True)
        record("open_page", path)
        numbers["regions"] = {
            name: page.locator(selector).first.evaluate(
                "item => { const box = item.getBoundingClientRect(); "
                "return [box.left + scrollX, box.top + scrollY, box.width, box.height]; }"
            )
            for name, selector in [
                ("toolbar", "main > .toolbar"),
                ("canvas", "section.canvas-box"),
                ("panel", "#panel"),
                ("checks", "section:has(#problems)"),
                ("script", "section:has(#code)"),
            ]
        }
        numbers["page_size"] = page.evaluate(
            "[document.documentElement.scrollWidth, document.documentElement.scrollHeight]"
        )
        clinic.crop("open_toolbar", clinic.region(["main > .toolbar"]), record, pad=4)
        clinic.crop("open_canvas", clinic.region(["section.canvas-box"]), record, pad=4)
        clinic.crop("open_panel", clinic.region(["#panel > *"]), record)
        clinic.shot("open_checks", "section:has(#problems)", record)
        clinic.shot("open_script", "section:has(#code)", record)
        steps["open"] = {"code": clinic.code(), "checks": clinic.checks()}

        # Part 2: three nodes with the page's defaults, the routes, and a branch.
        page.fill("#run-duration", str(DURATION))
        for kind, name in [("source", "Customers"), ("station", "Desk"), ("station", "Exam")]:
            clinic.add(kind, name)
        for name, (x, y) in LAYOUT.items():
            clinic.move(name, x, y)
        clinic.route("Customers", "Desk")
        clinic.route("Desk", "Exam")
        clinic.route("Exam", "Exit")
        clinic.deselect()
        clinic.canvas_crop("network", record)
        steps["network"] = {"code": clinic.code(), "checks": clinic.checks()}
        clinic.route("Desk", "Exit")
        (to_exam,) = clinic.edges("Desk", "Exam")
        (to_exit,) = clinic.edges("Desk", "Exit")
        clinic.probability(to_exam, WRONG_BRANCH[0])
        clinic.probability(to_exit, WRONG_BRANCH[1])
        clinic.deselect()
        clinic.canvas_crop("branch_wrong", record)
        steps["branch_wrong"] = {"code": clinic.code(), "checks": clinic.checks()}
        clinic.probability(to_exit, BRANCH[1])
        clinic.deselect()
        clinic.canvas_crop("branch_right", record)
        steps["branch"] = {"code": clinic.code(), "checks": clinic.checks()}

        # Part 3: named distributions and server counts.
        clinic.select("Customers")
        page.select_option("#field-interarrival-kind", "exponential")
        page.fill("#field-interarrival-mean", str(INTERARRIVAL_MEAN))
        clinic.panel_crop("panel_source", ["#field-name", "#field-interarrival-kind"], record)
        clinic.select("Desk")
        page.fill("#field-capacity", str(DESK["capacity"]))
        page.select_option("#field-service_time-kind", "constant")
        page.fill("#field-service_time-value", str(DESK["service"]))
        clinic.panel_crop("panel_desk", ["#field-name", "#field-capacity", "#field-service_time-kind"], record)
        clinic.select("Exam")
        page.fill("#field-capacity", str(EXAM["capacity"]))
        page.select_option("#field-service_time-kind", "uniform")
        page.fill("#field-service_time-low", str(EXAM["low"]))
        page.fill("#field-service_time-high", str(EXAM["high"]))
        clinic.panel_crop("panel_exam", ["#field-name", "#field-capacity", "#field-service_time-kind"], record)
        steps["times"] = {"code": clinic.code(), "checks": clinic.checks()}

        # Part 4: a staffing schedule at Exam, which leaves shift_end unchosen.
        page.check("#field-staffing_on")
        page.fill("#field-staffing-0-value", str(STAFFING[0][1]))
        page.click("#add-row-staffing")
        page.fill("#field-staffing-1-start", str(STAFFING[1][0]))
        page.fill("#field-staffing-1-value", str(STAFFING[1][1]))
        clinic.panel_crop("panel_staffing", ["#field-staffing-0-value", "#field-shift_end-finish"], record)
        steps["unchosen"] = {"code": clinic.code(), "checks": clinic.checks()}
        page.check("#field-shift_end-finish")
        assert page.is_checked("#field-shift_end-finish")
        clinic.panel_crop("panel_staffing_chosen", ["#field-staffing-0-value", "#field-shift_end-finish"], record)
        steps["chosen"] = {"code": clinic.code(), "checks": clinic.checks()}

        # Part 5: customer types, the type mix, and two arrows from Desk to Exam.
        page.click("#add-type")
        page.fill("#type-name-t1", "Walk-in")
        page.click("#add-type")
        page.fill("#type-name-t2", "Appointment")
        steps["types_added"] = {"code": clinic.code(), "checks": clinic.checks()}
        clinic.select("Customers")
        page.fill("#field-mix-t1", str(MIX["Walk-in"]))
        page.fill("#field-mix-t2", str(MIX["Appointment"]))
        clinic.panel_crop("panel_mix", ["#field-mix-t1", "#field-mix-t2"], record)
        clinic.types_of(to_exam, ["t2"])
        clinic.types_of(to_exit, ["t2"])
        steps["walk_in_missing"] = {"code": clinic.code(), "checks": clinic.checks()}
        clinic.panel_route("Desk", "Exam")
        walk_in = next(edge for edge in clinic.edges("Desk", "Exam") if edge != to_exam)
        clinic.types_of(walk_in, ["t1"])
        clinic.probability(to_exam, BRANCH[0])
        clinic.probability(to_exit, BRANCH[1])
        clinic.deselect()
        clinic.canvas_crop("typed_canvas", record)
        steps["typed"] = {"code": clinic.code(), "checks": clinic.checks()}

        # Part 6: download the script and save the model file, then load it back.
        with page.expect_download() as download:
            page.click("#download-code")
        script = SNIPPETS / download.value.suggested_filename
        download.value.save_as(script)
        steps["download_name"] = download.value.suggested_filename
        with page.expect_download() as download:
            page.click("#save-json")
        model_file = SNIPPETS / download.value.suggested_filename
        download.value.save_as(model_file)
        steps["model_file_name"] = download.value.suggested_filename
        page.once("dialog", lambda dialog: dialog.accept())
        page.click("#clear-model")
        steps["cleared"] = {"code": clinic.code()}
        page.set_input_files("#load-json", str(model_file))
        page.wait_for_function("document.getElementById('file-status').textContent.length > 0")
        steps["loaded"] = {
            "code": clinic.code(),
            "checks": clinic.checks(),
            "status": page.locator("#file-status").inner_text(),
        }
        clinic.shot("loaded_toolbar", "main > .toolbar", record)
        browser.close()
    return script, model_file


def main():
    OUT.mkdir(exist_ok=True)
    SNIPPETS.mkdir(exist_ok=True)
    numbers = {"sources": {}, "images": {}}

    def record_image(name, path):
        # The hash ties each screenshot to this capture, so a partial recapture or a
        # swapped file stops builder.py (Codex review, 2026-11-05).
        numbers["images"][name] = {"file": Path(path).name, "size": png_size(path), "sha256": digest(path)}

    script, model_file = drive(numbers, record_image)
    steps = numbers["steps"]
    assert script.read_text(encoding="utf-8") == steps["typed"]["code"]
    assert steps["loaded"]["code"] == steps["typed"]["code"]
    numbers["model_file"] = json.loads(model_file.read_text(encoding="utf-8"))

    # The script as the page wrote it with shift_end unchosen stops at FlowSim's check.
    unchosen = SNIPPETS / "unchosen.py"
    unchosen.write_text(steps["unchosen"]["code"], encoding="utf-8")
    try:
        run_snippet(unchosen)
    except ValueError as error:
        numbers["unchosen_error"] = str(error)
    else:
        raise AssertionError("The script with shift_end=None ran.")
    finally:
        unchosen.unlink()

    # Running the downloaded script, then the same script with an experiment added.
    namespace, printed = run_snippet(script)
    results = namespace["results"]
    numbers["printed"] = printed
    numbers["run"] = {
        **results.summary.row(0, named=True),
        "seed": results.settings.seed,
        "duration": results.settings.duration,
    }
    numbers["types"] = column(results.customers, "customer_type")
    numbers["stations"] = results.stations.select("station", "mean_wait", "utilization").to_dicts()
    extended = SNIPPETS / "flowsim_model_extended.py"
    extended.write_text(script.read_text(encoding="utf-8") + "\n".join(EXPERIMENT_LINES) + "\n", encoding="utf-8")
    namespace, _ = run_snippet(extended)
    experiment = namespace["experiment"]
    row = experiment.intervals("mean_total_wait").row(0, named=True)
    numbers["experiment"] = {
        "runs": column(experiment.summary.sort("replication"), "mean_total_wait"),
        "mean": row["mean"],
        "lower": row["lower"],
        "upper": row["upper"],
        "replications": len(experiment.runs),
        "seeds": [run.settings.seed for run in experiment.runs],
    }
    dashboard = ROOT / "output" / "clinic.html"
    numbers["dashboard_bytes"] = dashboard.stat().st_size
    record_image(
        "dashboard",
        shoot(dashboard, OUT / "dashboard.png", selector="#overview", viewport=(1000, 900), wait_ready=True),
    )

    record_image(
        "dashboard_runs",
        shoot(dashboard, OUT / "dashboard_runs.png", selector="#replication-section", viewport=(1000, 900), wait_ready=True),
    )

    def open_run(page):
        page.select_option("#run-choice", index=0)
        page.click("#open-run")
        page.wait_for_function("window.flowsimRunReady !== undefined")
        page.evaluate("window.flowsimRunReady")

    record_image(
        "dashboard_run",
        shoot(dashboard, OUT / "dashboard_run.png", selector="#run-root section:has(#queues)", viewport=(1200, 900), wait_ready=True, before=open_run),
    )
    for path in [script, model_file, extended, ROOT / "flowsim" / "builder.html", Path(__file__)]:
        numbers["sources"][relative(path)] = digest(path)
    write_numbers(OUT, numbers)


if __name__ == "__main__":
    main()
