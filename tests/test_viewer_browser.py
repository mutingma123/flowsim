"""Exercise the saved viewers in a real browser when Chrome is available."""

import polars as pl
import pytest

from flowsim import Model, compare, moving_average, order_up_to
from tests.models import (
    beer_chain,
    combined_line,
    deterministic_queue,
    job_shop,
    service_network,
    two_station_queue,
)


@pytest.mark.parametrize("drain", [False, True])
def test_offline_viewer_controls_and_download(tmp_path, offline_page, drain):
    result = service_network().run(
        duration=480,
        seed=42,
        drain=drain,
    )
    viewer = tmp_path / "viewer.html"
    result.viewer(viewer)
    page = offline_page(viewer)
    page.wait_for_function("window.flowsimReady !== undefined")
    page.evaluate("window.flowsimReady")
    assert page.locator(".js-plotly-plot").count() == 4
    assert "Unfinished at closing" in page.locator("#cards").inner_text()
    if drain:
        assert (
            "had completed service or abandoned" in page.locator("#notice").inner_text()
        )
    assert page.locator("#station-choice option").all_text_contents() == [
        "Check-in",
        "Service",
    ]
    page.select_option("#station-choice", "Service")
    page.wait_for_function("document.getElementById('queues').data[2].visible === true")
    assert page.evaluate(
        "document.getElementById('queues').data.map(trace => trace.visible)"
    ) == [False, False, True, True]
    assert page.evaluate(
        "document.getElementById('waits').data.map(trace => trace.visible)"
    ) == [False, True]
    page.fill("#customer-choice", "2")
    page.click("#show-customer")
    assert "Customer 2 arrived" in page.locator("#customer-details").inner_text()
    # Customers without a type get no type column.
    assert "Type" not in page.locator("#customers thead").all_text_contents()[0]
    page.select_option("#status-choice", "in_service")
    # The expected counts come from the run, so this test checks the viewer's
    # filter and download rather than a seeded count.
    in_service = result.customers.filter(pl.col("status") == "in_service").height
    remaining = result.customers.get_column("exit_time").null_count()
    assert (in_service > 0) is not drain
    assert page.locator("#customers tbody tr").count() == in_service
    assert (
        f"{in_service} matching customers" in page.locator("#page-details").inner_text()
    )
    with page.expect_download() as download_info:
        page.click("#download-customers")
    download = download_info.value
    downloaded_path = tmp_path / download.suggested_filename
    download.save_as(downloaded_path)
    downloaded = pl.read_csv(
        source=downloaded_path,
        schema_overrides=result.customers.schema,
    )
    assert downloaded.height == result.customers.height
    assert downloaded.get_column("exit_time").null_count() == remaining


def test_viewer_shows_customer_types(tmp_path, offline_page):
    result = job_shop().run(
        duration=20,
        drain=True,
    )
    viewer = tmp_path / "viewer.html"
    result.viewer(viewer)
    page = offline_page(viewer)
    page.wait_for_function("window.flowsimReady !== undefined")
    page.evaluate("window.flowsimReady")
    headers = page.locator("#customers thead th").all_text_contents()
    assert headers[:3] == ["Customer ID", "Source", "Type"]
    types = page.locator("#customers tbody tr td:nth-child(3)").all_text_contents()
    assert types == ["A", "B"]
    page.fill("#customer-choice", "2")
    page.click("#show-customer")
    assert (
        "Customer 2 (type B) arrived" in page.locator("#customer-details").inner_text()
    )


def test_viewer_shows_abandoned_customers(tmp_path, offline_page):
    # Arrivals at 0, 1, and 2 need 5 each, and customer 2 leaves at 1 + 3 = 4.
    model = Model()
    callers = model.source(
        name="Callers",
        interarrival=1,
        first_arrival=0,
        limit=3,
    )
    desk = model.station(
        name="Desk",
        capacity=1,
        service_time=5,
        patience=3,
        abandon_from="waiting",
    )
    model.route([callers, desk, model.exit])
    result = model.run(
        duration=20,
        drain=True,
    )
    viewer = tmp_path / "viewer.html"
    result.viewer(viewer)
    page = offline_page(viewer)
    page.wait_for_function("window.flowsimReady !== undefined")
    page.evaluate("window.flowsimReady")
    assert "Abandoned customers: 1" in page.locator("#notice").inner_text()
    page.select_option("#status-choice", "abandoned")
    assert "1 matching customers" in page.locator("#page-details").inner_text()
    cells = page.locator("#customers tbody tr td").all_text_contents()
    assert cells[-2:] == ["abandoned", "Left system"]
    page.fill("#customer-choice", "2")
    page.click("#show-customer")
    assert "left without service at 4" in page.locator("#customer-details").inner_text()


def test_empty_run_downloads_use_export_columns(tmp_path, offline_page):
    model = Model()
    arrivals = model.source(
        name="Customers",
        interarrival=1,
        first_arrival=10,
    )
    service = model.station(
        name="Service",
        capacity=1,
        service_time=1,
    )
    model.route([arrivals, service, model.exit])
    result = model.run(duration=5)
    assert result.customers.height == result.visits.height == 0
    viewer = tmp_path / "viewer.html"
    result.viewer(viewer)
    page = offline_page(viewer)
    page.wait_for_function("window.flowsimReady !== undefined")
    for name in ["customers", "visits"]:
        with page.expect_download() as download_info:
            page.click(f"#download-{name}")
        path = tmp_path / f"{name}.csv"
        download_info.value.save_as(path)
        header = path.read_text().strip().split(",")
        assert header == [f'"{column}"' for column in getattr(result, name).columns]


def test_scenario_report_renders_intervals_offline(tmp_path, offline_page):
    comparison = compare(
        scenarios={
            "One server": deterministic_queue(),
            "Two servers": deterministic_queue(capacity=2),
        },
        duration=3,
        replications=3,
        drain=True,
    )
    viewer = tmp_path / "comparison.html"
    comparison.viewer(viewer)
    page = offline_page(viewer)
    page.wait_for_function("window.flowsimReady !== undefined")
    page.evaluate("window.flowsimReady")
    # Intervals, paired differences, and each replication's value.
    assert page.locator(".js-plotly-plot").count() == 3
    assert page.locator("#interval-table tbody tr").count() == 2
    assert page.locator("#difference-table tbody tr").count() == 1
    assert page.evaluate("document.getElementById('scenario-means').data[0].x") == [
        1,
        0,
    ]
    assert page.evaluate(
        "document.getElementById('scenario-differences').data[0].x"
    ) == [-1]


def test_experiment_report_renders_one_metric_offline(tmp_path, offline_page):
    # One server gives a mean station wait of 1 in every replication.
    experiment = deterministic_queue().experiment(
        duration=7,
        replications=3,
    )
    viewer = tmp_path / "experiment.html"
    experiment.viewer(
        viewer,
        metric="mean_wait",
    )
    page = offline_page(viewer)
    page.wait_for_function("document.querySelectorAll('.axis-note').length === 1")
    # Intervals and each replication's value, with no differences.
    assert page.locator(".js-plotly-plot").count() == 2
    assert page.locator("#interval-table tbody tr").count() == 1
    assert page.locator("#interval-table tr").all_inner_texts() == [
        "Station\tMean (minutes)\tLower limit (minutes)\tUpper limit (minutes)\tObserved runs",
        "Service\t1.000\t1.000\t1.000\t3",
    ]
    assert page.locator("#interval-title").inner_text() == (
        "Mean station waiting time at Service"
    )
    assert page.locator("#difference-section").is_hidden()
    assert page.evaluate("document.getElementById('scenario-means').data[0].x") == [1]
    assert page.evaluate("document.getElementById('replication-values').data[0].y") == [
        1,
        1,
        1,
    ]


def test_scenario_report_moves_axis_titles_below_narrow_charts(tmp_path, offline_page):
    comparison = compare(
        scenarios={
            "One server": deterministic_queue(),
            "Two servers": deterministic_queue(capacity=2),
        },
        duration=3,
        replications=3,
        drain=True,
    )
    viewer = tmp_path / "comparison.html"
    comparison.viewer(viewer)
    page = offline_page(viewer)
    page.wait_for_function("document.querySelectorAll('.axis-note').length === 2")
    title = "document.getElementById('scenario-means').layout.xaxis.title.text"
    note = "document.querySelector('.axis-note')"
    wide = page.evaluate(title)
    assert wide == "Mean total waiting time (minutes)"
    assert page.evaluate(f"{note}.hidden")
    page.set_viewport_size({"width": 400, "height": 900})
    page.wait_for_function(f"!{note}.hidden")
    assert page.evaluate(title) == ""
    assert page.evaluate(f"{note}.textContent") == wide
    page.set_viewport_size({"width": 1400, "height": 1000})
    page.wait_for_function(f"{note}.hidden")
    assert page.evaluate(title) == wide


def test_extended_viewer_shows_resource_states_rejections_and_paused_work(
    tmp_path, offline_page
):
    result = combined_line().run(
        duration=180,
        drain=True,
    )
    paused = result.activities.filter(pl.col("state") == "paused").to_dicts()
    assert paused
    viewer = tmp_path / "extensions.html"
    result.viewer(viewer)
    page = offline_page(viewer)
    page.wait_for_function("window.flowsimReady !== undefined")
    page.evaluate("window.flowsimReady")
    assert page.locator(".js-plotly-plot").count() == 5
    assert page.locator("#resources-section").is_visible()
    assert page.locator("#failure-records tbody tr").count() == result.failures.height
    assert "Rejected arrivals:" in page.locator("#notice").inner_text()
    page.select_option("#station-choice", "Finishing")
    page.wait_for_function(
        "document.getElementById('resources').data[6].visible === true"
    )
    # Assembly and Finishing each draw six resource traces.
    assert (
        page.evaluate(
            "document.getElementById('resources').data.map(trace => trace.visible)"
        )
        == [False] * 6 + [True] * 6
    )
    page.fill("#customer-choice", str(paused[0]["customer_id"]))
    page.click("#show-customer")
    page.wait_for_function("document.getElementById('timeline').data[2].x.length > 0")
    assert page.evaluate("document.getElementById('timeline').data[2].name") == "Paused"
    page.select_option("#status-choice", "rejected")
    rejected = result.summary.to_dicts()[0]["rejected"]
    assert (
        f"{rejected} matching customers" in page.locator("#page-details").inner_text()
    )


def test_viewer_line_choices_persist_across_stations_and_the_stacked_switch(
    tmp_path, engine_page
):
    result = combined_line().run(
        duration=180,
        drain=True,
    )
    viewer = tmp_path / "extensions.html"
    result.viewer(viewer)
    page = engine_page(viewer)
    page.wait_for_function("window.flowsimReady !== undefined")
    page.evaluate("window.flowsimReady")
    visible = "id => document.getElementById(id).data.map(trace => trace.visible)"
    names = "id => document.getElementById(id).data.map(trace => trace.name)"
    assert page.locator("#queues-series label").all_inner_texts() == [
        "Waiting",
        "Occupied servers",
    ]
    lines = ["Processing", "Blocked", "Paused", "Down", "Available", "Scheduled"]
    assert page.locator("#resources-series label").all_inner_texts() == lines
    assert "the lines overlap" in page.locator("#resources-reading").inner_text()
    # Clearing a box dims that line in the legend for the shown station only.
    page.uncheck("#resources-series input[data-series='Down']")
    page.wait_for_function(
        "document.getElementById('resources').data[3].visible === 'legendonly'"
    )
    assert page.evaluate(visible, "resources") == (
        [True] * 3 + ["legendonly"] + [True] * 2 + [False] * 6
    )
    page.uncheck("#queues-series input[data-series='Waiting']")
    # The choices hold for the next station.
    page.select_option("#station-choice", "Finishing")
    page.wait_for_function(
        "document.getElementById('resources').data[9].visible === 'legendonly'"
    )
    assert page.evaluate(visible, "resources") == (
        [False] * 6 + [True] * 3 + ["legendonly"] + [True] * 2
    )
    assert page.evaluate(visible, "queues") == [False, False, "legendonly", True]
    # A legend click toggles the same choice and its box.
    page.locator("#resources .legend .traces").filter(has_text="Paused").locator(
        ".legendtoggle"
    ).click()
    page.wait_for_function(
        "document.getElementById('resources').data[8].visible === 'legendonly'"
    )
    assert not page.is_checked("#resources-series input[data-series='Paused']")
    # The stacked view keeps the choices and adds idle servers.
    page.check("#resources-stacked")
    page.wait_for_function(
        "document.getElementById('resources').data.some(trace => trace.name === 'Idle')"
    )
    assert page.evaluate(names, "resources") == (
        ["Processing", "Blocked", "Paused", "Down", "Idle", "Scheduled"] * 2
    )
    assert page.evaluate(visible, "resources") == (
        [False] * 6 + [True, True, "legendonly", "legendonly", True, True]
    )
    assert page.locator("#resources-series label").all_inner_texts() == [
        "Processing",
        "Blocked",
        "Paused",
        "Down",
        "Idle",
        "Scheduled",
    ]
    assert "dashed scheduled line" in page.locator("#resources-reading").inner_text()
    page.select_option("#station-choice", "Assembly")
    page.wait_for_function(
        "document.getElementById('resources').data[0].visible === true"
    )
    assert page.evaluate(visible, "resources") == (
        [True, True, "legendonly", "legendonly", True, True] + [False] * 6
    )
    page.uncheck("#resources-stacked")
    page.wait_for_function(
        "document.getElementById('resources').data[4].name === 'Available'"
    )
    assert page.evaluate(visible, "resources") == (
        [True, True, "legendonly", "legendonly", True, True] + [False] * 6
    )


def test_supply_viewer_switches_stock_points_and_downloads_records(
    tmp_path, offline_page
):
    result = beer_chain().run(
        duration=30,
        seed=4,
        warmup=5,
    )
    viewer = tmp_path / "supply.html"
    result.viewer(viewer)
    page = offline_page(viewer)
    page.wait_for_function("window.flowsimReady !== undefined")
    page.evaluate("window.flowsimReady")
    assert page.locator(".js-plotly-plot").count() == 2
    assert not page.locator("#production-section").is_visible()
    assert not page.locator("#download-jobs").is_visible()
    assert page.locator("#stock-points tbody tr").count() == 4
    assert page.locator("#stock-choice option").all_text_contents() == [
        "Retailer",
        "Wholesaler",
        "Distributor",
        "Factory",
    ]
    # Consumer demand plus one order trace per stage.
    assert page.evaluate("document.getElementById('orders').data.length") == 5
    page.select_option("#stock-choice", "Factory")
    page.wait_for_function(
        "document.getElementById('inventory').data[12].visible === true"
    )
    # Each stock point draws four traces.
    assert (
        page.evaluate(
            "document.getElementById('inventory').data.map(trace => trace.visible)"
        )
        == [False] * 12 + [True] * 4
    )
    for name in ["inventory", "shipments"]:
        with page.expect_download() as download_info:
            page.click(f"#download-{name}")
        path = tmp_path / f"{name}.csv"
        download_info.value.save_as(path)
        downloaded = pl.read_csv(
            source=path,
            schema_overrides=getattr(result, name).schema,
        )
        assert downloaded.height == getattr(result, name).height
        assert downloaded.columns == getattr(result, name).columns


def test_supply_viewer_shows_production_stations(tmp_path, offline_page):
    # The factory orders 50 each week in jobs of 16, 16, 16, and 2, and every
    # job is cut and then packed.
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
    cut = model.station(
        name="Cut",
        capacity=1,
        service_time=1 / 32,
    )
    pack = model.station(
        name="Pack",
        capacity=1,
        service_time=1 / 64,
    )
    model.route([factory, cut, pack, factory])
    model.supply(
        [consumers, factory],
        period=1,
    )
    result = model.run(duration=4)
    viewer = tmp_path / "production.html"
    result.viewer(viewer)
    page = offline_page(viewer)
    page.wait_for_function("window.flowsimReady !== undefined")
    page.evaluate("window.flowsimReady")
    assert page.locator(".js-plotly-plot").count() == 4
    assert page.locator("#production-section").is_visible()
    assert page.locator("#stations tbody tr").count() == 2
    summary = result.summary.row(0, named=True)
    details = page.locator("#production-details").inner_text()
    assert f"{summary['cohort_completions']} finished" in details
    assert page.locator("#station-choice option").all_text_contents() == [
        "Cut",
        "Pack",
    ]
    page.select_option("#station-choice", "Pack")
    page.wait_for_function("document.getElementById('queues').data[2].visible === true")
    assert page.evaluate(
        "document.getElementById('queues').data.map(trace => trace.visible)"
    ) == [False, False, True, True]
    with page.expect_download() as download_info:
        page.click("#download-jobs")
    path = tmp_path / "jobs.csv"
    download_info.value.save_as(path)
    jobs = pl.read_csv(
        source=path,
        schema_overrides=result.customers.schema,
    )
    assert jobs.columns == result.customers.columns
    assert jobs.get_column("quantity").to_list() == [16, 16, 16, 2] * 4


def click_point(page, index):
    """Click a replication point where it is drawn, through Plotly's drag layer."""
    point = page.locator("#replication-values .point").nth(index)
    point.scroll_into_view_if_needed()
    box = point.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)


def ready(page, name="flowsimReady"):
    page.wait_for_function(f"window.{name} !== undefined")
    page.evaluate(f"window.{name}")


def test_comparison_dashboard_switches_metrics_and_opens_runs(tmp_path, engine_page):
    comparison = compare(
        scenarios={
            "Base": combined_line(),
            "Pause": combined_line(shift_end="pause"),
        },
        duration=120,
        replications=3,
    )
    viewer = tmp_path / "comparison.html"
    comparison.viewer(
        viewer,
        metric="utilization",
        station="Finishing",
        baseline="Pause",
    )
    page = engine_page(viewer)
    ready(page)
    assert page.input_value("#metric-choice") == "utilization"
    assert page.locator("#location-choice option:checked").inner_text() == "Finishing"
    assert page.input_value("#baseline-choice") == "Pause"
    assert page.locator("#interval-title").inner_text() == (
        "Occupied / installed capacity at Finishing"
    )
    assert page.locator("#difference-title").inner_text() == "Difference from Pause"
    finishing = comparison.intervals(
        "utilization",
        station="Finishing",
    )
    assert page.evaluate(
        "document.getElementById('scenario-means').data[0].x"
    ) == pytest.approx(finishing.get_column("mean").to_list())
    # A system metric hides the location menu, and the baseline menu redraws
    # the paired differences.
    page.select_option("#metric-choice", "mean_total_wait")
    page.wait_for_function(
        "document.getElementById('interval-title').textContent === "
        "'Mean total waiting time'"
    )
    assert page.locator("#location-choice").is_hidden()
    page.select_option("#baseline-choice", "Base")
    page.wait_for_function(
        "document.getElementById('difference-title').textContent === "
        "'Difference from Base'"
    )
    paired = comparison.differences("mean_total_wait", baseline="Base")
    assert page.evaluate(
        "document.getElementById('scenario-differences').data[0].x"
    ) == pytest.approx(paired.get_column("mean").to_list())
    runs = comparison.experiments["Pause"].summary.sort("replication")
    assert page.evaluate(
        "document.getElementById('replication-values').data[1].y"
    ) == pytest.approx(runs.get_column("mean_total_wait").to_list())
    # Opening Pause's second run shows its single-run view, with the
    # server-state boxes and stacked switch, on the same page.
    assert page.locator("#run-panel").is_hidden()
    page.select_option(
        "#run-choice", label=page.locator("#run-choice option").nth(4).inner_text()
    )
    page.click("#open-run")
    ready(page, "flowsimRunReady")
    run = comparison.experiments["Pause"].runs[1]
    assert page.locator("#run-heading").inner_text() == (
        f"Pause, replication 2 (seed {run.settings.seed})"
    )
    arrivals = run.summary.row(0, named=True)["arrivals"]
    assert page.locator("#cards .card").first.inner_text().endswith(str(arrivals))
    assert page.locator("#resources-series label").count() == 6
    page.check("#resources-stacked")
    page.wait_for_function(
        "document.getElementById('resources').data.some(trace => trace.name === 'Idle')"
    )
    # Opening another run replaces the view, and closing it empties the panel.
    page.select_option(
        "#run-choice", label=page.locator("#run-choice option").first.inner_text()
    )
    page.click("#open-run")
    ready(page, "flowsimRunReady")
    assert page.locator("#run-heading").inner_text().startswith("Base, replication 1 ")
    assert page.locator("#queues").count() == 1
    assert not page.is_checked("#resources-stacked")
    page.click("#close-run")
    assert page.locator("#run-panel").is_hidden()
    assert page.locator("#run-root > *").count() == 0


def test_a_replication_point_opens_its_run(tmp_path, offline_page):
    experiment = deterministic_queue().experiment(
        duration=7,
        replications=3,
    )
    viewer = tmp_path / "experiment.html"
    experiment.viewer(viewer)
    page = offline_page(viewer)
    ready(page)
    click_point(page, 2)
    ready(page, "flowsimRunReady")
    seed = experiment.runs[2].settings.seed
    assert page.locator("#run-heading").inner_text() == f"Replication 3 (seed {seed})"
    assert page.input_value("#run-choice") == "2"


def test_dashboard_without_records_shows_the_overview_only(tmp_path, offline_page):
    experiment = deterministic_queue().experiment(
        duration=7,
        replications=3,
        keep_records=False,
    )
    viewer = tmp_path / "experiment.html"
    experiment.viewer(viewer)
    page = offline_page(viewer)
    ready(page)
    assert "keep_records=True" in page.locator("#replication-reading").inner_text()
    assert page.locator("#run-toolbar").is_hidden()
    click_point(page, 0)
    assert page.locator("#run-panel").is_hidden()


def test_supply_chain_dashboard_opens_the_supply_chain_run_view(tmp_path, offline_page):
    experiment = beer_chain().experiment(
        duration=20,
        replications=2,
    )
    viewer = tmp_path / "chain.html"
    experiment.viewer(viewer, metric="fill_rate", stock_point="Factory")
    page = offline_page(viewer)
    ready(page)
    assert page.locator("#location-label").inner_text() == "Stock point"
    assert page.locator("#location-choice option:checked").inner_text() == "Factory"
    page.click("#open-run")
    ready(page, "flowsimRunReady")
    assert (
        page.locator(
            "#run-root #orders .js-plotly-plot, #run-root #orders.js-plotly-plot"
        ).count()
        == 1
    )
    assert page.locator("#stock-choice option").all_text_contents() == [
        "Retailer",
        "Wholesaler",
        "Distributor",
        "Factory",
    ]


def test_a_point_opens_its_own_scenario_where_another_lacks_the_station(
    tmp_path, offline_page
):
    comparison = compare(
        scenarios={
            "Without": deterministic_queue(),
            "With": two_station_queue(),
        },
        duration=7,
        replications=2,
    )
    viewer = tmp_path / "comparison.html"
    # A named station must exist in every scenario, so the page's menu
    # chooses Check.
    comparison.viewer(viewer, metric="mean_wait")
    page = offline_page(viewer)
    ready(page)
    page.select_option("#location-choice", label="Check")
    page.wait_for_function(
        "document.getElementById('interval-title').textContent.endsWith('Check')"
    )
    assert "No other scenario shares this location" in (
        page.locator("#difference-missing").inner_text()
    )
    click_point(page, 1)
    ready(page, "flowsimRunReady")
    seed = comparison.experiments["With"].runs[1].settings.seed
    assert page.locator("#run-heading").inner_text() == (
        f"With, replication 2 (seed {seed})"
    )
    assert page.locator("#station-choice option").all_text_contents() == [
        "Service",
        "Check",
    ]
