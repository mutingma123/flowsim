"""Raw records and duration-weighted summaries with explicit censoring."""

from __future__ import annotations

import difflib
import html
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

import numpy as np
import polars as pl
from scipy.stats import t

from flowsim import __version__
from flowsim.validation import number
from flowsim.viewer import Viewer

if TYPE_CHECKING:
    import networkx as nx
    from plotly.graph_objects import Figure

CUSTOMER_SCHEMA = {
    "customer_id": pl.Int64,
    "source": pl.String,
    "customer_type": pl.String,
    "quantity": pl.Float64,
    "arrival_time": pl.Float64,
    "exit_time": pl.Float64,
    "abandon_time": pl.Float64,
    "flow_time": pl.Float64,
    "total_wait": pl.Float64,
    "total_blocked": pl.Float64,
    "admitted": pl.Boolean,
    "admission_time": pl.Float64,
    "outside_wait": pl.Float64,
    "status": pl.String,
    "station": pl.String,
}
VISIT_SCHEMA = {
    "customer_id": pl.Int64,
    "source": pl.String,
    "customer_type": pl.String,
    "station": pl.String,
    "arrival_time": pl.Float64,
    "service_start": pl.Float64,
    "service_end": pl.Float64,
    "departure_time": pl.Float64,
    "abandon_time": pl.Float64,
    "server_id": pl.Int64,
    "blocked_time": pl.Float64,
    "wait_time": pl.Float64,
    "service_time": pl.Float64,
}
STATE_SCHEMA = {
    "station": pl.String,
    "time": pl.Float64,
    "waiting": pl.Int64,
    "busy": pl.Int64,
    "processing": pl.Int64,
    "blocked": pl.Int64,
    "paused": pl.Int64,
    "down": pl.Int64,
    "scheduled": pl.Int64,
    "available": pl.Int64,
    "outside": pl.Int64,
}
ACTIVITY_SCHEMA = {
    "customer_id": pl.Int64,
    "station": pl.String,
    "server_id": pl.Int64,
    "state": pl.String,
    "start": pl.Float64,
    "end": pl.Float64,
}
FAILURE_SCHEMA = {
    "station": pl.String,
    "server_id": pl.Int64,
    "failure_time": pl.Float64,
    "time_to_failure": pl.Float64,
    "repair_time": pl.Float64,
    "repair_end": pl.Float64,
}
# The stations table's column types. STATION_SCHEMA, below the catalog, puts
# them in display order.
_STATION_TYPES = {
    "station": pl.String,
    "capacity": pl.Int64,
    "arrivals": pl.Int64,
    "wait_arrivals": pl.Int64,
    "service_starts": pl.Int64,
    "service_completions": pl.Int64,
    "wait_observations": pl.Int64,
    "waiting_at_close": pl.Int64,
    "occupied_at_close": pl.Int64,
    "waiting_at_end": pl.Int64,
    "occupied_at_end": pl.Int64,
    "blocked_at_close": pl.Int64,
    "paused_at_close": pl.Int64,
    "outside_at_close": pl.Int64,
    "mean_wait": pl.Float64,
    "p95_wait": pl.Float64,
    "mean_queue": pl.Float64,
    "max_queue": pl.Int64,
    "utilization": pl.Float64,
    "processing_utilization": pl.Float64,
    "blocking_fraction": pl.Float64,
    "downtime_fraction": pl.Float64,
    "mean_scheduled_servers": pl.Float64,
    "mean_available_servers": pl.Float64,
    "mean_outside_queue": pl.Float64,
    "staffed_utilization": pl.Float64,
}
# One row per stock point and review period. Stock columns are end-of-period
# values after the review's order, and flow columns are totals for the period.
INVENTORY_SCHEMA = {
    "stock_point": pl.String,
    "period": pl.Int64,
    "time": pl.Float64,
    "received": pl.Float64,
    "demand": pl.Float64,
    "filled": pl.Float64,
    "shipped": pl.Float64,
    "lost": pl.Float64,
    "on_hand": pl.Float64,
    "backorders": pl.Float64,
    "on_order": pl.Float64,
    "position": pl.Float64,
    "forecast": pl.Float64,
    "target": pl.Float64,
    "order_quantity": pl.Float64,
}
SHIPMENT_SCHEMA = {
    "sender": pl.String,
    "receiver": pl.String,
    "quantity": pl.Float64,
    "ship_time": pl.Float64,
    "lead_time": pl.Float64,
    "arrival_time": pl.Float64,
}
STOCK_POINT_SCHEMA = {
    "stock_point": pl.String,
    "periods": pl.Int64,
    "mean_demand": pl.Float64,
    "mean_order": pl.Float64,
    "demand_variance": pl.Float64,
    "order_variance": pl.Float64,
    "bullwhip_ratio": pl.Float64,
    "fill_rate": pl.Float64,
    "mean_on_hand": pl.Float64,
    "mean_backorders": pl.Float64,
    "lost_units": pl.Float64,
}
# The top supplier's name in the shipments table. It has unlimited stock.
SUPPLIER = "Supplier"
# State counts integrated over time for the station table.
AREA_FIELDS = [
    "waiting",
    "busy",
    "processing",
    "blocked",
    "down",
    "scheduled",
    "available",
    "outside",
]


class Status(StrEnum):
    """A customer's status, as written to the customers table."""

    OUTSIDE = "outside"
    WAITING = "waiting"
    IN_SERVICE = "in_service"
    BLOCKED = "blocked"
    PAUSED = "paused"
    REJECTED = "rejected"
    ABANDONED = "abandoned"
    COMPLETED = "completed"


class Phase(StrEnum):
    """A server's phase. Activity rows record every phase except idle."""

    IDLE = "idle"
    PROCESSING = "processing"
    BLOCKED = "blocked"
    PAUSED = "paused"


# The run builds one record per row, and each record's fields equal its schema's
# columns in order (tests check this). Slots make a misspelled field an error
# rather than a silent extra key.
@dataclass(
    slots=True,
    kw_only=True,
)
class _Customer:
    customer_id: int
    source: str
    # None for a customer from a source without types.
    customer_type: str | None = None
    # Units in a production job, or None for a customer from a source.
    quantity: float | None = None
    arrival_time: float
    exit_time: float | None = None
    abandon_time: float | None = None
    flow_time: float | None = None
    total_wait: float = 0.0
    total_blocked: float = 0.0
    admitted: bool = False
    admission_time: float | None = None
    outside_wait: float | None = None
    # The customer's process sets a status when it starts, at the arrival time.
    status: Status | None = None
    station: str | None = None


@dataclass(
    slots=True,
    kw_only=True,
)
class _Visit:
    customer_id: int
    source: str
    customer_type: str | None = None
    station: str
    arrival_time: float
    service_start: float | None = None
    service_end: float | None = None
    departure_time: float | None = None
    abandon_time: float | None = None
    server_id: int | None = None
    blocked_time: float | None = None
    wait_time: float | None = None
    service_time: float


@dataclass(
    slots=True,
    kw_only=True,
)
class _State:
    station: str
    time: float
    waiting: int
    busy: int
    processing: int
    blocked: int
    paused: int
    down: int
    scheduled: int
    available: int
    outside: int


@dataclass(
    slots=True,
    kw_only=True,
)
class _Activity:
    customer_id: int
    station: str
    server_id: int
    state: Phase
    start: float
    end: float | None = None


@dataclass(
    slots=True,
    kw_only=True,
)
class _Failure:
    station: str
    server_id: int
    failure_time: float
    time_to_failure: float
    repair_time: float
    repair_end: float | None = None


@dataclass(
    slots=True,
    kw_only=True,
)
class _Inventory:
    stock_point: str
    period: int
    time: float
    received: float
    demand: float
    filled: float
    shipped: float
    lost: float
    on_hand: float
    backorders: float
    on_order: float
    position: float
    forecast: float
    target: float
    order_quantity: float


@dataclass(
    slots=True,
    kw_only=True,
)
class _Shipment:
    sender: str
    receiver: str
    quantity: float
    ship_time: float
    lead_time: float
    arrival_time: float | None = None


def _frame(records: list, schema: dict[str, pl.DataType]) -> pl.DataFrame:
    """Build a table from records, reading each column by its field name.

    Polars would match dataclass fields to the schema by position and cast
    mismatches silently, so the columns are gathered by name instead.
    """
    return pl.DataFrame(
        data={
            column: [getattr(record, column) for record in records] for column in schema
        },
        schema=schema,
    )


@dataclass(frozen=True)
class Metric:
    """A replication metric: where it comes from, how it reads, and what it means.

    The kind sets units and number formats: "time", "rate", "fraction",
    "servers", "customers", "units", "variance", or "ratio". The table is the
    per-run table that holds the metric as a column ("summary", "stations", or
    "stock_points"), and the window names the cohort or period it measures.
    """

    scope: str
    label: str
    kind: str
    table: str
    meaning: str
    window: str


_WARMUP_WINDOW = "[warmup, duration)"
_ARRIVAL_COHORT = "arrivals at or after warmup"
_FLOW_COHORT = "arrivals at or after warmup with observed exits"
_WAIT_COHORT = "visits admitted at or after warmup with observed starts"
_PERIODS = "review periods at or after warmup"

# One row per replication metric: name, scope, label, kind, window, meaning.
# The table follows from the scope. Each meaning is one plain sentence.
_METRIC_ROWS = [
    # System metrics, in the summary table.
    (
        "mean_total_wait",
        "system",
        "Mean total waiting time",
        "time",
        _FLOW_COHORT,
        "Mean total time that a completed customer waited before service, "
        "summed over its stations and including any wait outside the first station.",
    ),
    (
        "mean_flow_time",
        "system",
        "Mean flow time",
        "time",
        _FLOW_COHORT,
        "Mean time from system arrival to exit for completed customers.",
    ),
    (
        "throughput",
        "system",
        "Throughput during operating hours",
        "rate",
        _WARMUP_WINDOW,
        "Customers who exit during the operating window, whenever they arrived, "
        "divided by the window's length.",
    ),
    (
        "remaining_at_close",
        "system",
        "Customers present at closing",
        "customers",
        "at closing",
        "Customers who were not rejected and had neither exited nor abandoned "
        "before closing, including customers still waiting outside the first station.",
    ),
    (
        "completed_at_close",
        "system",
        "Customers completed before closing",
        "customers",
        "before closing",
        "Customers who exit before closing, whenever they arrived.",
    ),
    (
        "remaining",
        "system",
        "Customers unfinished at the end",
        "customers",
        "at the end of the run",
        "Customers who were not rejected and had neither completed nor abandoned "
        "when the run ended.",
    ),
    (
        "overtime",
        "system",
        "Time to finish after closing",
        "time",
        "whole run",
        "Time from closing to the end of the run, i.e., end_time minus duration, "
        "which is zero in a run that is not drained and in a drained run whose "
        "customers all finish by closing.",
    ),
    (
        "mean_wip",
        "system",
        "Time-average customers in the system",
        "customers",
        _WARMUP_WINDOW,
        "Time-average number of admitted customers in the system, which excludes "
        "customers still waiting outside the first station.",
    ),
    (
        "rejected",
        "system",
        "Rejected arrivals",
        "customers",
        "whole run",
        "Arrivals that were rejected on arrival.",
    ),
    (
        "admitted",
        "system",
        "Admitted customers",
        "customers",
        "whole run",
        "Customers admitted to the first station, including admissions after closing.",
    ),
    (
        "measurement_rejected",
        "system",
        "Rejected arrivals after warm-up",
        "customers",
        _WARMUP_WINDOW,
        "Arrivals at or after warmup that were rejected on arrival.",
    ),
    (
        "measurement_admitted",
        "system",
        "Admissions after warm-up, before closing",
        "customers",
        _WARMUP_WINDOW,
        "Customers admitted to the first station during the operating window.",
    ),
    (
        "abandonment_rate",
        "system",
        "Arrivals after warm-up who abandon",
        "fraction",
        "arrivals at or after warmup, including rejected arrivals",
        "Share of arrivals at or after warmup, counting rejected arrivals in the "
        "denominator, who abandoned at any time in the run, including after "
        "closing in a drained run.",
    ),
    (
        "mean_total_blocked",
        "system",
        "Mean time blocked between stations",
        "time",
        _FLOW_COHORT,
        "Mean time that a completed customer was held at a station after service "
        "because the next station could not accept it.",
    ),
    (
        "mean_outside_wait",
        "system",
        "Mean waiting time outside",
        "time",
        _FLOW_COHORT,
        "Mean time that a completed customer waited outside the first station "
        "before admission, which is zero when it was admitted on arrival.",
    ),
    (
        "arrivals",
        "system",
        "Arrivals",
        "customers",
        "whole run",
        "Customers who arrived during the run, including rejected arrivals.",
    ),
    (
        "admitted_at_close",
        "system",
        "Customers admitted before closing",
        "customers",
        "before closing",
        "Customers admitted to the first station before closing.",
    ),
    (
        "outside_at_close",
        "system",
        "Customers outside at closing",
        "customers",
        "at closing",
        "Customers who were not rejected and had neither been admitted nor "
        "abandoned before closing, so they were waiting outside the first station.",
    ),
    (
        "abandoned",
        "system",
        "Customers who abandoned",
        "customers",
        "whole run",
        "Customers who left without service, including abandonments after closing.",
    ),
    (
        "completed",
        "system",
        "Customers completed",
        "customers",
        "at the end of the run",
        "Customers who completed service, including completions after closing "
        "when the run continues past it.",
    ),
    (
        "after_close_completions",
        "system",
        "Completions after closing",
        "customers",
        "at or after closing",
        "Customers who exit at or after closing, during the continuation of a "
        "drained run.",
    ),
    (
        "end_time",
        "system",
        "End of service",
        "time",
        "whole run",
        "Simulation time at which the run stopped, which is the closing time in "
        "a run that is not drained and, in a drained run, the later of closing "
        "and the last exit or abandonment.",
    ),
    (
        "measurement_arrivals",
        "system",
        "Arrivals after warm-up",
        "customers",
        _WARMUP_WINDOW,
        "Arrivals at or after warmup, including rejected arrivals, which form the "
        "denominator of the abandonment rate.",
    ),
    (
        "measurement_abandoned",
        "system",
        "Abandonments after warm-up, before closing",
        "customers",
        _WARMUP_WINDOW,
        "Customers whose abandonment time falls in the operating window.",
    ),
    (
        "cohort_arrivals",
        "system",
        "Customers in the arrival cohort",
        "customers",
        _ARRIVAL_COHORT,
        "Customers who arrived at or after warmup and were not rejected, whose "
        "completed members form the cohort behind the flow-time and total-wait "
        "averages.",
    ),
    (
        "measurement_completions",
        "system",
        "Completions after warm-up, before closing",
        "customers",
        _WARMUP_WINDOW,
        "Customers who exit during the operating window, which is the numerator "
        "of throughput.",
    ),
    (
        "cohort_completions",
        "system",
        "Completed customers in the arrival cohort",
        "customers",
        _FLOW_COHORT,
        "Members of the arrival cohort whose exits were observed.",
    ),
    (
        "cohort_remaining",
        "system",
        "Unfinished customers in the arrival cohort",
        "customers",
        _ARRIVAL_COHORT,
        "Members of the arrival cohort who had neither completed nor abandoned "
        "when the run ended.",
    ),
    # Station metrics, in the stations table.
    (
        "mean_wait",
        "station",
        "Mean station waiting time",
        "time",
        _WAIT_COHORT,
        "Mean time from a visit's admission to the station's line until its "
        "service started, which excludes time spent outside a full finite buffer "
        "or blocked upstream and excludes visits that abandoned or had not started.",
    ),
    (
        "mean_queue",
        "station",
        "Time-average customers waiting",
        "customers",
        _WARMUP_WINDOW,
        "Time-average number of customers waiting in the station's line, "
        "excluding customers waiting outside a finite buffer.",
    ),
    (
        "utilization",
        "station",
        "Occupied / installed capacity",
        "fraction",
        _WARMUP_WINDOW,
        "Occupied-server time as a share of installed capacity times the window "
        "length, where an occupied server holds a job that is processing, "
        "paused, or blocked.",
    ),
    (
        "p95_wait",
        "station",
        "95th percentile station waiting time",
        "time",
        _WAIT_COHORT,
        "The 95th percentile of the run's observed visit waits, interpolated "
        "linearly between the two nearest order statistics, so an interval across "
        "replications estimates the expected run-level 95th percentile and not "
        "the 95th percentile of all customers' waits pooled.",
    ),
    (
        "processing_utilization",
        "station",
        "Processing / installed capacity",
        "fraction",
        _WARMUP_WINDOW,
        "Server time spent processing as a share of installed capacity times "
        "the window length.",
    ),
    (
        "blocking_fraction",
        "station",
        "Blocked / installed capacity",
        "fraction",
        _WARMUP_WINDOW,
        "Server time spent blocked as a share of installed capacity times the "
        "window length.",
    ),
    (
        "downtime_fraction",
        "station",
        "Down / installed capacity",
        "fraction",
        _WARMUP_WINDOW,
        "Server time spent down as a share of installed capacity times the "
        "window length, which can overlap paused and blocked time and so must not "
        "be added to the other shares.",
    ),
    (
        "staffed_utilization",
        "station",
        "Processing / available capacity",
        "fraction",
        _WARMUP_WINDOW,
        "Server time spent processing as a share of available-server time, "
        "which is missing when no server was available at any time in the window.",
    ),
    (
        "mean_scheduled_servers",
        "station",
        "Mean scheduled servers",
        "servers",
        _WARMUP_WINDOW,
        "Time-average number of servers on duty under the staffing schedule, "
        "which equals the capacity at a station without a staffing schedule and "
        "includes servers that are down.",
    ),
    (
        "mean_available_servers",
        "station",
        "Mean available servers",
        "servers",
        _WARMUP_WINDOW,
        "Time-average number of servers that are on duty and not down, plus "
        "off-duty servers that are not down and are finishing a job at a station "
        "whose shifts end with shift_end='finish'.",
    ),
    (
        "mean_outside_queue",
        "station",
        "Time-average customers waiting outside",
        "customers",
        _WARMUP_WINDOW,
        "Time-average number of arriving customers waiting outside the station's "
        "full finite buffer for admission, which excludes upstream customers "
        "blocked from entering.",
    ),
    (
        "max_queue",
        "station",
        "Largest queue",
        "customers",
        _WARMUP_WINDOW,
        "Largest number of customers waiting in the station's line, ignoring "
        "states that last zero time.",
    ),
    (
        "service_starts",
        "station",
        "Service starts",
        "customers",
        _WARMUP_WINDOW,
        "Services that start at the station during the operating window.",
    ),
    (
        "service_completions",
        "station",
        "Service completions",
        "customers",
        _WARMUP_WINDOW,
        "Services whose processing ends at the station during the operating "
        "window, before any blocked time.",
    ),
    (
        "wait_arrivals",
        "station",
        "Visits in the wait cohort",
        "customers",
        "visits admitted at or after warmup",
        "Visits admitted to the station's line at or after warmup, which form the "
        "cohort behind the wait averages and include visits after closing when a "
        "drained run continues.",
    ),
    (
        "wait_observations",
        "station",
        "Visits with an observed wait",
        "customers",
        _WAIT_COHORT,
        "Visits in the wait cohort whose service start was observed.",
    ),
    (
        "waiting_at_close",
        "station",
        "Customers waiting at closing",
        "customers",
        "at closing",
        "Customers waiting in the station's line at closing, including customers "
        "who arrived before warmup.",
    ),
    (
        "occupied_at_close",
        "station",
        "Servers occupied at closing",
        "servers",
        "at closing",
        "Servers holding a job at closing, whether processing, paused, or "
        "blocked, so the count includes blocked_at_close and paused_at_close.",
    ),
    (
        "waiting_at_end",
        "station",
        "Customers waiting at the end",
        "customers",
        "at the end of the run",
        "Customers waiting in the station's line when the run ended.",
    ),
    (
        "occupied_at_end",
        "station",
        "Servers occupied at the end",
        "servers",
        "at the end of the run",
        "Servers holding a job when the run ended, whether processing, paused, "
        "or blocked.",
    ),
    (
        "blocked_at_close",
        "station",
        "Servers blocked at closing",
        "servers",
        "at closing",
        "Servers holding a finished job that the next station could not accept "
        "at closing.",
    ),
    (
        "paused_at_close",
        "station",
        "Servers paused at closing",
        "servers",
        "at closing",
        "Servers holding a job whose work was paused at closing because the "
        "server was down or off duty.",
    ),
    # Stock-point metrics, in the stock_points table.
    (
        "bullwhip_ratio",
        "stock_point",
        "Order variance / demand variance",
        "ratio",
        _PERIODS,
        "Sample variance of the quantities the stock point ordered divided by "
        "the sample variance of its incoming orders, which is missing with fewer "
        "than two periods or constant incoming orders.",
    ),
    (
        "fill_rate",
        "stock_point",
        "Demand filled from stock in the same period",
        "fraction",
        _PERIODS,
        "Total units of incoming orders filled from stock in the period they "
        "arrived divided by total incoming orders over the measured periods, so "
        "filled backorders do not count and the rate is missing when no orders "
        "arrived.",
    ),
    (
        "mean_on_hand",
        "stock_point",
        "Mean end-of-period stock on hand",
        "units",
        _PERIODS,
        "Mean stock on hand after each review's receipts and shipments, a level "
        "that holds until the next review, over the review periods at or after "
        "warmup.",
    ),
    (
        "mean_backorders",
        "stock_point",
        "Mean end-of-period backorders",
        "units",
        _PERIODS,
        "Mean backorders after each review's receipts and shipments, a level "
        "that holds until the next review, over the review periods at or after "
        "warmup.",
    ),
    (
        "lost_units",
        "stock_point",
        "Lost sales",
        "units",
        _PERIODS,
        "Total units of incoming orders lost, which is zero unless the stock "
        "point's shortage rule is 'lost'.",
    ),
    (
        "mean_demand",
        "stock_point",
        "Mean incoming orders",
        "units",
        _PERIODS,
        "Mean incoming orders per review period, which are consumer demand at "
        "the retailer and the downstream stage's order at every other stage.",
    ),
    (
        "mean_order",
        "stock_point",
        "Mean orders placed",
        "units",
        _PERIODS,
        "Mean quantity that the stock point ordered per review period.",
    ),
    (
        "demand_variance",
        "stock_point",
        "Variance of incoming orders",
        "variance",
        _PERIODS,
        "Sample variance of incoming orders per review period, with the n - 1 divisor.",
    ),
    (
        "order_variance",
        "stock_point",
        "Variance of orders placed",
        "variance",
        _PERIODS,
        "Sample variance of the quantities ordered per review period, with the "
        "n - 1 divisor.",
    ),
]
Scope = Literal["system", "station", "stock_point"]
_SCOPE_TABLES = {
    "system": "summary",
    "station": "stations",
    "stock_point": "stock_points",
}
METRICS = {
    name: Metric(
        scope=scope,
        label=label,
        kind=kind,
        table=_SCOPE_TABLES[scope],
        meaning=meaning,
        window=window,
    )
    for name, scope, label, kind, window, meaning in _METRIC_ROWS
}
SYSTEM_METRICS = [name for name, metric in METRICS.items() if metric.scope == "system"]
STATION_METRICS = [
    name for name, metric in METRICS.items() if metric.scope == "station"
]
STOCK_POINT_METRICS = [
    name for name, metric in METRICS.items() if metric.scope == "stock_point"
]

# Display order of the stations and summary tables: the headline columns come
# first, then the rest in the order their builders compute them. Order is a
# display choice, applied as each builder's final select, so reordering never
# touches a computation.
STATION_HEADLINE = [
    "station",
    "mean_wait",
    "mean_queue",
    "utilization",
    "p95_wait",
    "max_queue",
]
SUMMARY_HEADLINE = [
    "arrivals",
    "completed",
    "mean_total_wait",
    "mean_flow_time",
    "throughput",
    "overtime",
]


def headline_first(columns: list[str], headline: list[str]) -> list[str]:
    """Order columns with the headline columns first and the rest after them."""
    return [*headline, *(column for column in columns if column not in headline)]


STATION_SCHEMA = {
    column: _STATION_TYPES[column]
    for column in headline_first(list(_STATION_TYPES), STATION_HEADLINE)
}


# Plural time units that a rate names in the singular, i.e., "per minute".
# Any other label, such as "ms", stays as the model gives it.
_SINGULAR_UNITS = {
    "seconds": "second",
    "minutes": "minute",
    "hours": "hour",
    "days": "day",
    "weeks": "week",
    "months": "month",
    "years": "year",
    "periods": "period",
    "shifts": "shift",
}


def metric_units(metric: str, time_unit: str) -> str:
    singular = _SINGULAR_UNITS.get(time_unit, time_unit)
    return {
        "time": time_unit,
        "rate": f"customers per {singular}",
        "fraction": "share",
        "servers": "servers",
        "customers": "count",
        "units": "units",
        "ratio": "variance ratio",
        "variance": "squared units",
    }[METRICS[metric].kind]


def confidence_level(value: float) -> float:
    level = number(
        value=value,
        label="Confidence level",
        positive=True,
    )
    if level >= 1:
        raise ValueError("Confidence level must be below one.")
    return level


INTERVAL_SCHEMA = {
    "scenario": pl.String,
    "baseline": pl.String,
    "station": pl.String,
    "stock_point": pl.String,
    "metric": pl.String,
    "runs": pl.Int64,
    "observed_runs": pl.Int64,
    "mean": pl.Float64,
    "lower": pl.Float64,
    "upper": pl.Float64,
    "confidence": pl.Float64,
}


def interval_frame(rows: list[dict], keys: list[str]) -> pl.DataFrame:
    """Build an interval table whose columns exist even when it has no rows.

    The keys name the identifying columns in display order, and the estimate
    columns from "runs" to "confidence" follow them.
    """
    columns = [*keys, "runs", "observed_runs", "mean", "lower", "upper", "confidence"]
    return pl.DataFrame(
        data=rows,
        schema={column: INTERVAL_SCHEMA[column] for column in columns},
    )


# Numeric columns of the stations, summary, and stock_points tables that are not
# replication metrics, and identifier columns, each with the reason. A metric
# name has one scope, so the two station columns that share a name with a
# system metric are listed here and read from the stations table.
EXCLUDED = {
    (
        "stations",
        "station",
    ): "It names the row, so it identifies a station and measures nothing.",
    ("stations", "capacity"): "It is a setting, not an outcome.",
    (
        "stations",
        "arrivals",
    ): "It shares its name with the system metric arrivals, which counts customers over the whole run, so this count of visits admitted to the station's line in [warmup, duration) is read from the stations table.",
    (
        "stations",
        "outside_at_close",
    ): "It shares its name with the system metric outside_at_close, which counts customers outside the first station at closing, so this count for one station is read from the stations table.",
    (
        "stock_points",
        "stock_point",
    ): "It names the row, so it identifies a stock point and measures nothing.",
    (
        "stock_points",
        "periods",
    ): "It is fixed by the run length, the warm-up, and the review period, so it does not vary across replications.",
}


@dataclass(frozen=True)
class Column:
    """What one table column holds and its units."""

    meaning: str
    units: str


# Each table's columns as column: (meaning, units).
_SCHEMA_COLUMNS = {
    "customers": {
        "customer_id": ("Identifier of the customer, unique within a run.", "id"),
        "source": (
            "Name of the source that created the customer, or of the stock point that released the production job.",
            "label",
        ),
        "customer_type": (
            "Customer type, empty for a production job or a customer from a source without types.",
            "label",
        ),
        "quantity": (
            "Units in a production job, empty for a customer from a source.",
            "units",
        ),
        "arrival_time": ("Time the customer arrived in the system.", "time unit"),
        "exit_time": (
            "Time the customer left the network, empty if it did not complete.",
            "time unit",
        ),
        "abandon_time": (
            "Time the customer abandoned before service, empty if it did not abandon.",
            "time unit",
        ),
        "flow_time": (
            "Time from arrival to exit, empty if the customer did not exit.",
            "time unit",
        ),
        "total_wait": (
            "Total of the customer's completed waits before service, including any wait outside the first station.",
            "time unit",
        ),
        "total_blocked": (
            "Total time the customer was held at a station after service because the next station could not accept it, counting only blocking that had ended.",
            "time unit",
        ),
        "admitted": (
            "Whether the customer was admitted to the first station.",
            "true/false",
        ),
        "admission_time": (
            "Time the customer was admitted to the first station, empty if never admitted.",
            "time unit",
        ),
        "outside_wait": (
            "Time from arrival to admission, which is zero for a customer admitted on arrival and empty for a customer never admitted.",
            "time unit",
        ),
        "status": (
            "The customer's status at the end of the run: outside, waiting, in_service, blocked, paused, rejected, abandoned, or completed.",
            "label",
        ),
        "station": (
            "Station where the customer was at the end of the run, or where it was rejected or abandoned, empty for a completed customer.",
            "label",
        ),
    },
    "visits": {
        "customer_id": ("Identifier of the visiting customer.", "id"),
        "source": (
            "Name of the source that created the customer, or of the stock point that released the production job.",
            "label",
        ),
        "customer_type": (
            "Customer type, empty for a production job or a customer from a source without types.",
            "label",
        ),
        "station": ("Station that was visited.", "label"),
        "arrival_time": (
            "Time the customer entered the station's line, which follows its system arrival when it waited outside a full finite buffer and follows its upstream service end when it was blocked upstream.",
            "time unit",
        ),
        "service_start": (
            "Time service started, empty if it never started.",
            "time unit",
        ),
        "service_end": (
            "Time processing finished, so service_end minus service_start includes any paused time, empty if processing had not finished.",
            "time unit",
        ),
        "departure_time": (
            "Time the customer left the station, which can be later than service_end because of downstream blocking, empty if the customer had not left or abandoned the line.",
            "time unit",
        ),
        "abandon_time": (
            "Time the customer abandoned this station's line, empty if it did not.",
            "time unit",
        ),
        "server_id": (
            "Server that served the visit, empty if service never started.",
            "id",
        ),
        "blocked_time": (
            "Time the customer was held after service until departure, empty if not observed.",
            "time unit",
        ),
        "wait_time": (
            "Time from arrival at the station to the start of service, empty if service never started.",
            "time unit",
        ),
        "service_time": (
            "Sampled service requirement, i.e., the per-unit draw times the job's quantity for a production job, which is not elapsed busy time and can extend beyond the run limit.",
            "time unit",
        ),
    },
    "states": {
        "station": ("Station the row describes.", "label"),
        "time": (
            "Time of the row, i.e., the start of the run, a time when the station's state changed, closing, or the end of the run, and the row holds the state after every event at that time.",
            "time unit",
        ),
        "waiting": (
            "Customers waiting in the station's line after the change.",
            "count",
        ),
        "busy": (
            "Servers holding a job that is processing, paused, or blocked.",
            "servers",
        ),
        "processing": ("Servers actively processing a job.", "servers"),
        "blocked": (
            "Servers holding a finished job that the next station cannot accept.",
            "servers",
        ),
        "paused": (
            "Servers holding a job whose work is paused because the server was down or off duty.",
            "servers",
        ),
        "down": ("Servers that are down for repair.", "servers"),
        "scheduled": (
            "Servers on duty under the staffing schedule, which equals the capacity at a station without a staffing schedule and includes servers that are down.",
            "servers",
        ),
        "available": (
            "Servers that are on duty and not down, plus off-duty servers that are not down and are finishing a job when shift_end is 'finish'.",
            "servers",
        ),
        "outside": (
            "Arriving customers waiting outside the station's full finite buffer for admission, which excludes upstream customers blocked from entering.",
            "count",
        ),
    },
    "activities": {
        "customer_id": ("Identifier of the customer served.", "id"),
        "station": ("Station where the interval occurred.", "label"),
        "server_id": ("Server that held the job during the interval.", "id"),
        "state": (
            "Server phase during the interval: processing, blocked, or paused.",
            "label",
        ),
        "start": ("Start of the interval.", "time unit"),
        "end": (
            "End of the interval, empty if it was still open at the end.",
            "time unit",
        ),
    },
    "failures": {
        "station": ("Station of the failed server.", "label"),
        "server_id": ("Server that failed.", "id"),
        "failure_time": ("Time the server failed.", "time unit"),
        "time_to_failure": (
            "Sampled lifetime, counted only while the failure clock runs, so it can be shorter than the time elapsed since the previous repair ended.",
            "time unit",
        ),
        "repair_time": ("Sampled repair requirement.", "time unit"),
        "repair_end": (
            "Time the repair finished, empty if it was not observed.",
            "time unit",
        ),
    },
    "inventory": {
        "stock_point": ("Stock point the row describes.", "label"),
        "period": ("Review period number, counted from zero.", "index"),
        "time": ("Time of the review.", "time unit"),
        "received": (
            "Units added to stock at the review, from shipments due by this period and, at a producing stage, jobs finished since the previous review.",
            "units",
        ),
        "demand": ("Incoming orders in the period.", "units"),
        "filled": (
            "Units of the period's incoming orders filled from stock in the same period.",
            "units",
        ),
        "shipped": (
            "Units shipped downstream in the period, including filled backorders.",
            "units",
        ),
        "lost": ("Units of incoming orders lost in the period.", "units"),
        "on_hand": (
            "Stock on hand at the end of the period, after the review's order.",
            "units",
        ),
        "backorders": ("Backorders at the end of the period.", "units"),
        "on_order": (
            "Units ordered but not yet received at the end of the period.",
            "units",
        ),
        "position": (
            "Inventory position at the end of the period: on hand plus on order minus backorders.",
            "units",
        ),
        "forecast": (
            "One-period forecast used for the order, i.e., the moving average of incoming orders, or of consumer demand when forecast_from is 'end_demand', including this period.",
            "units",
        ),
        "target": ("Order-up-to target used for the period's order.", "units"),
        "order_quantity": ("Quantity ordered at the period's review.", "units"),
    },
    "shipments": {
        "sender": (
            "Stage that shipped, or Supplier for orders of a top stage that does not produce.",
            "label",
        ),
        "receiver": ("Stage that receives the shipment.", "label"),
        "quantity": ("Units shipped.", "units"),
        "ship_time": ("Time the shipment was sent.", "time unit"),
        "lead_time": (
            "Lead time of the shipment, constant or sampled, which can be shorter than arrival_time minus ship_time because a shipment arrives only at a review and never before an earlier shipment to the same stage.",
            "time unit",
        ),
        "arrival_time": (
            "Time the shipment arrived, empty if it was still in transit at the end.",
            "time unit",
        ),
    },
    "stations": {
        "station": ("Station the row describes.", "label"),
        "capacity": ("Number of installed servers at the station.", "servers"),
        "arrivals": (
            "Visits admitted to the station's line in [warmup, duration), which excludes rejected arrivals and customers still waiting outside.",
            "count",
        ),
        "outside_at_close": (
            "Arriving customers waiting outside the station's full finite buffer for admission at closing, which excludes upstream customers blocked from entering.",
            "count",
        ),
    },
    "stock_points": {
        "stock_point": ("Stock point the row describes.", "label"),
        "periods": ("Review periods at or after warmup.", "count"),
    },
    "intervals": {
        "scenario": ("Scenario that the interval describes.", "label"),
        "baseline": (
            "Baseline scenario that the difference is measured against, in the differences table only.",
            "label",
        ),
        "station": (
            "Station the metric was measured at, empty for a system metric and absent from the tables of stock-point metrics.",
            "label",
        ),
        "stock_point": (
            "Stock point the metric was measured at, a column that only the tables of stock-point metrics have, in place of station.",
            "label",
        ),
        "metric": ("Name of the replication metric.", "label"),
        "runs": ("Replications run.", "count"),
        "observed_runs": (
            "Replications with a finite value, or, in the differences table, matched pairs whose difference is finite, which are the ones the interval uses.",
            "count",
        ),
        "mean": (
            "Mean of the run-level values, or of the paired differences in the differences table.",
            "metric units",
        ),
        "lower": (
            "Lower limit of the Student t confidence interval, empty when fewer than two runs are observed.",
            "metric units",
        ),
        "upper": (
            "Upper limit of the Student t confidence interval, empty when fewer than two runs are observed.",
            "metric units",
        ),
        "confidence": ("Confidence level of the interval.", "share"),
    },
    "pooled": {
        "replication": (
            "Replication number within an experiment, counted from one.",
            "index",
        ),
        "scenario": ("Scenario name in a comparison's pooled tables.", "label"),
    },
    "fits": {
        "rank": ("Position by AIC, where one is the best fit.", "count"),
        "family": ("Family name.", "label"),
        "description": (
            "Plain-language description of the fitted distribution with its parameters, including any shift and a warning when draws can be negative.",
            "label",
        ),
        "mean": ("Mean of the fitted distribution.", "data unit"),
        "sd": ("Standard deviation of the fitted distribution.", "data unit"),
        "p_negative": (
            "Chance that a draw from the fitted distribution is below zero.",
            "share",
        ),
        "aic": (
            "Akaike information criterion, 2k - 2 log-likelihood for k fitted parameters, where lower is better.",
            "dimensionless",
        ),
        "ks": (
            "Kolmogorov-Smirnov statistic, the largest vertical gap between the data's empirical CDF and the fitted CDF, empty for count fits.",
            "share",
        ),
        "shape": (
            "Shape parameter of a gamma or Weibull fit before any shift.",
            "dimensionless",
        ),
        "scale": (
            "Scale parameter of a gamma or Weibull fit before any shift.",
            "data unit",
        ),
        "low": (
            "Lower end of a uniform, triangular, or beta fit before any shift, so the fitted lower end is low plus by when by is present.",
            "data unit",
        ),
        "mode": (
            "Mode of a triangular fit before any shift, so the fitted mode is mode plus by when by is present.",
            "data unit",
        ),
        "high": (
            "Upper end of a uniform, triangular, or beta fit before any shift, so the fitted upper end is high plus by when by is present.",
            "data unit",
        ),
        "a": ("First shape parameter of a beta fit.", "dimensionless"),
        "b": ("Second shape parameter of a beta fit.", "dimensionless"),
        "by": (
            "Shift added to a shifted fit, so the unshifted mean is mean minus by.",
            "data unit",
        ),
    },
}
# Every documented column as (table, column): Column. The metric columns of
# summary, stations, and stock_points read their entries from METRICS.
COLUMNS = {
    **{
        (table, column): Column(
            meaning=meaning,
            units=units,
        )
        for table, entries in _SCHEMA_COLUMNS.items()
        for column, (meaning, units) in entries.items()
    },
    **{
        (metric.table, name): Column(
            meaning=metric.meaning,
            units=metric_units(name, "time unit"),
        )
        for name, metric in METRICS.items()
    },
}
_SCOPE_LABELS = {
    "system": "system",
    "station": "station",
    "stock_point": "stock-point",
}


def _grouped_metrics() -> dict[str, list[str]]:
    return {
        "system metrics": SYSTEM_METRICS,
        "station metrics": STATION_METRICS,
        "stock-point metrics": STOCK_POINT_METRICS,
    }


def unknown(
    kind: str,
    name: str,
    choices: list[str] | dict[str, list[str]],
    *,
    intro: str | None = None,
) -> ValueError:
    """Build the error for a name that is not among the choices.

    The message names what was not found, lists the close matches when there
    are any, and lists the choices, grouped when the choices are a mapping from
    a group label to its names.
    """
    groups = choices if isinstance(choices, dict) else {f"{kind}s": list(choices)}
    pool = [choice for group in groups.values() for choice in group]
    close = difflib.get_close_matches(
        str(name),
        pool,
        n=3,
    )
    lines = [intro or f"{kind.capitalize()} {name!r} is missing in this experiment."]
    if close:
        lines.append(f"Close matches: {', '.join(close)}.")
    if isinstance(choices, dict):
        lines.append("Available:")
        lines += [f"  {label}: {', '.join(group)}" for label, group in groups.items()]
    else:
        lines.append(f"Available {kind}s: {', '.join(pool)}.")
    return ValueError("\n".join(lines))


def metric_error(name: str) -> ValueError:
    """Build the error for a name that is not a registered metric."""
    tables = sorted(table for table, column in COLUMNS if column == name)
    if tables:
        reasons = [
            EXCLUDED[(table, name)] for table in tables if (table, name) in EXCLUDED
        ]
        if len(tables) == 1:
            where = f"a {tables[0]} column"
        else:
            where = f"a column of the {', '.join(tables)} tables"
        return ValueError(
            " ".join(
                [
                    f"{name!r} is {where}, not a replication metric.",
                    *reasons,
                    "Call flowsim.metrics() to list the metrics.",
                ]
            )
        )
    error = unknown(
        kind="metric",
        name=name,
        choices=_grouped_metrics(),
        intro=f"Unknown metric {name!r}.",
    )
    return ValueError(f"{error}\nCall flowsim.metrics() for their meanings.")


def scope_name(metric: str) -> str:
    return _SCOPE_LABELS[METRICS[metric].scope]


class Inapplicable(ValueError):
    """A metric whose scope the model does not have, e.g., stock points."""


# System metrics about when the run stopped, which every model has, unlike the
# customer counts and averages a supply chain without stations lacks.
RUN_LEVEL_METRICS = frozenset({"end_time", "overtime"})


def inapplicable(
    metric: str,
    *,
    stations: bool,
    stock_points: bool,
    supply: bool,
) -> Inapplicable | None:
    """Return the error for a metric that this kind of model cannot measure.

    A service network has no stock points. A supply chain without production
    stations has no stations and no customers, so its system metrics would all
    be missing or zero. A model without stations has no station metrics.
    """
    scope = METRICS[metric].scope
    # The run's stopping time applies to every model.
    if metric in RUN_LEVEL_METRICS:
        return None
    if scope == "stock_point" and not stock_points:
        other = ", or a station metric, e.g., metric='mean_wait'," if stations else ""
        return Inapplicable(
            f"This model has no stock points, so stock-point metrics such as "
            f"{metric!r} do not apply. Choose a system metric, e.g., "
            f"metric='mean_total_wait'{other}."
        )
    if scope != "stock_point" and supply and not stations:
        return Inapplicable(
            "This supply chain has no production stations, so it has no "
            f"customers or stations, and {scope_name(metric)} metrics such as "
            f"{metric!r} do not apply. Choose a stock-point metric, e.g., "
            "metric='fill_rate'."
        )
    if scope == "station" and not stations:
        return Inapplicable(
            f"This model has no stations, so station metrics such as {metric!r} "
            "do not apply. Choose a system metric, e.g., metric='mean_total_wait'."
        )
    return None


def metrics(scope: Scope | None = None) -> pl.DataFrame:
    """List the replication metrics that ``intervals`` and ``plot`` accept.

    Parameters
    ----------
    scope : {"system", "station", "stock_point"}, optional
        Keep only the metrics of this scope. The default lists every metric.

    Returns
    -------
    polars.DataFrame
        One row per metric with its name, scope, table, label, units, needs
        (the argument that picks one location), window, and meaning. Time
        metrics list "time unit" because no model is known here.

    Example
    -------
    >>> flowsim.metrics("station").select("name", "units", "meaning")
    """
    if scope is not None and scope not in _SCOPE_TABLES:
        raise ValueError(f"Choose a scope from {list(_SCOPE_TABLES)}, not {scope!r}.")
    needs = {
        "system": "",
        "station": "station=",
        "stock_point": "stock_point=",
    }
    chosen = {
        name: metric
        for name, metric in METRICS.items()
        if scope is None or metric.scope == scope
    }
    return pl.DataFrame(
        data={
            "name": list(chosen),
            "scope": [metric.scope for metric in chosen.values()],
            "table": [metric.table for metric in chosen.values()],
            "label": [metric.label for metric in chosen.values()],
            "units": [metric_units(name, "time unit") for name in chosen],
            "needs": [needs[metric.scope] for metric in chosen.values()],
            "window": [metric.window for metric in chosen.values()],
            "meaning": [metric.meaning for metric in chosen.values()],
        },
        schema={
            "name": pl.String,
            "scope": pl.String,
            "table": pl.String,
            "label": pl.String,
            "units": pl.String,
            "needs": pl.String,
            "window": pl.String,
            "meaning": pl.String,
        },
    )


def explain(name: str) -> None:
    """Print what a metric or table column means and how to request it.

    The printout covers the replication metric called ``name`` (its label,
    scope, table, units, window, meaning, and how to request it), every table
    column with that name, and the reason a column is not a metric. A name that
    is not in the catalog prints its close matches.

    Parameters
    ----------
    name : str
        A metric or column name, e.g. ``"mean_wait"`` or ``"customer_id"``.

    Returns
    -------
    None
        The description is printed, not returned.

    Example
    -------
    >>> flowsim.explain("p95_wait")
    """
    metric = METRICS.get(name)
    columns = sorted((table, column) for table, column in COLUMNS if column == name)
    if metric is None and not columns:
        pool = sorted({*METRICS, *(column for _, column in COLUMNS)})
        close = difflib.get_close_matches(
            name,
            pool,
            n=3,
        )
        print(f"{name!r} is not a metric or column name.")
        print(
            f"Close matches: {', '.join(close)}."
            if close
            else "There are no close matches."
        )
        print("Call flowsim.metrics() to list the replication metrics.")
        return
    lines = []
    if metric is not None:
        where = {
            "system": "",
            "station": 'station="Service"',
            "stock_point": 'stock_point="Retailer"',
        }[metric.scope]
        call = f'"{name}"' if not where else f'"{name}", {where}'
        lines += [
            f"{name}: {metric.label}",
            f"  Replication metric ({_SCOPE_LABELS[metric.scope]} scope, "
            f"{metric.table} table)",
            f"    Units:   {metric_units(name, 'time unit')}",
            f"    Window:  {metric.window}",
            f"    Meaning: {metric.meaning}",
            f"    Request: experiment.intervals({call})",
            f"             comparison.intervals({call})",
        ]
    else:
        lines.append(name)
    for table, column in columns:
        entry = COLUMNS[(table, column)]
        lines.append(f"  Column in the {table} table (units: {entry.units})")
        if metric is None or entry.meaning != metric.meaning:
            lines.append(f"    Meaning: {entry.meaning}")
        if (table, column) in EXCLUDED:
            lines.append(f"    Not a replication metric: {EXCLUDED[(table, column)]}")
    print("\n".join(lines))


def write_text(path: str | Path, text: str) -> None:
    destination = Path(path)
    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    destination.write_text(
        data=text,
        encoding="utf-8",
    )


def _run_settings(run: Results) -> tuple:
    """Return the settings that pooled or compared runs must share."""
    settings = run.settings
    return (settings.duration, settings.warmup, settings.drain, settings.time_unit)


# Every file name a FlowSim export can write. An export removes the ones it did
# not write, so a folder never mixes files from two different exports.
EXPORT_FILE_NAMES = frozenset(
    {
        "customers.csv",
        "visits.csv",
        "states.csv",
        "stations.csv",
        "summary.csv",
        "activities.csv",
        "failures.csv",
        "inventory.csv",
        "shipments.csv",
        "stock_points.csv",
        "metadata.json",
        "runs.csv",
        "intervals.csv",
        "differences.csv",
    }
)


def remove_stale_exports(destination: Path, written: set[str]) -> None:
    """Delete FlowSim export files in destination that this export did not write."""
    for name in EXPORT_FILE_NAMES - written:
        stale = destination / name
        if stale.is_file():
            stale.unlink()


def _write_metadata(path: str | Path, data: dict) -> None:
    """Write export metadata as JSON, stamped with the FlowSim version."""
    write_text(path, json.dumps({"flowsim_version": __version__, **data}, indent=2))


def interval_estimate(values: np.ndarray, confidence: float) -> dict:
    """Estimate uncertainty across independent finite replication values."""
    values = values[np.isfinite(values)]
    count = len(values)
    mean = float(values.mean()) if count else None
    lower = upper = None
    # Estimates have the metric's units. Standard error divides by sqrt(runs).
    if mean is not None and count >= 2:
        half_width = float(
            t.ppf((1 + confidence) / 2, df=count - 1)
            * values.std(ddof=1)
            / np.sqrt(count)
        )
        lower = mean - half_width
        upper = mean + half_width
    return {
        "observed_runs": count,
        "mean": mean,
        "lower": lower,
        "upper": upper,
    }


@dataclass(frozen=True)
class Settings:
    """The settings of a run: its window, stopping rule, seed, and capacities.

    end_time is when the run stopped, which is later than duration in a drained
    run. capacities is a read-only mapping from each station to its servers.
    An experiment's or comparison's settings hold None for the seed and end
    time, which differ by run, and a comparison's hold None for capacities,
    which differ by scenario.

    Attributes
    ----------
    duration : float
        Closing time in model time units.
    warmup : float
        Initial period excluded from measurement.
    drain : bool
        Whether the run continued past duration until no customers remained.
    seed : int or None
        The run's seed.
    time_unit : str
        The model's time unit label.
    end_time : float or None
        When the run stopped.
    capacities : mapping of str to int or None
        Installed servers at each station.

    Example
    -------
    >>> results.settings.duration
    480.0
    """

    duration: float
    warmup: float
    drain: bool
    seed: int | None
    time_unit: str
    end_time: float | None
    capacities: Mapping[str, int] | None


# Displays read tables and attributes that already exist. None of them runs a
# model, fits a distribution, or builds a viewer or figure.
def display_text(head: str, rows: list[tuple[str, str]]) -> str:
    """Join a heading and its (label, value) rows into a short text display."""
    lines = [head]
    for label, value in rows:
        lines.append(f"  {label}: {value}" if label else f"    {value}")
    return "\n".join(lines)


def display_html(head: str, rows: list[tuple[str, str]]) -> str:
    """Render the same heading and rows as a compact HTML table."""
    body = "".join(
        '<tr><th style="text-align: left; vertical-align: top; padding-right: 1em;">'
        f"{html.escape(label)}</th><td><code>{html.escape(value)}</code></td></tr>"
        for label, value in rows
    )
    return (
        f"<div><strong>{html.escape(head)}</strong>"
        f'<table style="border-collapse: collapse;">{body}</table></div>'
    )


def figure(value: object) -> str:
    """Format one table value for a display."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3g}"
    return str(value)


def window_line(settings: Settings) -> str:
    """Describe a run window and stopping rule in one line."""
    stopping = "drained" if settings.drain else "not drained"
    return (
        f"{settings.duration:g} {settings.time_unit}, "
        f"warm-up {settings.warmup:g}, {stopping}"
    )


def missing_attribute(
    owner: object,
    name: str,
    hints: dict[str, str],
) -> AttributeError:
    """Build the error for a missing public attribute, with a hint or matches."""
    message = f"{type(owner).__name__!r} object has no attribute {name!r}."
    if name in hints:
        return AttributeError(f"{message} {hints[name]}")
    public = [
        attribute
        for attribute in [*dir(type(owner)), *vars(owner)]
        if not attribute.startswith("_")
    ]
    close = difflib.get_close_matches(
        name,
        public,
        n=3,
    )
    if close:
        message += f" Close matches: {', '.join(close)}."
    return AttributeError(message)


def moved_settings(owner: str, names: list[str]) -> dict[str, str]:
    """Hint that each named setting now lives on the owner's settings."""
    return {name: f"The setting moved: use {owner}.settings.{name}." for name in names}


# A run's raw record tables, which model.experiment(..., keep_records=False)
# drops once the run's measures are computed.
RAW_TABLES = (
    "customers",
    "visits",
    "states",
    "activities",
    "failures",
    "inventory",
    "shipments",
)

_DROPPED = (
    "This run's raw records were dropped by model.experiment(..., "
    "keep_records=False). Rerun with keep_records=True to keep them."
)


class Results:
    """The records and measures of one simulation run.

    A run's raw records are the customers, visits, states, activities, failures,
    and (for a supply chain) inventory and shipments tables. Its measures are
    the stations, summary, and stock_points tables. Queue averages,
    utilization, throughput, and the measurement counts use the window
    [warmup, duration). Whole-run counts such as arrivals and completed cover
    the entire run, including a drained continuation, and wait and flow-time
    averages use cohorts of arrivals at or after warmup whose outcomes were
    observed. flowsim.explain(name) gives each measure's window. Model.run
    returns a Results.

    Attributes
    ----------
    settings : Settings
        The duration, warmup, drain rule, seed, time unit, end time, and
        capacities of the run.
    customers, visits, states, activities, failures : polars.DataFrame
        Raw records: each customer, each station visit, station state changes,
        processing and blocked intervals, and server failures.
    inventory, shipments : polars.DataFrame
        Raw records of each stock-point review and each shipment. Both are empty
        for a service network.
    stations, summary, stock_points : polars.DataFrame
        Measures per station, for the whole system, and per stock point. A
        table that does not apply to the model is empty.

    The common next calls are report, plot_queue, plot_wait, plot_utilization,
    plot_inventory, viewer, and export. Call flowsim.explain(name) for a column.

    Example
    -------
    >>> results = model.run(duration=480)
    >>> results.summary.select("arrivals", "completed", "mean_total_wait")
    """

    settings: Settings
    customers: pl.DataFrame
    visits: pl.DataFrame
    states: pl.DataFrame
    activities: pl.DataFrame
    failures: pl.DataFrame
    inventory: pl.DataFrame
    shipments: pl.DataFrame
    stations: pl.DataFrame
    summary: pl.DataFrame
    stock_points: pl.DataFrame

    # Old plot names, by their current names on a single run.
    _RENAMED = {
        "queue_plot": "plot_queue",
        "wait_plot": "plot_wait",
        "utilization_plot": "plot_utilization",
        "resource_plot": "plot_resources",
        "customer_plot": "plot_customer",
        "inventory_plot": "plot_inventory",
        "orders_plot": "plot_orders",
    }

    def __getattr__(self, name: str) -> object:
        # Called only for a missing attribute. Underscore names, which pickle,
        # copy, and IPython probe, get the plain error with no hint.
        if name.startswith("_"):
            raise AttributeError(
                f"{type(self).__name__!r} object has no attribute {name!r}"
            )
        hints = moved_settings(
            owner="results",
            names=[
                "duration",
                "warmup",
                "drain",
                "seed",
                "time_unit",
                "end_time",
                "capacities",
            ],
        )
        hints.update(
            {
                old: f"The method was renamed: use results.{new}()."
                for old, new in self._RENAMED.items()
            }
        )
        hints.update({table: _DROPPED for table in RAW_TABLES})
        hints["intervals"] = (
            "A single run has no replications. Run model.experiment(...) for intervals."
        )
        hints["differences"] = (
            "A single run has no replications. Run model.experiment(...) for each "
            "scenario, then flowsim.compare(...) for differences."
        )
        hints["plot"] = (
            "A single run has plot_queue(), plot_wait(), plot_utilization(), "
            "plot_resources(), plot_customer(id), plot_inventory(), and "
            "plot_orders(). For intervals across replications, run "
            "model.experiment(...) and call experiment.plot()."
        )
        raise missing_attribute(self, name, hints)

    @property
    def _capacities(self) -> Mapping[str, int]:
        # A run's settings always hold its capacities. Only a comparison's
        # shared settings hold None.
        capacities = self.settings.capacities
        assert capacities is not None
        return capacities

    def _drop_records(self) -> None:
        """Delete the raw record tables and keep the measures."""
        for name in RAW_TABLES:
            delattr(self, name)
        self._records_kept = False

    def _require_records(self, call: str) -> None:
        """Raise a clear error when a call needs raw records that were dropped."""
        if not self._records_kept:
            raise ValueError(f"results.{call} reads raw records. {_DROPPED}")

    def __repr__(self) -> str:
        return display_text(*self._display())

    def _repr_html_(self) -> str:
        return display_html(*self._display())

    def _display(self) -> tuple[str, list[tuple[str, str]]]:
        settings = self.settings
        kind = "service network" if self._supply is None else "supply chain"
        rows = [
            ("Run", f"{window_line(settings)}, ends at {settings.end_time:g}"),
            ("Seed", str(settings.seed)),
            (
                "",
                "model.experiment(...) spawns each replication's seed from its seed "
                "argument, so replication 1's seed differs from a single run's seed.",
            ),
        ]
        if self._supply is None:
            first = self.summary.row(0, named=True)
            rows.append(
                (
                    "Summary",
                    ", ".join(
                        f"{name} {figure(first[name])}"
                        for name in [
                            "arrivals",
                            "completed",
                            "mean_total_wait",
                            "mean_flow_time",
                        ]
                    ),
                )
            )
        shown = 6
        stock_rows = list(self.stock_points.iter_rows(named=True))
        for label, frame, name, columns in [
            ("Stock points", stock_rows, "stock_point", ["fill_rate", "mean_on_hand"]),
            (
                "Stations",
                list(self.stations.iter_rows(named=True)),
                "station",
                ["mean_wait", "utilization"],
            ),
        ]:
            for index, row in enumerate(frame[:shown]):
                detail = ", ".join(
                    f"{column} {figure(row[column])}" for column in columns
                )
                rows.append((label if index == 0 else "", f"{row[name]}: {detail}"))
            if len(frame) > shown:
                rows.append(("", f"... and {len(frame) - shown} more"))
        if not self._records_kept:
            kept = [name for name in self._table_names() if name not in RAW_TABLES]
            rows += [
                ("Tables", ", ".join(kept)),
                ("", "Raw records were dropped by keep_records=False."),
                ("Next", "results.report(), flowsim.explain(name)"),
            ]
            return f"Results: {kind}, {settings.duration:g} {settings.time_unit}", rows
        rows.append(("Tables", ", ".join(self._table_names())))
        plots = (
            "results.plot_queue(), results.plot_wait(), results.plot_utilization()"
            if self._supply is None
            else "results.plot_inventory(), results.plot_orders()"
        )
        rows += [
            ("Next", f"results.report(), {plots}"),
            ("", "results.viewer(), results.export(folder), flowsim.explain(name)"),
        ]
        return f"Results: {kind}, {settings.duration:g} {settings.time_unit}", rows

    def _table_names(self) -> list[str]:
        names = [
            "customers",
            "visits",
            "states",
            "stations",
            "summary",
            "activities",
            "failures",
        ]
        if self._supply is not None:
            names += ["inventory", "shipments", "stock_points"]
        return names

    def __init__(
        self,
        customers: list[_Customer],
        visits: list[_Visit],
        states: list[_State],
        activities: list[_Activity],
        failures: list[_Failure],
        inventory: list[_Inventory],
        shipments: list[_Shipment],
        supply: dict | None,
        definitions: dict,
        capacities: dict[str, int],
        duration: float,
        end_time: float,
        drain: bool,
        closing_states: dict[str, _State],
        warmup: float,
        time_unit: str,
        seed: int,
        graph: nx.DiGraph,
        definition: tuple,
    ):
        self.customers = _frame(customers, CUSTOMER_SCHEMA)
        self.visits = _frame(visits, VISIT_SCHEMA)
        self.states = _frame(states, STATE_SCHEMA)
        self.activities = _frame(activities, ACTIVITY_SCHEMA)
        self.failures = _frame(failures, FAILURE_SCHEMA)
        self.inventory = _frame(inventory, INVENTORY_SCHEMA)
        self.shipments = _frame(shipments, SHIPMENT_SCHEMA)
        self.settings = Settings(
            duration=duration,
            warmup=warmup,
            drain=drain,
            seed=seed,
            time_unit=time_unit,
            end_time=end_time,
            capacities=MappingProxyType(dict(capacities)),
        )
        # The chain's order, review period, and stock-point settings, or None
        # for a service network.
        self._supply = supply
        self._definitions = definitions
        self._closing_states = closing_states
        self._graph = graph.copy()
        # Experiment pools only runs whose model definitions match.
        self._definition = definition
        self.stations = self._station_metrics()
        self.summary = self._system_metrics()
        self.stock_points = self._stock_point_metrics()
        self._records_kept = True

    def _station_areas(self) -> pl.DataFrame:
        """Integrate each station's state counts over [warmup, duration).

        A state row holds until the station's next row, so its width is the
        part of that span inside the window. Areas have units customer*time
        and server*time. The largest queue counts only rows with positive width.
        """
        width = (
            (
                pl.col("time")
                .shift(-1)
                .over("station")
                .clip(upper_bound=self.settings.duration)
                - pl.col("time").clip(lower_bound=self.settings.warmup)
            )
            .clip(lower_bound=0)
            .fill_null(0)
        )
        return (
            self.states.with_columns(width.alias("width"))
            .group_by(
                "station",
                maintain_order=True,
            )
            .agg(
                *[
                    (pl.col(field) * pl.col("width")).sum().alias(f"{field}_area")
                    for field in AREA_FIELDS
                ],
                pl.col("waiting")
                .filter(pl.col("width") > 0)
                .max()
                .fill_null(0)
                .alias("max_queue"),
            )
        )

    def _station_counts(self) -> pl.DataFrame:
        """Count each station's visits in the window and its closing states."""

        def in_window(column: str) -> pl.Expr:
            return pl.col(column).is_between(
                lower_bound=self.settings.warmup,
                upper_bound=self.settings.duration,
                closed="left",
            )

        # Waits belong to station arrivals at or after warm-up, with no upper
        # bound, so drained runs include arrivals after closing.
        cohort = pl.col("arrival_time") >= self.settings.warmup
        waits = pl.col("wait_time").filter(cohort)
        visits = self.visits.group_by("station").agg(
            in_window("arrival_time").sum().alias("arrivals"),
            cohort.sum().alias("wait_arrivals"),
            in_window("service_start").sum().alias("service_starts"),
            in_window("service_end").sum().alias("service_completions"),
            waits.count().alias("wait_observations"),
            waits.mean().alias("mean_wait"),
            waits.quantile(
                quantile=0.95,
                interpolation="linear",
            ).alias("p95_wait"),
        )
        closing = _frame(list(self._closing_states.values()), STATE_SCHEMA).select(
            "station",
            pl.col("waiting").alias("waiting_at_close"),
            pl.col("busy").alias("occupied_at_close"),
            pl.col("blocked").alias("blocked_at_close"),
            pl.col("paused").alias("paused_at_close"),
            pl.col("outside").alias("outside_at_close"),
        )
        final = self.states.group_by(
            "station",
            maintain_order=True,
        ).agg(
            pl.col("waiting").last().alias("waiting_at_end"),
            pl.col("busy").last().alias("occupied_at_end"),
        )
        counts = [
            "arrivals",
            "wait_arrivals",
            "service_starts",
            "service_completions",
            "wait_observations",
        ]
        # A station no customer visited has zero counts and no waits.
        return (
            closing.join(
                other=visits,
                on="station",
                how="left",
                maintain_order="left",
            )
            .join(
                other=final,
                on="station",
                how="left",
                maintain_order="left",
            )
            .with_columns(pl.col(counts).fill_null(0))
        )

    def _station_metrics(self) -> pl.DataFrame:
        window = self.settings.duration - self.settings.warmup
        # Utilization is server*time / (servers*time), dimensionless.
        installed = pl.col("capacity") * window
        stations = (
            pl.DataFrame(
                data={
                    "station": list(self._capacities),
                    "capacity": list(self._capacities.values()),
                },
                schema={"station": pl.String, "capacity": pl.Int64},
            )
            .join(
                other=self._station_counts(),
                on="station",
                how="left",
                maintain_order="left",
            )
            .join(
                other=self._station_areas(),
                on="station",
                how="left",
                maintain_order="left",
            )
        )
        return stations.with_columns(
            (pl.col("waiting_area") / window).alias("mean_queue"),
            (pl.col("busy_area") / installed).alias("utilization"),
            (pl.col("processing_area") / installed).alias("processing_utilization"),
            (pl.col("blocked_area") / installed).alias("blocking_fraction"),
            (pl.col("down_area") / installed).alias("downtime_fraction"),
            (pl.col("scheduled_area") / window).alias("mean_scheduled_servers"),
            (pl.col("available_area") / window).alias("mean_available_servers"),
            (pl.col("outside_area") / window).alias("mean_outside_queue"),
            pl.when(pl.col("available_area") == 0)
            .then(None)
            .otherwise(pl.col("processing_area") / pl.col("available_area"))
            .alias("staffed_utilization"),
        ).select(
            [pl.col(column).cast(dtype) for column, dtype in STATION_SCHEMA.items()]
        )

    def _system_metrics(self) -> pl.DataFrame:
        eligible = self.customers.filter(pl.col("status") != Status.REJECTED)
        cohort = eligible.filter(pl.col("arrival_time") >= self.settings.warmup)
        finished = cohort.filter(pl.col("status") == Status.COMPLETED)
        completed = eligible.get_column("exit_time").count()
        rejected = self.customers.height - eligible.height
        # Abandoned customers leave without service, so they are neither
        # completed nor remaining, and their waits stay out of the averages.
        abandoned = eligible.get_column("abandon_time").count()
        abandoned_at_close = eligible.filter(
            pl.col("abandon_time") < self.settings.duration
        ).height
        cohort_abandoned = cohort.get_column("abandon_time").count()
        measurement_arrivals = self.customers.filter(
            pl.col("arrival_time") >= self.settings.warmup
        ).height
        exits = self.customers.filter(
            (pl.col("exit_time") >= self.settings.warmup)
            & (pl.col("exit_time") < self.settings.duration)
        ).height
        completed_at_close = self.customers.filter(
            pl.col("exit_time") < self.settings.duration
        ).height
        window = self.settings.duration - self.settings.warmup
        # Sum each customer's presence clipped to the observation window.
        # Customer*time / time gives the time-average work in process.
        inside = eligible.filter(pl.col("admission_time").is_not_null())
        presence = inside.select(
            (
                pl.coalesce("exit_time", "abandon_time")
                .fill_null(self.settings.duration)
                .clip(upper_bound=self.settings.duration)
                - pl.col("admission_time").clip(lower_bound=self.settings.warmup)
            )
            .clip(lower_bound=0)
            .sum()
            .alias("presence")
        ).item()
        # A run's settings always record its end time.
        end_time = self.settings.end_time
        assert end_time is not None
        summary = pl.DataFrame(
            {
                "arrivals": [self.customers.height],
                "admitted": [self.customers.filter(pl.col("admitted")).height],
                "admitted_at_close": [
                    inside.filter(
                        pl.col("admission_time") < self.settings.duration
                    ).height
                ],
                "outside_at_close": [
                    eligible.filter(
                        (
                            pl.col("admission_time").is_null()
                            | (pl.col("admission_time") >= self.settings.duration)
                        )
                        & (
                            pl.col("abandon_time").is_null()
                            | (pl.col("abandon_time") >= self.settings.duration)
                        )
                    ).height
                ],
                "rejected": [rejected],
                "abandoned": [abandoned],
                "completed": [completed],
                "remaining": [eligible.height - completed - abandoned],
                "completed_at_close": [completed_at_close],
                "remaining_at_close": [
                    eligible.height - completed_at_close - abandoned_at_close
                ],
                "after_close_completions": [completed - completed_at_close],
                "end_time": [end_time],
                "overtime": [end_time - self.settings.duration],
                "measurement_arrivals": [measurement_arrivals],
                # A rejection happens at arrival, so both counts use the event's
                # own time in [warmup, duration), as measurement_completions does.
                "measurement_rejected": [
                    self.customers.filter(
                        (pl.col("status") == Status.REJECTED)
                        & (pl.col("arrival_time") >= self.settings.warmup)
                    ).height
                ],
                # Abandonments count by their own time, like completions. The
                # rate instead follows the customers who arrived after warm-up.
                "measurement_abandoned": [
                    eligible.filter(
                        (pl.col("abandon_time") >= self.settings.warmup)
                        & (pl.col("abandon_time") < self.settings.duration)
                    ).height
                ],
                "abandonment_rate": [
                    cohort_abandoned / measurement_arrivals
                    if measurement_arrivals
                    else None
                ],
                "measurement_admitted": [
                    inside.filter(
                        (pl.col("admission_time") >= self.settings.warmup)
                        & (pl.col("admission_time") < self.settings.duration)
                    ).height
                ],
                "cohort_arrivals": [cohort.height],
                "measurement_completions": [exits],
                "cohort_completions": [finished.height],
                "cohort_remaining": [
                    cohort.height - finished.height - cohort_abandoned
                ],
                "mean_flow_time": [finished.get_column("flow_time").mean()],
                "mean_total_wait": [finished.get_column("total_wait").mean()],
                "mean_total_blocked": [finished.get_column("total_blocked").mean()],
                "mean_outside_wait": [finished.get_column("outside_wait").mean()],
                "throughput": [exits / window],
                "mean_wip": [presence / window],
            },
            schema_overrides={
                "abandonment_rate": pl.Float64,
                "mean_flow_time": pl.Float64,
                "mean_total_wait": pl.Float64,
                "mean_total_blocked": pl.Float64,
                "mean_outside_wait": pl.Float64,
            },
        )
        return summary.select(headline_first(summary.columns, SUMMARY_HEADLINE))

    def _stock_point_metrics(self) -> pl.DataFrame:
        """Summarize each stock point over the review periods in [warmup, duration).

        Means of on-hand stock and backorders average end-of-period values. The
        fill rate is the share of each period's new demand filled from stock in
        that period. The bullwhip ratio divides the variance of orders placed by
        the variance of orders received, both with the n - 1 divisor, and is
        missing with fewer than two periods or constant demand.
        """
        names = [] if self._supply is None else self._supply["chain"][1:]
        window = self.inventory.filter(pl.col("time") >= self.settings.warmup)
        measured = window.group_by("stock_point").agg(
            pl.len().alias("periods"),
            pl.col("demand").mean().alias("mean_demand"),
            pl.col("order_quantity").mean().alias("mean_order"),
            pl.col("demand").var(ddof=1).alias("demand_variance"),
            pl.col("order_quantity").var(ddof=1).alias("order_variance"),
            pl.col("demand").sum().alias("demanded"),
            pl.col("filled").sum().alias("filled"),
            pl.col("on_hand").mean().alias("mean_on_hand"),
            pl.col("backorders").mean().alias("mean_backorders"),
            pl.col("lost").sum().alias("lost_units"),
        )
        return (
            pl.DataFrame(
                data={"stock_point": names},
                schema={"stock_point": pl.String},
            )
            .join(
                other=measured,
                on="stock_point",
                how="left",
                maintain_order="left",
            )
            .with_columns(
                pl.when(pl.col("demand_variance") > 0)
                .then(pl.col("order_variance") / pl.col("demand_variance"))
                .alias("bullwhip_ratio"),
                pl.when(pl.col("demanded") > 0)
                .then(pl.col("filled") / pl.col("demanded"))
                .alias("fill_rate"),
                pl.col("periods").fill_null(0),
            )
            .select(
                [
                    pl.col(column).cast(dtype)
                    for column, dtype in STOCK_POINT_SCHEMA.items()
                ]
            )
        )

    def report(self) -> pl.DataFrame:
        """List every replication metric that applies to this run, one per row.

        The columns are scope, location (the station or stock point, null for a
        system metric), metric, label, value, and units in the run's time unit.
        Rows follow the catalog: system metrics, then each station's metrics,
        then each stock point's. A scope that the model lacks has no rows, so a
        service network lists no stock-point metrics, and a supply chain without
        production stations lists only its stock-point metrics and the run's
        end_time and overtime.

        Returns
        -------
        polars.DataFrame
            One row per metric and location, with the columns above.

        Example
        -------
        >>> results.report().filter(pl.col("scope") == "system")
        """
        stations = list(self._capacities)
        stock_points = self.stock_points.get_column("stock_point").to_list()
        rows = []
        for names, column, table, places in [
            (SYSTEM_METRICS, None, self.summary, [None]),
            (STATION_METRICS, "station", self.stations, stations),
            (STOCK_POINT_METRICS, "stock_point", self.stock_points, stock_points),
        ]:
            names = [
                name
                for name in names
                if inapplicable(
                    name,
                    stations=bool(stations),
                    stock_points=bool(stock_points),
                    supply=self._supply is not None,
                )
                is None
            ]
            if not names:
                continue
            for place in places:
                values = (
                    table if place is None else table.filter(pl.col(column) == place)
                ).row(
                    0,
                    named=True,
                )
                rows += [
                    {
                        "scope": METRICS[name].scope,
                        "location": place,
                        "metric": name,
                        "label": METRICS[name].label,
                        "value": None if values[name] is None else float(values[name]),
                        "units": metric_units(name, self.settings.time_unit),
                    }
                    for name in names
                ]
        return pl.DataFrame(
            data=rows,
            schema={
                "scope": pl.String,
                "location": pl.String,
                "metric": pl.String,
                "label": pl.String,
                "value": pl.Float64,
                "units": pl.String,
            },
        )

    # plots imports METRICS from this module at load time, so each plot
    # method imports its function when called.
    def plot_queue(self, station: str | None = None) -> Figure:
        """Plot waiting customers and occupied servers over time.

        Without a station, a menu chooses among the stations. A named station
        is the only one drawn.

        Parameters
        ----------
        station : str, optional
            Name of one station. Without it, all stations are drawn.

        Returns
        -------
        plotly.graph_objects.Figure
            The queue-length figure.

        Example
        -------
        >>> results.plot_queue("Desk").show()
        """
        self._require_records("plot_queue()")
        from flowsim.plots import plot_queue, require_stations

        require_stations(self)

        return plot_queue(self, station=station)

    def plot_wait(self, station: str | None = None) -> Figure:
        """Plot the waiting-time histogram of station arrivals after warm-up.

        Parameters
        ----------
        station : str, optional
            Name of one station. Without it, all stations are drawn.

        Returns
        -------
        plotly.graph_objects.Figure
            The waiting-time histogram.

        Example
        -------
        >>> results.plot_wait("Desk").show()
        """
        self._require_records("plot_wait()")
        from flowsim.plots import plot_wait, require_stations

        require_stations(self)

        return plot_wait(self, station=station)

    def plot_utilization(self, station: str | None = None) -> Figure:
        """Plot each station's occupied share of capacity, or one station's.

        Parameters
        ----------
        station : str, optional
            Name of one station. Without it, every station is drawn.

        Returns
        -------
        plotly.graph_objects.Figure
            The utilization figure.

        Example
        -------
        >>> results.plot_utilization().show()
        """
        self._require_records("plot_utilization()")
        from flowsim.plots import plot_utilization, require_stations

        require_stations(self)

        return plot_utilization(self, station=station)

    def plot_resources(self, station: str | None = None) -> Figure:
        """Plot processing, blocked, paused, down, and staffed servers over time.

        Parameters
        ----------
        station : str, optional
            Name of one station. Without it, all stations are drawn.

        Returns
        -------
        plotly.graph_objects.Figure
            The server-state figure.

        Example
        -------
        >>> results.plot_resources("Desk").show()
        """
        self._require_records("plot_resources()")
        from flowsim.plots import plot_resources, require_stations

        require_stations(self)

        return plot_resources(self, station=station)

    def plot_customer(self, customer_id: int) -> Figure:
        """Plot one customer's waiting, service, paused, and blocked time.

        Parameters
        ----------
        customer_id : int
            The customer_id of a row in the customers table, starting at 1.

        Returns
        -------
        plotly.graph_objects.Figure
            The customer's timeline.

        Example
        -------
        >>> results.plot_customer(1).show()
        """
        self._require_records("plot_customer()")
        from flowsim.plots import plot_customer

        return plot_customer(self, customer_id)

    def plot_inventory(self, stock_point: str | None = None) -> Figure:
        """Plot stock on hand, backorders, and orders at each review.

        Without a stock point, a menu chooses among the stock points. A named
        stock point is the only one drawn.

        Parameters
        ----------
        stock_point : str, optional
            Name of one stock point. Without it, all stock points are drawn.

        Returns
        -------
        plotly.graph_objects.Figure
            The inventory figure. It applies to a supply chain.

        Example
        -------
        >>> results.plot_inventory("Store").show()
        """
        self._require_records("plot_inventory()")
        from flowsim.plots import plot_inventory

        return plot_inventory(self, stock_point=stock_point)

    def plot_orders(self) -> Figure:
        """Plot consumer demand and every stage's orders, which shows the bullwhip.

        Returns
        -------
        plotly.graph_objects.Figure
            The orders figure. It applies to a supply chain.

        Example
        -------
        >>> results.plot_orders().show()
        """
        self._require_records("plot_orders()")
        from flowsim.plots import plot_orders

        return plot_orders(self)

    def viewer(self, path: str | Path | None = None) -> Viewer:
        """Build the offline results page, saving it when a path is given.

        A notebook displays the returned Viewer. A script calls its save(path)
        or open() method.

        Parameters
        ----------
        path : str or pathlib.Path, optional
            File to save the page to. Without it, nothing is written.

        Returns
        -------
        Viewer
            The page.

        Example
        -------
        >>> results.viewer("output/run.html")
        """
        self._require_records("viewer()")
        from flowsim.plots import supply_viewer_html, viewer_html

        if self._supply is None:
            page = Viewer(
                document=viewer_html(self),
                kind="results page",
                height=900,
            )
        else:
            page = Viewer(
                document=supply_viewer_html(self),
                kind="supply-chain results page",
                height=900,
            )
        if path is not None:
            page.save(path)
        return page

    def export(self, directory: str | Path) -> Path:
        """Export raw records, metrics, and their measurement definitions.

        Writes one CSV file per table (customers, visits, states, stations,
        summary, activities, and failures, plus inventory, shipments, and
        stock_points for a supply chain) and metadata.json with the settings,
        routes, and measurement definitions. Missing values stay empty. FlowSim
        export files from an earlier export that this one does not write are
        removed.

        Parameters
        ----------
        directory : str or pathlib.Path
            Folder to write to. It is created if needed.

        Returns
        -------
        pathlib.Path
            The folder.

        Example
        -------
        >>> results.export("output/my-run")
        """
        self._require_records("export()")
        destination = Path(directory)
        destination.mkdir(
            parents=True,
            exist_ok=True,
        )
        names = self._table_names()
        for name in names:
            getattr(self, name).write_csv(destination / f"{name}.csv")
        metadata = {
            "time_unit": self.settings.time_unit,
            "duration": self.settings.duration,
            "end_time": self.settings.end_time,
            "drain": self.settings.drain,
            "warmup": self.settings.warmup,
            "seed": self.settings.seed,
            "capacities": dict(self._capacities),
            "definitions": self._definitions,
            # A typed edge lists each type that may take it, with its probability.
            "routes": [
                {"from": origin, "to": target, "probability": data["probability"]}
                if "probability" in data
                else {"from": origin, "to": target, "types": dict(data["types"])}
                for origin, target, data in self._graph.edges(data=True)
            ],
            "state_window": "[warmup, duration)",
            "wait_cohort": (
                "Visits admitted to the station's line at or after warmup with "
                "observed service starts, including visits admitted after closing "
                "when drained"
            ),
            "flow_cohort": "System arrivals at or after warmup with observed exits",
            "censoring": "Missing starts and exits remain null, never zero",
        }
        if self._supply is not None:
            metadata["supply"] = self._supply
            metadata["inventory_window"] = (
                "Review periods at times in [warmup, duration)"
            )
            metadata["shipment_arrivals"] = (
                "Null for shipments still in transit at the end"
            )
        _write_metadata(destination / "metadata.json", metadata)
        remove_stale_exports(
            destination,
            {f"{name}.csv" for name in names} | {"metadata.json"},
        )
        return destination


class Experiment:
    """Independent runs and Student t intervals across replication means.

    Model.experiment returns an Experiment. Each replication has its own seed,
    and the intervals treat each run's metric as one independent observation.

    Attributes
    ----------
    runs : list of Results
        The replications, in order.
    settings : Settings
        The settings the runs share, with no seed or end time.
    summary, stations, stock_points : polars.DataFrame
        Each run's tables stacked, with a replication column (starting at 1).
    stock_point_names : list of str
        The stock points in chain order, empty for a service network.

    The common next calls are intervals, plot, viewer, and export. Call
    flowsim.metrics() for the metric names.

    Example
    -------
    >>> experiment = model.experiment(duration=480, replications=30)
    >>> experiment.intervals("mean_total_wait")
    """

    runs: list[Results]

    def __init__(self, runs: list[Results]):
        runs = list(runs)
        if len(runs) < 2:
            raise ValueError("An experiment needs at least two runs.")
        if len({run.settings.seed for run in runs}) != len(runs):
            raise ValueError(
                "Replications need distinct seeds. A repeated run is not an "
                "independent observation."
            )
        # The model check below also covers station names and capacities.
        if any(_run_settings(run) != _run_settings(runs[0]) for run in runs):
            raise ValueError(
                "Replications need the same duration, warm-up, drain rule, "
                "and time unit."
            )
        if any(run._definition != runs[0]._definition for run in runs):
            raise ValueError(
                "Replications need runs of the same model. Separately built "
                "models count as different when their sampling functions are "
                "different objects, so run every replication from one Model."
            )
        self.runs = runs

    def __getattr__(self, name: str) -> object:
        if name.startswith("_"):
            raise AttributeError(
                f"{type(self).__name__!r} object has no attribute {name!r}"
            )
        hints = moved_settings(
            owner="experiment",
            names=["duration", "warmup", "drain", "time_unit"],
        )
        hints["differences"] = (
            "An experiment is one scenario. Use flowsim.compare({name: model, "
            "...}, duration) to compare scenarios with paired differences."
        )
        raise missing_attribute(self, name, hints)

    def __repr__(self) -> str:
        return display_text(*self._display())

    def _repr_html_(self) -> str:
        return display_html(*self._display())

    def _display(self) -> tuple[str, list[tuple[str, str]]]:
        seeds = [run.settings.seed for run in self.runs]
        listed = ", ".join(str(seed) for seed in seeds[:3])
        if len(seeds) > 3:
            listed += f", ... (first 3 of {len(seeds)}, spawned from the seed argument)"
        names = self.stock_point_names or self.runs[0].stations["station"].to_list()
        rows = [
            ("Settings", window_line(self.settings)),
            ("Seeds", listed),
            (
                "Stock points" if self.stock_point_names else "Stations",
                ", ".join(names),
            ),
            ("Next", "experiment.intervals(metric), experiment.plot()"),
            ("", "experiment.viewer(), experiment.export(folder), flowsim.metrics()"),
        ]
        if not self.runs[0]._records_kept:
            rows.insert(
                3,
                ("Records", "Raw records were dropped by keep_records=False."),
            )
        kind = "service network" if self.runs[0]._supply is None else "supply chain"
        return f"Experiment: {len(self.runs)} replications of a {kind}", rows

    # The pooled tables are built from the runs on each access, so estimates
    # and exports always read the runs' current values.
    @property
    def stations(self) -> pl.DataFrame:
        """Return every run's stations table, stacked, with a replication column."""
        return pl.concat(
            [
                run.stations.select(
                    pl.lit(index).alias("replication"),
                    pl.all(),
                )
                for index, run in enumerate(self.runs, start=1)
            ]
        )

    @property
    def stock_points(self) -> pl.DataFrame:
        """Return every run's stock_points table, stacked, with a replication column."""
        return pl.concat(
            [
                run.stock_points.select(
                    pl.lit(index).alias("replication"),
                    pl.all(),
                )
                for index, run in enumerate(self.runs, start=1)
            ]
        )

    @property
    def summary(self) -> pl.DataFrame:
        """Return every run's summary table, stacked, with a replication column."""
        return pl.concat(
            [
                run.summary.select(
                    pl.lit(index).alias("replication"),
                    pl.all(),
                )
                for index, run in enumerate(self.runs, start=1)
            ]
        )

    @property
    def settings(self) -> Settings:
        """Return the settings the runs share, with no seed or end time."""
        return replace(
            self.runs[0].settings,
            seed=None,
            end_time=None,
        )

    @property
    def stock_point_names(self) -> list[str]:
        """Return the stock points in chain order, empty for a service network."""
        supply = self.runs[0]._supply
        return [] if supply is None else supply["chain"][1:]

    # plots imports METRICS from this module at load time, and reporting imports
    # this module, so each reporting method imports its function when called.
    def intervals(
        self,
        metric: str = "mean_total_wait",
        *,
        station: str | None = None,
        stock_point: str | None = None,
        confidence: float = 0.95,
    ) -> pl.DataFrame:
        """Estimate a metric across runs with Student t intervals.

        A system metric gives one row with a null station. A station metric
        gives one row per station unless station= names one, and a stock-point
        metric gives one row per stock point unless stock_point= names one, in
        a stock_point column that replaces the station column. Missing run
        values are excluded and counted in observed_runs.

        Parameters
        ----------
        metric : str, default 'mean_total_wait'
            A replication metric name from flowsim.metrics().
        station : str, optional
            Station to report, for a station metric. Without it, every station.
        stock_point : str, optional
            Stock point to report, for a stock-point metric. Without it, every
            stock point.
        confidence : float, default 0.95
            Confidence level of the interval, strictly between 0 and 1.

        Returns
        -------
        polars.DataFrame
            One row per location with the mean, interval limits, and
            observed_runs.

        Example
        -------
        >>> experiment.intervals("utilization", station="Desk", confidence=0.9)
        """
        from flowsim.reporting import experiment_intervals

        return experiment_intervals(
            experiment=self,
            metric=metric,
            station=station,
            stock_point=stock_point,
            confidence=confidence,
        )

    def plot(
        self,
        metric: str = "mean_total_wait",
        *,
        station: str | None = None,
        stock_point: str | None = None,
        confidence: float = 0.95,
    ) -> Figure:
        """Plot the intervals for a metric, one point per location it covers.

        Parameters
        ----------
        metric : str, default 'mean_total_wait'
            A replication metric name from flowsim.metrics().
        station : str, optional
            Station to plot, for a station metric. Without it, every station.
        stock_point : str, optional
            Stock point to plot, for a stock-point metric. Without it, every
            stock point.
        confidence : float, default 0.95
            Confidence level of the interval, strictly between 0 and 1.

        Returns
        -------
        plotly.graph_objects.Figure
            The interval figure.

        Example
        -------
        >>> experiment.plot("mean_total_wait").show()
        """
        from flowsim.reporting import interval_figure

        return interval_figure(
            table=self.intervals(
                metric=metric,
                station=station,
                stock_point=stock_point,
                confidence=confidence,
            ),
            metric=metric,
            time_unit=self.settings.time_unit,
        )

    def viewer(
        self,
        path: str | Path | None = None,
        *,
        metric: str = "mean_total_wait",
        station: str | None = None,
        stock_point: str | None = None,
        confidence: float = 0.95,
    ) -> Viewer:
        """Build an offline page of one metric's intervals, saved to path if given.

        Parameters
        ----------
        path : str or pathlib.Path, optional
            File to save the page to. Without it, nothing is written.
        metric : str, default 'mean_total_wait'
            A replication metric name from flowsim.metrics().
        station : str, optional
            Station to report, for a station metric.
        stock_point : str, optional
            Stock point to report, for a stock-point metric.
        confidence : float, default 0.95
            Confidence level of the interval, strictly between 0 and 1.

        Returns
        -------
        Viewer
            The page.

        Example
        -------
        >>> experiment.viewer("output/experiment.html")
        """
        from flowsim.reporting import page, window_text

        settings = self.settings
        document = page(
            heading="Replication intervals",
            text=window_text(
                metric,
                duration=settings.duration,
                warmup=settings.warmup,
                drain=settings.drain,
                time_unit=settings.time_unit,
            ),
            metric=metric,
            table=self.intervals(
                metric=metric,
                station=station,
                stock_point=stock_point,
                confidence=confidence,
            ),
            time_unit=settings.time_unit,
            confidence=confidence,
            means=self.plot(
                metric=metric,
                station=station,
                stock_point=stock_point,
                confidence=confidence,
            ),
        )
        viewer = Viewer(
            document=document,
            kind="replication page",
            height=800,
        )
        if path is not None:
            viewer.save(path)
        return viewer

    def export(
        self,
        directory: str | Path,
        *,
        metric: str = "mean_total_wait",
        station: str | None = None,
        stock_point: str | None = None,
        confidence: float = 0.95,
    ) -> Path:
        """Write the pooled run tables, one metric's intervals, and metadata.

        The folder receives runs.csv (the pooled summary), stations.csv,
        stock_points.csv for a supply chain, intervals.csv, and metadata.json
        with the settings, replication seeds, metric, and confidence level.

        Parameters
        ----------
        directory : str or pathlib.Path
            Folder to write to. It is created if needed.
        metric : str, default 'mean_total_wait'
            A replication metric name from flowsim.metrics().
        station : str, optional
            Station to report, for a station metric.
        stock_point : str, optional
            Stock point to report, for a stock-point metric.
        confidence : float, default 0.95
            Confidence level of the interval, strictly between 0 and 1.

        Returns
        -------
        pathlib.Path
            The folder.

        Example
        -------
        >>> experiment.export("output/experiment", metric="utilization")
        """
        from flowsim.reporting import export_tables, request_metadata

        intervals = self.intervals(
            metric=metric,
            station=station,
            stock_point=stock_point,
            confidence=confidence,
        )
        return export_tables(
            directory,
            summary=self.summary,
            stations=self.stations,
            stock_points=self.stock_points if self.stock_point_names else None,
            intervals=intervals,
            differences=None,
            metadata=request_metadata(
                experiment=self,
                metric=metric,
                station=station,
                stock_point=stock_point,
                confidence=confidence,
            ),
        )
