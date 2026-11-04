"""The model builder page: its schema, its file, and its generated code."""

import inspect
import json
import re
import runpy
import shutil
import subprocess

import pytest
from polars.testing import assert_frame_equal

import flowsim
from flowsim.builder_page import schema
from tests.models import branching_service, deterministic_queue

# Public distribution constructors the builder leaves out: sequence data
# (empirical, discrete), a wrapper (shifted), and demand counts.
NOT_IN_BUILDER = {"empirical", "discrete", "shifted", "poisson", "negative_binomial"}

SCHEMA_SCRIPT = r'<script id="schema" type="application/json">(.*?)</script>'


def test_schema_lists_every_duration_constructor_with_its_parameters():
    constructors = {
        name
        for name, member in vars(flowsim.distributions).items()
        if inspect.isfunction(member)
        and not name.startswith("_")
        and member.__module__ == "flowsim.distributions"
    }
    listed = {entry["name"]: entry for entry in schema()["distributions"]}
    assert set(listed) == constructors - NOT_IN_BUILDER
    assert set(listed) == {
        "exponential",
        "uniform",
        "triangular",
        "pert",
        "normal",
        "lognormal",
        "gamma",
        "weibull",
        "erlang",
        "beta",
    }
    for name, entry in listed.items():
        constructor = getattr(flowsim, name)
        signature = inspect.signature(constructor).parameters
        assert [item["name"] for item in entry["parameters"]] == list(signature)
        # The page fills a new distribution from the docstring example.
        constructor(**entry["example"])
    beta = {item["name"]: item for item in listed["beta"]["parameters"]}
    assert (beta["low"]["default"], beta["high"]["default"]) == (0, 1)
    assert beta["a"]["required"] and not beta["low"]["required"]
    mean = listed["exponential"]["parameters"][0]
    assert (mean["minimum"], mean["exclusive"]) == (0, True)
    k = listed["erlang"]["parameters"][0]
    assert (k["kind"], k["minimum"], k["exclusive"]) == ("integer", 1, False)


def test_schema_reads_model_arguments_from_their_signatures():
    data = schema()
    for kind, method in [
        ("source", flowsim.Model.source),
        ("station", flowsim.Model.station),
    ]:
        names = [item["name"] for item in data[kind]]
        assert names == [name for name in inspect.signature(method).parameters][1:]
        assert set(data["supported"][kind]) <= set(names)
    station = {item["name"]: item for item in data["station"]}
    assert station["shift_end"]["choices"] == ["finish", "pause"]
    assert station["service_time"]["kind"] == "duration"
    assert (station["capacity"]["kind"], station["capacity"]["minimum"]) == (
        "integer",
        1,
    )
    source = {item["name"]: item for item in data["source"]}
    assert source["interarrival"]["exclusive"] is True
    assert source["limit"]["kind"] == "integer"
    run = {item["name"]: item for item in data["run"]}
    assert run["seed"]["default"] == 42
    assert data["model"][0]["default"] == "minutes"
    assert {"model", "results", "print", "exponential", "class"} <= set(
        data["reserved"]
    )


def test_builder_page_embeds_the_schema_and_requests_nothing():
    page = flowsim.builder()
    assert isinstance(page, flowsim.Viewer)
    document = page.html
    embedded = re.search(SCHEMA_SCRIPT, document, re.DOTALL).group(1)
    assert json.loads(embedded) == json.loads(json.dumps(schema()))
    tags = re.findall(r"<(?:script|link|img|iframe)\b[^>]*>", document)
    assert tags and not any("http" in tag for tag in tags)
    scripts = re.findall(r"<script\b[^>]*>(.*?)</script>", document, re.DOTALL)
    assert not any(re.search(r"https?:", script) for script in scripts)
    assert 'sandbox="allow-scripts allow-downloads"' in page._repr_html_()
    assert "model builder page" in repr(page)


def test_builder_with_a_path_writes_the_page(tmp_path):
    path = tmp_path / "pages" / "builder.html"
    page = flowsim.builder(path)
    assert path.read_text(encoding="utf-8") == page.html


# Browser helpers. Each drives the page through its controls.


def add_node(page, kind, name, fields=None, durations=None):
    """Add a node, fill its panel, and return its id."""
    page.click(f"#add-{kind}")
    node_id = page.locator("#panel").get_attribute("data-node-id")
    page.fill("#field-name", name)
    for field, (distribution, values) in (durations or {}).items():
        page.select_option(f"#field-{field}-kind", distribution)
        for key, value in values.items():
            page.fill(f"#field-{field}-{key}", str(value))
    for field, value in (fields or {}).items():
        page.fill(f"#field-{field}", str(value))
    return node_id


def center(box):
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def drag(page, start, end):
    page.mouse.move(*start)
    page.mouse.down()
    page.mouse.move(*end, steps=8)
    page.mouse.up()


def node_box(page, node_id):
    return page.locator(f'g.node[data-node-id="{node_id}"] rect.body').bounding_box()


def drag_route(page, origin, target):
    """Draw a route by dragging from the origin's handle to the target."""
    handle = page.locator(f'g.node[data-node-id="{origin}"] .handle').bounding_box()
    drag(page, center(handle), center(node_box(page, target)))


def panel_route(page, origin, target):
    """Add a route from the side panel of the selected origin."""
    page.locator(f'g.node[data-node-id="{origin}"] rect.body').click(
        position={"x": 8, "y": 8}
    )
    page.select_option("#route-target", target)
    page.click("#add-route")


def node_state(page, node_id):
    nodes = page.evaluate("window.flowsimBuilder.state()")["nodes"]
    return next(node for node in nodes if node["id"] == node_id)


def run_script(code, tmp_path, monkeypatch):
    """Run generated code as a script in a temporary folder; return its results."""
    script = tmp_path / "generated" / "model.py"
    script.parent.mkdir()
    script.write_text(code, encoding="utf-8")
    ruff = shutil.which("ruff")
    if ruff is not None:
        formatted = subprocess.run(
            [ruff, "format", "--diff", str(script)],
            capture_output=True,
            text=True,
        )
        assert formatted.returncode == 0, formatted.stdout + formatted.stderr
    monkeypatch.chdir(script.parent)
    return runpy.run_path(str(script), run_name="__main__")["results"]


def assert_same_run(results, expected):
    for table in ("customers", "visits", "stations", "summary"):
        assert_frame_equal(getattr(results, table), getattr(expected, table))


def open_builder(tmp_path, offline_page):
    path = tmp_path / "builder.html"
    flowsim.builder(path)
    return offline_page(path)


def build_branching_service(page):
    """Draw tests.models.branching_service with named distributions and a branch."""
    page.fill("#run-duration", "120")
    customers = add_node(
        page,
        kind="source",
        name="Customers",
        durations={"interarrival": ("exponential", {"mean": 3})},
    )
    triage = add_node(
        page,
        kind="station",
        name="Triage",
        fields={"capacity": 1},
        durations={"service_time": ("constant", {"value": 1})},
    )
    routine = add_node(
        page,
        kind="station",
        name="Routine",
        fields={"capacity": 2},
        durations={"service_time": ("gamma", {"shape": 2, "scale": 2})},
    )
    specialist = add_node(
        page,
        kind="station",
        name="Specialist",
        fields={"capacity": 1},
        durations={"service_time": ("uniform", {"low": 5, "high": 8})},
    )
    # Move Specialist below Routine by dragging it.
    before = node_state(page, specialist)
    below = center(node_box(page, routine))
    drag(page, center(node_box(page, specialist)), (below[0], below[1] + 150))
    after = node_state(page, specialist)
    assert after["y"] > before["y"] + 100 and after["x"] < before["x"]
    drag_route(page, customers, triage)
    drag_route(page, triage, routine)
    drag_route(page, triage, specialist)
    # A second route from Triage makes a branch with probabilities on the arrows.
    arrow = f'.edge-prob[data-from="{triage}"][data-to="{routine}"]'
    assert page.locator(arrow).input_value() == "0.5"
    page.fill(arrow, "0.7")
    assert "sum to 1.2" in page.locator("#problems").inner_text()
    page.locator(f'g.node[data-node-id="{triage}"] rect.body').click(
        position={"x": 8, "y": 8}
    )
    page.fill(f'.panel-prob[data-to="{specialist}"]', "0.3")
    assert page.locator(arrow).input_value() == "0.7"
    panel_route(page, routine, "exit")
    drag_route(page, specialist, "exit")


def test_builder_writes_the_deterministic_queue(tmp_path, offline_page, monkeypatch):
    page = open_builder(tmp_path, offline_page)
    assert "Add a source" in page.locator("#problems").inner_text()
    page.fill("#run-duration", "10")
    customers = add_node(
        page,
        kind="source",
        name="Customers",
        fields={"first_arrival": 0, "limit": 3},
        durations={"interarrival": ("constant", {"value": 1})},
    )
    service = add_node(
        page,
        kind="station",
        name="Service",
        fields={"capacity": 1},
        durations={"service_time": ("constant", {"value": 2})},
    )
    drag_route(page, customers, service)
    assert "Service: It has no onward route" in page.locator("#problems").inner_text()
    drag_route(page, service, "exit")
    assert "No problems found" in page.locator("#problems").inner_text()
    code = page.locator("#code").text_content()
    assert code == (
        '"""A FlowSim model drawn in the model builder. '
        'Edit it like any FlowSim script."""\n'
        "\n"
        "from flowsim import Model\n"
        "\n"
        'model = Model(time_unit="minutes")\n'
        "customers = model.source(\n"
        '    name="Customers",\n'
        "    interarrival=1,\n"
        "    first_arrival=0,\n"
        "    limit=3,\n"
        ")\n"
        "service = model.station(\n"
        '    name="Service",\n'
        "    capacity=1,\n"
        "    service_time=2,\n"
        ")\n"
        "model.route([customers, service, model.exit])\n"
        "\n"
        "results = model.run(\n"
        "    duration=10,\n"
        "    seed=42,\n"
        ")\n"
        "print(results)\n"
    )
    results = run_script(code, tmp_path, monkeypatch)
    expected = deterministic_queue().run(
        duration=10,
        seed=42,
    )
    assert_same_run(results, expected)
    # The hand-calculated waits: 0, 1, and 2 minutes.
    waits = results.visits.get_column("wait_time").to_list()
    assert waits == [0, 1, 2]


def test_builder_writes_a_branching_network(tmp_path, offline_page, monkeypatch):
    page = open_builder(tmp_path, offline_page)
    build_branching_service(page)
    assert "No problems found" in page.locator("#problems").inner_text()
    code = page.locator("#code").text_content()
    assert "from flowsim import Model, exponential, gamma, uniform\n" in code
    assert "model.route([customers, triage])\n" in code
    assert "model.branch(triage, {routine: 0.7, specialist: 0.3})\n" in code
    with page.expect_download() as download_info:
        page.click("#download-code")
    download = download_info.value
    assert download.suggested_filename == "flowsim_model.py"
    saved = tmp_path / "download.py"
    download.save_as(saved)
    assert saved.read_text(encoding="utf-8") == code
    results = run_script(code, tmp_path, monkeypatch)
    expected = branching_service().run(
        duration=120,
        seed=42,
    )
    assert_same_run(results, expected)


def wait_for_status(page, text):
    """Wait for the file status, which the page sets after reading the file."""
    page.wait_for_function(
        "text => document.getElementById('file-status').textContent.includes(text)",
        arg=text,
    )


def test_builder_saves_and_loads_its_model_file(tmp_path, offline_page):
    page = open_builder(tmp_path, offline_page)
    build_branching_service(page)
    code = page.locator("#code").text_content()
    state = page.evaluate("window.flowsimBuilder.state()")
    with page.expect_download() as download_info:
        page.click("#save-json")
    saved = tmp_path / download_info.value.suggested_filename
    download_info.value.save_as(saved)
    data = json.loads(saved.read_text(encoding="utf-8"))
    assert (data["format"], data["version"]) == ("flowsim-builder", 1)
    assert data == state
    triage = next(node for node in data["nodes"] if node["name"] == "Triage")
    assert triage["service_time"] == {"name": "constant", "value": 1}
    page.click("#clear-model")
    assert "Add a source" in page.locator("#problems").inner_text()
    page.set_input_files("#load-json", str(saved))
    wait_for_status(page, "Loaded flowsim_model.json.")
    assert page.locator("#code").text_content() == code
    assert page.evaluate("window.flowsimBuilder.state()") == state
    # A file in another format version is refused, and the model stays.
    later = tmp_path / "later.json"
    later.write_text(json.dumps({**data, "version": 99}), encoding="utf-8")
    page.set_input_files("#load-json", str(later))
    wait_for_status(page, "version 99")
    assert page.locator("#code").text_content() == code


@pytest.mark.parametrize(
    argnames=("name", "identifier"),
    argvalues=[
        ("Check-in", "check_in"),
        ("2nd desk", "station_2nd_desk"),
        ("print", "print_station"),
    ],
)
def test_builder_derives_valid_unique_names(tmp_path, offline_page, name, identifier):
    page = open_builder(tmp_path, offline_page)
    add_node(page, kind="station", name=name)
    add_node(page, kind="station", name=f"{name} ")
    code = page.locator("#code").text_content()
    assert f"{identifier} = model.station(" in code
    assert f"{identifier}_2 = model.station(" in code
    assert "are named" in page.locator("#problems").inner_text()


def two_node_model(page):
    customers = add_node(
        page,
        kind="source",
        name="Customers",
        durations={"interarrival": ("constant", {"value": 1})},
    )
    service = add_node(
        page,
        kind="station",
        name="Service",
        fields={"capacity": 1},
        durations={"service_time": ("constant", {"value": 2})},
    )
    drag_route(page, customers, service)
    drag_route(page, service, "exit")
    return customers, service


def refuse_file(page, tmp_path, data, message):
    """Load a file that must be refused and check the model did not change."""
    code = page.locator("#code").text_content()
    state = page.evaluate("window.flowsimBuilder.state()")
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    page.set_input_files("#load-json", str(path))
    wait_for_status(page, "Could not load bad.json")
    assert message in page.locator("#file-status").text_content()
    assert page.locator("#code").text_content() == code
    assert page.evaluate("window.flowsimBuilder.state()") == state


def test_builder_refuses_a_loaded_node_id_that_would_reach_the_html(
    tmp_path, offline_page
):
    page = open_builder(tmp_path, offline_page)
    two_node_model(page)
    data = page.evaluate("window.flowsimBuilder.state()")
    hostile = 'n1" onmouseover="window.pwned=1'
    data["nodes"][0]["id"] = hostile
    for edge in data["edges"]:
        if edge["from"] == "n1":
            edge["from"] = hostile
    refuse_file(page, tmp_path, data, "Every node id must be")
    assert page.locator("[onmouseover]").count() == 0
    assert page.evaluate("window.pwned") is None
    # Ids that are not strings, or are repeated, are refused too.
    numbered = json.loads(json.dumps(data))
    numbered["nodes"][0]["id"] = 5
    refuse_file(page, tmp_path, numbered, "Every node id must be")
    repeated = json.loads(json.dumps(data))
    repeated["nodes"][0]["id"] = repeated["nodes"][1]["id"]
    refuse_file(page, tmp_path, repeated, "Two nodes have the id")


def test_builder_refuses_a_loaded_route_the_page_would_not_add(tmp_path, offline_page):
    page = open_builder(tmp_path, offline_page)
    customers, service = two_node_model(page)
    data = page.evaluate("window.flowsimBuilder.state()")
    routes = data["edges"]

    def with_edge(edge):
        return {**data, "edges": [*routes, edge]}

    def route(origin, target):
        return {"from": origin, "to": target, "probability": 1}

    refuse_file(
        page,
        tmp_path,
        with_edge(route(customers, service)),
        "Customers already routes to Service.",
    )
    refuse_file(
        page,
        tmp_path,
        with_edge(route(service, service)),
        "A node cannot route to itself.",
    )
    refuse_file(
        page,
        tmp_path,
        with_edge(route(service, customers)),
        "A source cannot receive routed customers.",
    )
    refuse_file(
        page,
        tmp_path,
        with_edge(route("exit", service)),
        "The exit cannot have an outgoing route.",
    )
    # Endpoints must be strings, so 1 and "1" cannot both pass.
    refuse_file(
        page,
        tmp_path,
        with_edge(route(1, service)),
        "A route names a node the file does not have.",
    )


def test_builder_flags_integers_that_a_number_cannot_hold_exactly(
    tmp_path, offline_page
):
    page = open_builder(tmp_path, offline_page)
    two_node_model(page)
    page.fill("#run-duration", "10")
    page.fill("#run-seed", "9007199254740993")
    assert "Seed must be a whole number" in page.locator("#problems").inner_text()
    assert "seed=None" in page.locator("#code").text_content()
    assert "9007199254740992" not in page.locator("#code").text_content()
    page.fill("#run-seed", "1e21")
    assert "Seed must be a whole number" in page.locator("#problems").inner_text()
    assert "seed=None" in page.locator("#code").text_content()
    page.fill("#run-seed", "9007199254740991")
    assert "No problems found" in page.locator("#problems").inner_text()
    assert "seed=9007199254740991" in page.locator("#code").text_content()
    page.fill("#run-seed", "007")
    assert "seed=7," in page.locator("#code").text_content()
    for text in ("2.0", "-3", "1e2"):
        page.fill("#field-capacity", text)
        assert (
            "capacity must be a whole number" in page.locator("#problems").inner_text()
        )


def test_builder_branch_tolerance_comes_from_the_model_check():
    tolerance = schema()["branch_sum_tolerance"]
    assert tolerance == flowsim.model.BRANCH_SUM_TOLERANCE

    def branch(extra):
        model = flowsim.Model()
        model.source(
            name="In",
            interarrival=1,
        )
        stations = [
            model.station(
                name=name,
                capacity=1,
                service_time=1,
            )
            for name in "ABC"
        ]
        model.branch(
            stations[0],
            {stations[1]: 0.5, stations[2]: 0.5 + extra},
        )

    branch(tolerance / 2)
    with pytest.raises(ValueError, match="must sum to one"):
        branch(tolerance * 2)


def test_builder_flags_branch_sums_outside_the_model_tolerance(tmp_path, offline_page):
    page = open_builder(tmp_path, offline_page)
    customers = add_node(
        page,
        kind="source",
        name="Customers",
        durations={"interarrival": ("constant", {"value": 1})},
    )
    triage = add_node(
        page,
        kind="station",
        name="Triage",
        fields={"capacity": 1},
        durations={"service_time": ("constant", {"value": 1})},
    )
    first = add_node(
        page,
        kind="station",
        name="First",
        fields={"capacity": 1},
        durations={"service_time": ("constant", {"value": 1})},
    )
    drag_route(page, customers, triage)
    panel_route(page, triage, first)
    panel_route(page, triage, "exit")
    arrow = f'.edge-prob[data-from="{triage}"][data-to="{first}"]'
    other = f'.edge-prob[data-from="{triage}"][data-to="exit"]'
    page.fill(arrow, "0.5")
    page.fill(other, "0.5000000001")
    assert "sum to 1.0000000001, not 1" in page.locator("#problems").inner_text()
    page.fill(arrow, "0.7")
    page.fill(other, "0.3")
    assert "sum to" not in page.locator("#problems").inner_text()
