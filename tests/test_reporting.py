"""Shared reporting, plots, viewers, run reports, settings, and diagrams."""

import inspect
import json
import math
import re
import webbrowser
from dataclasses import FrozenInstanceError
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from flowsim import (
    Comparison,
    Experiment,
    Model,
    compare,
    exponential,
    moving_average,
    order_up_to,
)
from flowsim.model import Node
from flowsim.plots import chain_positions, layout_layers
from flowsim.results import (
    STATION_METRICS,
    STATION_SCHEMA,
    STOCK_POINT_METRICS,
    SYSTEM_METRICS,
    Settings,
)
from flowsim.viewer import Viewer
from tests.models import beer_chain, deterministic_queue, service_network


@pytest.fixture(scope="module")
def experiment():
    return service_network(service_capacity=1).experiment(
        duration=60,
        replications=3,
        seed=1,
    )


@pytest.fixture(scope="module")
def comparison():
    return compare(
        scenarios={
            "One": service_network(service_capacity=1),
            "Two": service_network(service_capacity=2),
        },
        duration=60,
        replications=3,
        seed=1,
    )


def test_experiment_and_comparison_share_reporting_signatures():
    for name in ["intervals", "plot", "viewer", "export"]:
        shared = inspect.signature(getattr(Experiment, name)).parameters
        compared = inspect.signature(getattr(Comparison, name)).parameters
        for parameter in ["metric", "station", "stock_point", "confidence"]:
            assert shared[parameter].default == compared[parameter].default, name
            assert shared[parameter].kind == compared[parameter].kind, name
        assert shared["metric"].default == "mean_total_wait"
        assert "baseline" not in shared


@pytest.mark.parametrize(
    ("metric", "station"),
    [
        ("mean_total_wait", None),
        ("mean_wait", None),
        ("mean_wait", "Service"),
        ("utilization", "Check-in"),
    ],
)
def test_experiment_rows_equal_the_comparison_rows_of_the_same_scenario(
    experiment,
    comparison,
    metric,
    station,
):
    # Both run the one-server model from seed 1, so the runs are identical.
    alone = experiment.intervals(
        metric,
        station=station,
    )
    within = (
        comparison.intervals(
            metric,
            station=station,
        )
        .filter(pl.col("scenario") == "One")
        .drop("scenario")
    )
    assert_frame_equal(alone, within)
    expected = ["Check-in", "Service"] if station is None else [station]
    if metric == "mean_total_wait":
        expected = [None]
    assert alone.get_column("station").to_list() == expected
    assert set(alone.get_column("metric")) == {metric}


def test_comparison_station_metric_covers_every_station_in_each_scenario(comparison):
    intervals = comparison.intervals("mean_wait")
    assert intervals.select("scenario", "station").rows() == [
        ("One", "Check-in"),
        ("One", "Service"),
        ("Two", "Check-in"),
        ("Two", "Service"),
    ]
    differences = comparison.differences("mean_wait")
    assert differences.select("scenario", "baseline", "station").rows() == [
        ("Two", "One", "Check-in"),
        ("Two", "One", "Service"),
    ]
    # Each difference is the matched runs' station means subtracted.
    stations = comparison.stations.filter(pl.col("station") == "Service")
    one, two = (
        stations.filter(pl.col("scenario") == name)
        .sort("replication")
        .get_column("mean_wait")
        .to_numpy()
        for name in ["One", "Two"]
    )
    assert differences.get_column("mean").to_list()[1] == pytest.approx(
        (two - one).mean()
    )


def test_experiment_plot_draws_one_point_per_location(experiment):
    stations = experiment.plot("mean_wait")
    assert [list(trace.y) for trace in stations.data] == [["Check-in"], ["Service"]]
    assert [trace.meta for trace in stations.data] == ["Check-in", "Service"]
    assert stations.layout.yaxis.title.text == "Station"
    system = experiment.plot()
    assert len(system.data) == 1
    assert list(system.data[0].y) == ["System"]
    assert system.layout.xaxis.title.text == "Mean total waiting time (minutes)"
    single = experiment.plot(
        "utilization",
        station="Service",
    )
    assert "at Service" in single.layout.xaxis.title.text
    assert single.layout.xaxis.tickformat == ".0%"


def test_comparison_plot_names_scenario_and_station_when_several(comparison):
    figure = comparison.plot("mean_wait")
    assert [trace.name for trace in figure.data] == ["Check-in", "Service"]
    assert list(figure.data[1].y) == ["One<br>Service", "Two<br>Service"]
    assert figure.data[0].showlegend


def test_experiment_viewer_shows_one_metric_without_differences(tmp_path):
    # One server gives waits 0, 1, and 2 in every replication, so the mean
    # station wait is 1 with a zero-width interval.
    experiment = deterministic_queue().experiment(
        duration=7,
        replications=3,
    )
    viewer = experiment.viewer(
        tmp_path / "page.html",
        metric="mean_wait",
    )
    page = viewer.html
    assert (tmp_path / "page.html").read_text(encoding="utf-8") == page
    assert "<h1>Replication intervals</h1>" in page
    assert "<h2>Mean station waiting time at Service</h2>" in page
    assert (
        "<tr><th>Station</th><th>Mean (minutes)</th><th>Lower limit (minutes)</th>"
        "<th>Upper limit (minutes)</th><th>Observed runs</th></tr>"
    ) in page
    assert (
        "<tr><td>Service</td><td>1.000</td><td>1.000</td><td>1.000</td><td>3</td></tr>"
    ) in page
    assert "Difference from" not in page
    assert 'id="scenario-differences"' not in page
    for placeholder in ["__TEXT__", "__TITLE__", "__MEANS__", "__HEADER__"]:
        assert placeholder not in page


def test_experiment_export_writes_pooled_tables_and_metadata(tmp_path):
    experiment = deterministic_queue().experiment(
        duration=7,
        replications=3,
        seed=5,
    )
    (tmp_path / "differences.csv").write_text("stale")
    (tmp_path / "customers.csv").write_text("stale")
    (tmp_path / "notes.txt").write_text("keep")
    experiment.export(
        tmp_path,
        metric="mean_wait",
        confidence=0.9,
    )
    written = sorted(path.name for path in tmp_path.iterdir())
    assert written == [
        "intervals.csv",
        "metadata.json",
        "notes.txt",
        "runs.csv",
        "stations.csv",
    ]
    runs = pl.read_csv(tmp_path / "runs.csv")
    assert runs.get_column("replication").to_list() == [1, 2, 3]
    assert runs.get_column("completed").to_list() == [3, 3, 3]
    assert pl.read_csv(tmp_path / "stations.csv").height == 3
    intervals = pl.read_csv(tmp_path / "intervals.csv")
    assert intervals.select("metric", "station", "mean").rows() == [
        ("mean_wait", "Service", 1.0)
    ]
    metadata = json.loads((tmp_path / "metadata.json").read_text())
    assert metadata["metric"] == "mean_wait"
    assert metadata["station"] is None
    assert metadata["confidence"] == 0.9
    assert metadata["duration"] == 7
    assert metadata["time_unit"] == "minutes"
    assert metadata["replication_seeds"] == [
        run.settings.seed for run in experiment.runs
    ]


def test_experiment_export_writes_stock_points_for_a_supply_chain(tmp_path):
    experiment = beer_chain().experiment(
        duration=12,
        replications=2,
    )
    experiment.export(
        tmp_path,
        metric="fill_rate",
    )
    assert pl.read_csv(tmp_path / "stock_points.csv").height == 2 * 4
    assert pl.read_csv(tmp_path / "intervals.csv").get_column(
        "stock_point"
    ).to_list() == ["Retailer", "Wholesaler", "Distributor", "Factory"]
    # A later service-network export removes the supply-chain table.
    deterministic_queue().experiment(
        duration=7,
        replications=2,
    ).export(tmp_path)
    assert not (tmp_path / "stock_points.csv").exists()


def test_inapplicable_metrics_name_the_right_call():
    network = deterministic_queue().experiment(
        duration=7,
        replications=2,
    )
    with pytest.raises(ValueError, match="no stock points.*metric='mean_total_wait'"):
        network.intervals("fill_rate")
    with pytest.raises(ValueError, match="no stock points"):
        network.plot("bullwhip_ratio")
    chain = beer_chain().experiment(
        duration=12,
        replications=2,
    )
    # The default metric needs customers, which a chain without production lacks.
    with pytest.raises(ValueError, match="no production stations.*metric='fill_rate'"):
        chain.intervals()
    with pytest.raises(ValueError, match="no production stations"):
        chain.intervals("utilization")
    with pytest.raises(ValueError, match="takes no station="):
        network.intervals(
            "mean_total_wait",
            station="Service",
        )
    with pytest.raises(ValueError, match="takes no stock_point="):
        network.intervals(
            "mean_wait",
            stock_point="Retailer",
        )
    with pytest.raises(ValueError, match="Close matches: Factory"):
        chain.intervals(
            "fill_rate",
            stock_point="Factor",
        )
    both = compare(
        scenarios={
            "Chain": beer_chain(),
            "Other chain": beer_chain("end_demand"),
        },
        duration=12,
        replications=2,
    )
    with pytest.raises(ValueError, match="no production stations"):
        both.intervals()
    with pytest.raises(ValueError, match="no production stations"):
        both.export("unused")


@pytest.fixture(scope="module")
def service_run():
    return service_network().run(
        duration=30,
        seed=1,
    )


@pytest.fixture(scope="module")
def chain_run():
    return beer_chain().run(
        duration=12,
        seed=2,
    )


@pytest.mark.parametrize(
    ("method", "per_station"),
    [("plot_queue", 2), ("plot_wait", 1), ("plot_resources", 6)],
)
def test_station_plots_draw_one_named_station(service_run, method, per_station):
    every = getattr(service_run, method)()
    assert {trace.meta for trace in every.data} == {"Check-in", "Service"}
    assert len(every.layout.updatemenus[0].buttons) == 2
    chosen = getattr(service_run, method)(station="Service")
    assert [trace.meta for trace in chosen.data] == ["Service"] * per_station
    assert all(trace.visible for trace in chosen.data)
    assert not chosen.layout.updatemenus
    with pytest.raises(ValueError, match="Close matches: Service"):
        getattr(service_run, method)(station="Servce")


def test_utilization_plot_can_show_one_station(service_run):
    every = service_run.plot_utilization()
    assert list(every.data[0].y) == ["Check-in", "Service"]
    chosen = service_run.plot_utilization(station="Service")
    assert list(chosen.data[0].y) == ["Service"]
    expected = service_run.stations.filter(pl.col("station") == "Service")
    assert list(chosen.data[0].x) == expected.get_column("utilization").to_list()


def test_inventory_plot_draws_one_named_stock_point(chain_run):
    every = chain_run.plot_inventory()
    assert len(every.data) == 4 * 4
    chosen = chain_run.plot_inventory(stock_point="Factory")
    assert [trace.meta for trace in chosen.data] == ["Factory"] * 4
    assert all(trace.visible for trace in chosen.data)
    with pytest.raises(ValueError, match="Close matches: Factory"):
        chain_run.plot_inventory(stock_point="Factroy")


@pytest.mark.parametrize("method", ["plot_inventory", "plot_orders"])
def test_stock_point_plots_on_a_service_network_name_the_station_plots(
    service_run,
    method,
):
    with pytest.raises(ValueError, match=r"no stock points\. plot_queue\(\)"):
        getattr(service_run, method)()


@pytest.mark.parametrize(
    "method",
    ["plot_queue", "plot_wait", "plot_utilization", "plot_resources"],
)
def test_station_plots_on_a_supply_chain_name_the_stock_point_plots(
    chain_run,
    method,
):
    with pytest.raises(ValueError, match=r"no stations\. plot_inventory\(\)"):
        getattr(chain_run, method)()


def test_viewer_holds_the_document_and_saves_it(tmp_path):
    result = deterministic_queue().run(duration=7)
    viewer = result.viewer()
    assert isinstance(viewer, Viewer)
    assert viewer.html.startswith("<!doctype html>")
    saved = viewer.save(tmp_path / "new" / "page.html")
    assert saved == tmp_path / "new" / "page.html"
    assert saved.read_text(encoding="utf-8") == viewer.html
    # A path saves the page and still returns the Viewer.
    direct = result.viewer(tmp_path / "direct.html")
    assert isinstance(direct, Viewer)
    assert (tmp_path / "direct.html").read_text(encoding="utf-8") == direct.html


def test_viewer_displays_in_an_isolated_frame_and_prints_briefly():
    viewer = deterministic_queue().run(duration=7).viewer()
    frame = viewer._repr_html_()
    assert frame.startswith('<iframe srcdoc="')
    assert 'sandbox="allow-scripts allow-downloads"' in frame
    assert "allow-same-origin" not in frame
    # The document is escaped inside srcdoc, so no tag reaches the notebook.
    assert "<script" not in frame
    srcdoc = re.match(r'<iframe srcdoc="([^"]*)"', frame).group(1)
    assert "&lt;script" in srcdoc
    text = repr(viewer)
    assert len(text) < 200
    assert "<script" not in text
    assert re.search(r"results page, \d+\.\d MB", text)
    assert ".save(path)" in text and ".open()" in text
    comparison = compare(
        scenarios={
            "One": deterministic_queue(),
            "Two": deterministic_queue(capacity=2),
        },
        duration=7,
        replications=2,
    )
    assert "comparison page" in repr(comparison.viewer())
    assert "replication page" in repr(comparison.experiments["One"].viewer())


def test_viewer_open_writes_a_file_and_opens_its_address(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(
        target=webbrowser,
        name="open",
        value=opened.append,
    )
    viewer = deterministic_queue().run(duration=7).viewer()
    temporary = viewer.open()
    try:
        assert temporary.read_text(encoding="utf-8") == viewer.html
        assert opened == [temporary.resolve().as_uri()]
    finally:
        Path(temporary).unlink()
    saved = viewer.save(tmp_path / "page.html")
    assert viewer.open() == saved
    assert opened[-1] == saved.resolve().as_uri()


def test_headline_columns_come_first_in_tables_and_exports(service_run, tmp_path):
    assert service_run.stations.columns[:6] == [
        "station",
        "mean_wait",
        "mean_queue",
        "utilization",
        "p95_wait",
        "max_queue",
    ]
    assert service_run.summary.columns[:6] == [
        "arrivals",
        "completed",
        "mean_total_wait",
        "mean_flow_time",
        "throughput",
        "overtime",
    ]
    # The schema constant agrees with the table, and no column is lost.
    assert list(STATION_SCHEMA) == service_run.stations.columns
    assert len(set(service_run.stations.columns)) == 26
    service_run.export(tmp_path)
    for table in ["stations", "summary"]:
        exported = pl.read_csv(tmp_path / f"{table}.csv")
        assert exported.columns == getattr(service_run, table).columns


def test_report_lists_each_applicable_metric_with_hand_checked_values():
    # Customers arrive at 0, 1, and 2 and each needs 2 minutes on one server, so
    # all three exit by 6, before closing at 7. One customer waits from 1 to 2
    # and another from 2 to 4, so at most one waits at a time. The server is
    # busy over [0, 6), i.e., 6 of 7 minutes.
    report = deterministic_queue().run(duration=7).report()
    assert report.columns == ["scope", "location", "metric", "label", "value", "units"]
    assert report.group_by("scope", maintain_order=True).len().rows() == [
        ("system", len(SYSTEM_METRICS)),
        ("station", len(STATION_METRICS)),
    ]
    assert report.get_column("metric").to_list() == [
        *SYSTEM_METRICS,
        *STATION_METRICS,
    ]
    values = {
        (row["location"], row["metric"]): row for row in report.iter_rows(named=True)
    }
    assert values[None, "completed"]["value"] == 3
    assert values[None, "completed"]["units"] == "count"
    assert values["Service", "max_queue"]["value"] == 1
    assert values["Service", "utilization"]["value"] == pytest.approx(6 / 7)
    assert values[None, "mean_total_wait"]["units"] == "minutes"
    assert values[None, "mean_total_wait"]["label"] == "Mean total waiting time"


def test_report_omits_scopes_the_model_lacks(chain_run):
    chain = chain_run.report()
    # Without stations, only the run-level overtime and end_time remain of the
    # system metrics, and no station rows appear.
    assert set(chain.get_column("scope")) == {"stock_point", "system"}
    stages = chain.filter(pl.col("scope") == "stock_point")
    assert stages.get_column("location").unique(maintain_order=True).to_list() == [
        "Retailer",
        "Wholesaler",
        "Distributor",
        "Factory",
    ]
    assert chain.height == 4 * len(STOCK_POINT_METRICS) + 2
    model = Model()
    source = model.source(
        name="Customers",
        interarrival=1,
    )
    model.route([source, model.exit])
    plain = model.run(duration=5).report()
    assert set(plain.get_column("scope")) == {"system"}


def public_names(value) -> set[str]:
    return {name for name in dir(value) if not name.startswith("_")}


def test_run_settings_are_frozen_and_plumbing_is_private():
    # Arrivals at 0, 1, and 2 need 2 minutes each, so draining past closing at
    # 3 ends the run when the third customer leaves at 6.
    result = deterministic_queue().run(
        duration=3,
        seed=8,
        drain=True,
    )
    settings = result.settings
    assert isinstance(settings, Settings)
    assert (
        settings.duration,
        settings.warmup,
        settings.drain,
        settings.seed,
        settings.time_unit,
        settings.end_time,
    ) == (3, 0, True, 8, "minutes", 6)
    assert dict(settings.capacities) == {"Service": 1}
    with pytest.raises(FrozenInstanceError):
        settings.duration = 4
    with pytest.raises(TypeError):
        settings.capacities["Service"] = 2
    assert public_names(result) == {
        "customers",
        "visits",
        "states",
        "activities",
        "failures",
        "inventory",
        "shipments",
        "stations",
        "summary",
        "stock_points",
        "settings",
        "plot_queue",
        "plot_wait",
        "plot_utilization",
        "plot_resources",
        "plot_customer",
        "plot_inventory",
        "plot_orders",
        "viewer",
        "export",
        "report",
    }


def test_experiment_and_comparison_settings_omit_values_that_differ(comparison):
    experiment = comparison.experiments["One"]
    shared = experiment.settings
    assert (shared.duration, shared.time_unit, shared.seed, shared.end_time) == (
        60,
        "minutes",
        None,
        None,
    )
    assert dict(shared.capacities) == {"Check-in": 1, "Service": 1}
    assert comparison.settings.capacities is None
    assert comparison.settings.duration == 60
    shared_names = {"settings", "intervals", "plot", "viewer", "export"}
    assert public_names(experiment) == shared_names | {
        "runs",
        "summary",
        "stations",
        "stock_points",
        "stock_point_names",
    }
    assert public_names(comparison) == shared_names | {
        "experiments",
        "baseline",
        "summary",
        "stations",
        "stock_points",
        "differences",
    }


def marked(figure) -> dict[str, str]:
    """Map each node label in the diagram's warning trace to its hover note."""
    (trace,) = [trace for trace in figure.data if trace.meta == "problem"]
    return dict(zip(trace.text, trace.customdata))


def test_diagram_marks_a_station_whose_route_misses_the_exit():
    model = Model()
    source = model.source(
        name="Customers",
        interarrival=1,
    )
    station = model.station(
        name="Service",
        capacity=1,
        service_time=1,
    )
    model.route([source, station])
    figure = model.diagram()
    notes = marked(figure)
    assert set(notes) == {"Service<br>1 server", "Exit"}
    assert "no onward route" in notes["Service<br>1 server"]
    assert notes["Exit"] == "No source reaches it."
    assert "Red nodes need routes" in figure.layout.title.text
    # The exit stays in the last layer even with no route into it.
    assert layout_layers(model) == [["Customers"], ["Service"], ["Exit"]]
    with pytest.raises(ValueError, match="'Service' has no onward route"):
        model.diagram(check=True)


def test_diagram_marks_an_unreachable_station_in_a_cyclic_network():
    # A and B form a cycle across types, and C has no route at all.
    model = Model()
    first = model.source(
        name="X orders",
        interarrival=1,
        types={"X": 1},
    )
    second = model.source(
        name="Y orders",
        interarrival=1,
        types={"Y": 1},
    )
    a, b, c = (
        model.station(
            name=name,
            capacity=1,
            service_time=1,
        )
        for name in ["A", "B", "C"]
    )
    model.route(
        [first, a, b, model.exit],
        types=["X"],
    )
    model.route(
        [second, b, a, model.exit],
        types=["Y"],
    )
    notes = marked(model.diagram())
    assert list(notes) == ["C<br>1 server"]
    assert notes["C<br>1 server"].startswith("No source reaches it. It has no onward")
    assert layout_layers(model) == [["X orders", "Y orders", "C"], ["A", "B"], ["Exit"]]
    with pytest.raises(ValueError, match="'C' is unreachable"):
        model.diagram(check=True)


def test_diagram_of_a_complete_model_marks_nothing():
    figure = deterministic_queue().diagram()
    assert marked(figure) == {}
    assert figure.layout.title.text is None
    model = Model()
    station = model.station(
        name="Service",
        capacity=1,
        service_time=1,
    )
    model.route([station, model.exit])
    # Without a source, the station and the exit are unreachable.
    assert set(marked(model.diagram())) == {"Service<br>1 server", "Exit"}
    unlinked = Model(time_unit="weeks")
    unlinked.demand(
        name="Consumers",
        per_period=50,
    )
    with pytest.raises(ValueError, match=r"Link them with model\.supply"):
        unlinked.diagram()


def chain_nodes(figure) -> dict[str, list[tuple[str, float, float]]]:
    """Map each node trace's kind to its (label, x, y) points."""
    return {
        trace.meta: list(zip(trace.text, trace.x, trace.y)) for trace in figure.data
    }


def arrows(figure) -> list[tuple[float, float, float, float]]:
    """Return each arrow's start and end, rounded, in drawing order."""
    return [
        tuple(round(value, 2) for value in (item.ax, item.ay, item.x, item.y))
        for item in figure.layout.annotations
        if item.showarrow
    ]


def test_chain_diagram_places_beer_game_stages_by_hand():
    figure = beer_chain().diagram()
    # Goods move from the supplier at x = 0 down the chain to consumers at x = 5.
    assert chain_nodes(figure) == {
        "supplier": [("Supplier", 0.0, 0.0)],
        "stock_point": [
            ("Retailer", 4.0, 0.0),
            ("Wholesaler", 3.0, 0.0),
            ("Distributor", 2.0, 0.0),
            ("Factory", 1.0, 0.0),
        ],
        "demand": [("Consumers", 5.0, 0.0)],
        "station": [],
    }
    # Each arrow stops 0.17 short of both nodes.
    assert arrows(figure) == [
        (x + 0.17, 0.0, x + 0.83, 0.0) for x in [0.0, 1.0, 2.0, 3.0, 4.0]
    ]
    # Each stock point's two-week lead time labels the arrow into it, and the
    # arrow to consumers has none.
    labels = [
        (item.text, item.x) for item in figure.layout.annotations if not item.showarrow
    ]
    assert labels == [
        ("2 weeks", 0.5),
        ("2 weeks", 1.5),
        ("2 weeks", 2.5),
        ("2 weeks", 3.5),
    ]
    assert figure.layout.title.text == (
        "Goods move left to right. Each arrow into a stock point shows its lead time."
    )


def test_chain_diagram_draws_production_below_the_producing_stage():
    figure = one_stage_chain(produce=True).diagram()
    assert chain_nodes(figure) == {
        "supplier": [],
        "stock_point": [("Factory", 0.0, 0.0)],
        "demand": [("Consumers", 1.0, 0.0)],
        "station": [("Press<br>1 server", 1.0, -1.0)],
    }
    # Factory to consumers, then the production route to the press and back.
    # Each diagonal has unit vector (+-0.7071, -+0.7071) and shifts 0.08 to its
    # own left. It stops 0.35 from the factory, past its label, and 0.17 from
    # the press: e.g., the arrow down starts at 0.35 * 0.7071 + 0.08 * 0.7071
    # = 0.30 and -0.35 * 0.7071 + 0.08 * 0.7071 = -0.19.
    assert sorted(arrows(figure)) == [
        (0.17, 0.0, 0.83, 0.0),
        (0.3, -0.19, 0.94, -0.82),
        (0.82, -0.94, 0.19, -0.3),
    ]
    assert not [item for item in figure.layout.annotations if not item.showarrow]
    assert figure.layout.title.text == (
        "Goods move left to right. The stations below the top stage make its goods."
    )
    model = Model(time_unit="weeks")
    consumers = model.demand(
        name="Consumers",
        per_period=50,
    )
    store = model.stock_point(
        name="Store",
        initial=100,
        lead_time=exponential(mean=2),
        shortage="backorder",
        policy=order_up_to(
            forecast=moving_average(window=1),
            safety_factor=0,
            cover=2,
        ),
        forecast_from="orders",
    )
    model.supply(
        [consumers, store],
        period=1,
    )
    figure = model.diagram()
    labels = [item.text for item in figure.layout.annotations if not item.showarrow]
    assert labels == ["Exponential(mean=2)"]


def test_chain_diagram_spreads_a_production_line_across_columns():
    model = Model(time_unit="weeks")
    consumers = model.demand(
        name="Consumers",
        per_period=50,
    )
    factory = model.stock_point(
        name="Factory",
        initial=100,
        lead_time=None,
        batch_size=16,
        shortage="backorder",
        policy=order_up_to(
            forecast=moving_average(window=1),
            safety_factor=0,
            cover=2,
        ),
        forecast_from="orders",
    )
    cut, weld, paint = (
        model.station(
            name=name,
            capacity=2,
            service_time=0.01,
        )
        for name in ["Cut", "Weld", "Paint"]
    )
    model.route([factory, cut, weld, factory])
    model.supply(
        [consumers, factory],
        period=1,
    )
    assert paint.name == "Paint"
    # Paint is on no route, so it follows the two-step line instead of hiding.
    stations = chain_nodes(model.diagram())["station"]
    assert stations == [
        ("Cut<br>2 servers", 1.0, -1.0),
        ("Weld<br>2 servers", 2.0, -1.0),
        ("Paint<br>2 servers", 3.0, -1.0),
    ]


def producing_factory() -> tuple[Model, Node, Node]:
    """A linked one-stage chain whose factory produces, with no route yet."""
    model = Model(time_unit="weeks")
    consumers = model.demand(
        name="Consumers",
        per_period=50,
    )
    factory = model.stock_point(
        name="Factory",
        initial=100,
        lead_time=None,
        batch_size=16,
        shortage="backorder",
        policy=order_up_to(
            forecast=moving_average(window=1),
            safety_factor=0,
            cover=2,
        ),
        forecast_from="orders",
    )
    return model, consumers, factory


def test_chain_diagram_keeps_branch_arrows_clear_of_other_stations():
    model, consumers, factory = producing_factory()
    a, b, c, d = (
        model.station(
            name=name,
            capacity=1,
            service_time=0.01,
        )
        for name in "ABCD"
    )
    model.branch(factory, {a: 0.3, b: 0.3, c: 0.4})
    for station in (a, b, c):
        model.route([station, d])
    model.route([d, factory])
    model.supply(
        [consumers, factory],
        period=1,
    )
    # A, B, and C are one step from the factory, so they stack in column 1;
    # D is two steps away, in column 2.
    assert chain_positions(model) == {
        "Factory": (0.0, 0.0),
        "Consumers": (1.0, 0.0),
        "A": (1.0, -1.0),
        "B": (1.0, -2.0),
        "C": (1.0, -3.0),
        "D": (2.0, -1.0),
    }
    positions = list(chain_positions(model).values())
    for x0, y0, x1, y1 in arrows(model.diagram()):
        for x, y in positions:
            if min(math.dist((x, y), (x0, y0)), math.dist((x, y), (x1, y1))) < 0.5:
                continue
            # The closest point of the arrow to a node it does not join.
            share = ((x - x0) * (x1 - x0) + (y - y0) * (y1 - y0)) / (
                (x1 - x0) ** 2 + (y1 - y0) ** 2
            )
            share = min(max(share, 0), 1)
            closest = (x0 + share * (x1 - x0), y0 + share * (y1 - y0))
            assert math.dist((x, y), closest) > 0.3


def test_chain_diagram_draws_an_unfinished_producer_and_numpy_lead_times():
    model, consumers, factory = producing_factory()
    model.supply(
        [consumers, factory],
        period=1,
    )
    assert chain_positions(model) == {"Factory": (0.0, 0.0), "Consumers": (1.0, 0.0)}
    with pytest.raises(ValueError):
        model.diagram(check=True)
    for lead_time in (np.int64(2), np.float32(2)):
        model = Model(time_unit="weeks")
        consumers = model.demand(
            name="Consumers",
            per_period=50,
        )
        store = model.stock_point(
            name="Store",
            initial=100,
            lead_time=lead_time,
            shortage="backorder",
            policy=order_up_to(
                forecast=moving_average(window=1),
                safety_factor=0,
            ),
            forecast_from="orders",
        )
        model.supply(
            [consumers, store],
            period=1,
        )
        figure = model.diagram()
        labels = [item.text for item in figure.layout.annotations if not item.showarrow]
        assert labels == ["2 weeks"]


def one_stage_chain(produce: bool) -> Model:
    """A factory that either buys with a two-week lead time or makes on one press."""
    model = Model(time_unit="weeks")
    consumers = model.demand(
        name="Consumers",
        per_period=50,
    )
    factory = model.stock_point(
        name="Factory",
        initial=100,
        lead_time=None if produce else 2,
        batch_size=16 if produce else None,
        shortage="backorder",
        # A constant lead time sets its own cover, and production needs one.
        policy=order_up_to(
            forecast=moving_average(window=1),
            safety_factor=0,
            cover=2 if produce else None,
        ),
        forecast_from="orders",
    )
    if produce:
        press = model.station(
            name="Press",
            capacity=1,
            service_time=1 / 64,
        )
        model.route([factory, press, factory])
    model.supply(
        [consumers, factory],
        period=1,
    )
    return model


def test_a_comparison_reports_customer_metrics_where_any_scenario_has_them():
    comparison = compare(
        scenarios={
            "Buy": one_stage_chain(produce=False),
            "Make": one_stage_chain(produce=True),
        },
        duration=6,
        replications=2,
    )
    # The buying scenario has no jobs, so its flow time is never observed.
    flow = comparison.intervals("mean_flow_time")
    assert flow.select("scenario", "observed_runs").rows() == [("Buy", 0), ("Make", 2)]
    # Only the making scenario has a station to report.
    press = comparison.intervals("utilization")
    assert press.select("scenario", "station").rows() == [("Make", "Press")]
    assert comparison.differences("utilization").height == 0
    with pytest.raises(ValueError, match="Scenario 'Buy': This supply chain has no"):
        comparison.intervals(
            "utilization",
            station="Press",
        )
    with pytest.raises(ValueError, match="no production stations"):
        comparison.experiments["Buy"].intervals("mean_flow_time")


def test_a_run_without_stations_still_has_a_viewer_but_no_station_plots():
    model = Model()
    arrivals = model.source(
        name="Customers",
        interarrival=1,
    )
    model.route([arrivals, model.exit])
    result = model.run(duration=5)
    assert "FlowSim" in result.viewer().html
    with pytest.raises(ValueError, match="no stations"):
        result.plot_queue()


def test_run_level_metrics_apply_to_a_supply_chain_without_stations():
    # A supply chain cannot drain, so every run stops at closing, i.e.,
    # end_time is the duration and overtime is zero.
    experiment = beer_chain().experiment(
        duration=20,
        replications=3,
    )
    assert experiment.intervals("end_time")["mean"].to_list() == [20.0]
    assert experiment.intervals("overtime")["mean"].to_list() == [0.0]
    with pytest.raises(ValueError, match="no production stations"):
        experiment.intervals("mean_total_wait")
    system = beer_chain().run(duration=20).report().filter(pl.col("scope") == "system")
    assert system["metric"].to_list() == ["overtime", "end_time"]


def test_dropped_records_keep_every_measure_and_explain_the_loss(tmp_path):
    kept = service_network().experiment(
        duration=120,
        replications=3,
        seed=5,
    )
    dropped = service_network().experiment(
        duration=120,
        replications=3,
        seed=5,
        keep_records=False,
    )
    # The same seeds give the same runs, so every measure must match exactly.
    for table in ["summary", "stations", "stock_points"]:
        assert_frame_equal(getattr(kept, table), getattr(dropped, table))
    assert_frame_equal(kept.intervals(), dropped.intervals())
    assert_frame_equal(kept.runs[0].report(), dropped.runs[0].report())
    run = dropped.runs[0]
    for table in ["customers", "visits", "states", "activities", "failures"]:
        with pytest.raises(AttributeError, match="keep_records=True"):
            getattr(run, table)
    for call in [
        lambda: run.plot_queue(),
        lambda: run.plot_customer(1),
        lambda: run.viewer(),
        lambda: run.export(tmp_path / "run"),
    ]:
        with pytest.raises(ValueError, match="reads raw records"):
            call()
    assert "Raw records were dropped" in repr(run)
    assert "Raw records were dropped" in repr(dropped)
    assert "Raw records were dropped" not in repr(kept)
    dropped.export(tmp_path / "experiment")
    assert (tmp_path / "experiment" / "stations.csv").exists()
    with pytest.raises(ValueError, match="keep_records must be True or False"):
        service_network().experiment(
            duration=120,
            keep_records="no",
        )


def test_compare_passes_keep_records_to_each_scenario():
    comparison = compare(
        scenarios={"One": service_network(1), "Two": service_network(2)},
        duration=120,
        replications=2,
        keep_records=False,
    )
    for experiment in comparison.experiments.values():
        assert all(not run._records_kept for run in experiment.runs)
    assert comparison.differences().height > 0
