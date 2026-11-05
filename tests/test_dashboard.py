"""Experiment and comparison dashboards: their data, runs, and checks."""

import json

import pytest
from plotly.offline import get_plotlyjs

from flowsim import compare
from flowsim.catalog import STATION_METRICS, SYSTEM_METRICS
from flowsim.plots import page_template
from tests.models import (
    deterministic_queue,
    embedded_json,
    queue_comparison,
    two_station_queue,
)


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
    data = embedded_json(page, "dashboard-data")
    assert data["scenarios"] == [None]
    assert data["initial"] == {
        "metric": "mean_wait",
        "location": None,
        "baseline": None,
    }
    entry = next(item for item in data["metrics"] if item["name"] == "mean_wait")
    assert entry["locations"] == ["Service"]
    assert entry["units"] == "minutes"
    (view,) = entry["views"]
    assert view["title"] == "Mean station waiting time at Service"
    assert [
        (row["station"], row["mean"], row["lower"], row["upper"], row["observed_runs"])
        for row in view["intervals"]
    ] == [("Service", 1.0, 1.0, 1.0, 3)]
    assert view["changes"] == {}
    assert view["runs"]["data"][0]["y"] == [1.0, 1.0, 1.0]
    # The menu lists every metric that applies, in catalog order, so a
    # service network lists no stock-point metric.
    assert [item["name"] for item in data["metrics"]] == [
        *SYSTEM_METRICS,
        *STATION_METRICS,
    ]
    assert "__" + "DASHBOARD_JSON" + "__" not in page


def test_comparison_dashboard_holds_every_metric_baseline_and_run(tmp_path):
    # One server gives a mean station wait of 1 and two servers give 0 in
    # every replication, so each paired difference is -1 from One and +1
    # from Two.
    comparison = queue_comparison(replications=3)
    page = comparison.viewer(
        metric="mean_wait",
        station="Service",
        baseline="Two",
    ).html
    data = embedded_json(page, "dashboard-data")
    assert data["scenarios"] == ["One", "Two"]
    assert data["initial"] == {
        "metric": "mean_wait",
        "location": "Service",
        "baseline": "Two",
    }
    assert [item["name"] for item in data["metrics"]] == [
        *SYSTEM_METRICS,
        *STATION_METRICS,
    ]
    entry = next(item for item in data["metrics"] if item["name"] == "mean_wait")
    (view,) = entry["views"]
    assert [(row["scenario"], row["mean"]) for row in view["intervals"]] == [
        ("One", 1.0),
        ("Two", 0.0),
    ]
    for baseline, scenario, difference in [("One", "Two", -1.0), ("Two", "One", 1.0)]:
        (row,) = view["changes"][baseline]["intervals"]
        assert (row["scenario"], row["baseline"], row["mean"]) == (
            scenario,
            baseline,
            difference,
        )
    traces = view["runs"]["data"]
    assert [trace["y"] for trace in traces] == [[1.0, 1.0, 1.0], [0.0, 0.0, 0.0]]
    assert traces[1]["customdata"] == [[1, 0], [1, 1], [1, 2]]
    # Each run's records sit in their own element, as its run page holds them.
    for scenario, (name, experiment) in enumerate(comparison.experiments.items()):
        for index, run in enumerate(experiment.runs):
            embedded = embedded_json(page, f"run-{scenario}-{index}")
            single = embedded_json(run.viewer().html, "result-data")
            assert embedded == single
            assert data["runs"][scenario][index]["label"] == (
                f"{name}, replication {index + 1} (seed {run.settings.seed})"
            )
    # Plotly and the shared template appear once, and no figure repeats it.
    assert page.count(get_plotlyjs()[:400]) == 1
    assert embedded_json(page, "plot-template") == page_template()
    assert '"template"' not in json.dumps(data)
    assert '"template"' not in json.dumps(embedded_json(page, "run-0-0"))


def test_dashboard_without_records_holds_no_runs():
    comparison = queue_comparison(
        replications=3,
        keep_records=False,
    )
    # compare passes keep_records to every scenario's runs, not only some.
    for experiment in comparison.experiments.values():
        assert all(not run.records_kept for run in experiment.runs)
    for page in [comparison.viewer().html, comparison.experiments["One"].viewer().html]:
        data = embedded_json(page, "dashboard-data")
        assert data["records"] is False
        assert '<script id="run-' not in page
        assert len(data["runs"][0]) == 3


def test_dashboard_requests_are_checked_before_the_page_is_built():
    comparison = queue_comparison(replications=2)
    with pytest.raises(ValueError, match="Close matches"):
        comparison.viewer(metric="mean_wiat")
    with pytest.raises(ValueError, match="Unknown baseline scenario"):
        comparison.viewer(baseline="Three")
    with pytest.raises(ValueError, match="takes no station="):
        comparison.experiments["One"].viewer(station="Service")


def test_replication_points_keep_their_scenario_where_another_lacks_the_station():
    comparison = compare(
        scenarios={
            "Without": deterministic_queue(),
            "With": two_station_queue(),
        },
        duration=7,
        replications=2,
    )
    data = embedded_json(comparison.viewer().html, "dashboard-data")
    entry = next(item for item in data["metrics"] if item["name"] == "mean_wait")
    assert entry["locations"] == ["Service", "Check"]
    service, check = entry["views"]
    assert [trace["customdata"] for trace in service["runs"]["data"]] == [
        [[0, 0], [0, 1]],
        [[1, 0], [1, 1]],
    ]
    # Only "With" has Check, and its points still open its own runs, in its
    # own color.
    (trace,) = check["runs"]["data"]
    assert trace["name"] == "With"
    assert trace["customdata"] == [[1, 0], [1, 1]]
    assert trace["marker"]["color"] == service["runs"]["data"][1]["marker"]["color"]
    assert [row["scenario"] for row in check["intervals"]] == ["With"]
    assert check["changes"]["Without"] is None
