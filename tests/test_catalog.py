"""The metric and column catalog agrees with the tables a run produces."""

import numpy as np
import polars as pl
import pytest

import flowsim
from flowsim import compare, fit_all
from flowsim.catalog import COLUMNS, EXCLUDED, METRICS
from flowsim.fitting import _PARAMETER_COLUMNS
from flowsim.records import (
    ACTIVITY_SCHEMA,
    CUSTOMER_SCHEMA,
    FAILURE_SCHEMA,
    INTERVAL_SCHEMA,
    INVENTORY_SCHEMA,
    SHIPMENT_SCHEMA,
    STATE_SCHEMA,
    STATION_SCHEMA,
    STOCK_POINT_SCHEMA,
    VISIT_SCHEMA,
)
from tests.models import beer_chain, deterministic_queue, service_network

FIT_BASE_COLUMNS = [
    "rank",
    "family",
    "description",
    "mean",
    "sd",
    "p_negative",
    "aic",
    "ks",
]


@pytest.fixture(scope="module")
def service_run():
    return service_network().run(
        duration=60,
        seed=1,
    )


@pytest.fixture(scope="module")
def chain_run():
    return beer_chain().run(
        duration=30,
        seed=7,
    )


def column_names(table: str) -> set[str]:
    return {column for name, column in COLUMNS if name == table}


def test_every_column_is_documented_and_every_entry_exists(service_run, chain_run):
    experiment = service_network().experiment(
        duration=60,
        replications=3,
    )
    comparison = compare(
        scenarios={
            "One": service_network(service_capacity=1),
            "Two": service_network(service_capacity=2),
        },
        duration=60,
        replications=3,
    )
    fits = fit_all(np.random.default_rng(3).gamma(4, 1.5, 100))
    actual = {
        "customers": set(CUSTOMER_SCHEMA),
        "visits": set(VISIT_SCHEMA),
        "states": set(STATE_SCHEMA),
        "activities": set(ACTIVITY_SCHEMA),
        "failures": set(FAILURE_SCHEMA),
        "stations": set(STATION_SCHEMA) | set(service_run.stations.columns),
        "summary": set(service_run.summary.columns),
        "inventory": set(INVENTORY_SCHEMA) | set(chain_run.inventory.columns),
        "shipments": set(SHIPMENT_SCHEMA) | set(chain_run.shipments.columns),
        "stock_points": set(STOCK_POINT_SCHEMA) | set(chain_run.stock_points.columns),
        "intervals": (
            set(INTERVAL_SCHEMA)
            | set(experiment.intervals().columns)
            | set(comparison.intervals().columns)
            | set(comparison.differences().columns)
        ),
        "pooled": {"replication", "scenario"},
        "fits": set(FIT_BASE_COLUMNS) | set(_PARAMETER_COLUMNS),
    }
    assert "replication" in experiment.summary.columns
    assert "scenario" in comparison.summary.columns
    assert set(fits.table.columns) <= actual["fits"]
    for table, columns in actual.items():
        assert column_names(table) == columns, table
    # Nothing documents a table that has no columns here.
    assert {table for table, _ in COLUMNS} == set(actual)


def test_every_metric_is_a_numeric_column_of_its_table(service_run, chain_run):
    tables = {
        "summary": service_run.summary,
        "stations": service_run.stations,
        "stock_points": chain_run.stock_points,
    }
    for name, metric in METRICS.items():
        table = tables[metric.table]
        assert name in table.columns, name
        assert table.schema[name].is_numeric(), name


def test_every_numeric_column_is_a_metric_or_excluded_never_both(
    service_run,
    chain_run,
):
    tables = {
        "summary": service_run.summary,
        "stations": service_run.stations,
        "stock_points": chain_run.stock_points,
    }
    for table, frame in tables.items():
        for column, dtype in frame.schema.items():
            is_metric = column in METRICS and METRICS[column].table == table
            is_excluded = (table, column) in EXCLUDED
            if dtype.is_numeric():
                assert is_metric != is_excluded, (table, column)
    for table, column in EXCLUDED:
        assert (table, column) in COLUMNS
        assert not (column in METRICS and METRICS[column].table == table)
    # The two shared names stay system metrics, and the station columns are excluded.
    assert METRICS["arrivals"].scope == "system"
    assert METRICS["outside_at_close"].scope == "system"
    assert ("stations", "arrivals") in EXCLUDED
    assert ("stations", "outside_at_close") in EXCLUDED


def test_metrics_lists_one_row_per_metric_and_filters_by_scope():
    everything = flowsim.metrics()
    assert everything.columns == [
        "name",
        "scope",
        "table",
        "label",
        "units",
        "needs",
        "window",
        "meaning",
    ]
    assert everything.get_column("name").to_list() == list(METRICS)
    stations = flowsim.metrics("station")
    assert set(stations.get_column("scope")) == {"station"}
    assert set(stations.get_column("needs")) == {"station="}
    assert "max_queue" in stations.get_column("name").to_list()
    assert flowsim.metrics("system").get_column("needs").unique().to_list() == [""]
    row = everything.filter(pl.col("name") == "mean_wait").row(
        0,
        named=True,
    )
    assert row["units"] == "time unit"
    with pytest.raises(ValueError, match="system.*station.*stock_point"):
        flowsim.metrics("stations")


def test_explain_prints_metric_and_column_entries(capsys):
    flowsim.explain("mean_wait")
    printed = capsys.readouterr().out
    assert "Mean station waiting time" in printed
    assert "station scope" in printed
    assert 'experiment.intervals("mean_wait", station="Service")' in printed
    flowsim.explain("p95_wait")
    assert "run-level 95th percentile" in capsys.readouterr().out
    flowsim.explain("customer_id")
    printed = capsys.readouterr().out
    assert "customers table" in printed
    assert "visits table" in printed
    flowsim.explain("capacity")
    assert "a setting, not an outcome" in capsys.readouterr().out
    flowsim.explain("arrivals")
    printed = capsys.readouterr().out
    assert "summary table" in printed
    assert "Not a replication metric" in printed
    flowsim.explain("mean_wiat")
    assert "mean_wait" in capsys.readouterr().out
    flowsim.explain("zzzzzz")
    assert "no close matches" in capsys.readouterr().out


def test_experiment_errors_suggest_matches_and_explain_columns():
    experiment = deterministic_queue().experiment(
        duration=7,
        replications=3,
    )
    with pytest.raises(ValueError, match="mean_wait") as error:
        experiment.intervals("mean_wiat")
    assert "system metrics:" in str(error.value)
    assert "station metrics:" in str(error.value)
    with pytest.raises(ValueError, match="Close matches: Service"):
        experiment.intervals(
            "mean_wait",
            station="Servce",
        )
    with pytest.raises(ValueError, match="stations column.*a setting, not an outcome"):
        experiment.intervals("capacity")
    with pytest.raises(
        ValueError,
        match="column of the activities, customers, visits tables, not a replication metric",
    ):
        experiment.intervals("customer_id")


def test_comparison_errors_state_the_scope_and_suggest_matches():
    comparison = compare(
        scenarios={
            "One": deterministic_queue(),
            "Two": deterministic_queue(capacity=2),
        },
        duration=7,
        replications=2,
    )
    with pytest.raises(ValueError, match="Close matches: Service"):
        comparison.intervals(
            "mean_wait",
            station="Servce",
        )
    with pytest.raises(ValueError, match="mean_wait"):
        comparison.intervals("mean_wiat")
    with pytest.raises(ValueError, match="Close matches: Two"):
        comparison.differences(baseline="Tow")


def test_new_metrics_match_a_hand_calculation():
    # Customers arrive at 0, 1, 2 and each needs 2 units on one server.
    # Customer 1 serves over [0, 2), customer 2 over [2, 4), customer 3 over
    # [4, 6). At time 1 customer 2 waits, and at time 2 the completion frees the
    # server before customer 3 arrives, so one customer waits from 2 to 4 and
    # none waits afterward: max_queue = 1. All three exits (2, 4, 6) precede
    # closing at 7, so completed = 3. Services start at 0, 2, 4 and end at
    # 2, 4, 6, all inside [0, 7).
    experiment = deterministic_queue().experiment(
        duration=7,
        replications=4,
    )
    for metric, station, expected in [
        ("max_queue", "Service", 1.0),
        ("service_starts", "Service", 3.0),
        ("service_completions", "Service", 3.0),
        ("completed", None, 3.0),
    ]:
        row = experiment.intervals(
            metric,
            station=station,
        ).row(
            0,
            named=True,
        )
        assert row["mean"] == pytest.approx(expected), metric
        assert row["lower"] == pytest.approx(expected), metric
        assert row["upper"] == pytest.approx(expected), metric
