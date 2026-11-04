"""Interval tables, plots, pages, and exports shared by experiments and comparisons.

Experiment and Comparison call these functions, so the same request gives the
same rows, figure, page, and files in both. A request names a metric and, for
a station or stock-point metric, optionally one location. Without a location,
a station metric covers every station and a stock-point metric covers every
stock point.
"""

from __future__ import annotations

import html
import re
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import plotly.graph_objects as go
import polars as pl

from flowsim.plots import BLUE, GRAY, STAGE_COLORS, label, style
from flowsim.results import (
    METRICS,
    Inapplicable,
    _write_metadata,
    confidence_level,
    inapplicable,
    interval_estimate,
    interval_frame,
    metric_error,
    metric_units,
    remove_stale_exports,
    scope_name,
    unknown,
)

if TYPE_CHECKING:
    from flowsim.results import Experiment

# Interval-table column headings on the report page.
_HEADINGS = {
    "scenario": "Scenario",
    "station": "Station",
    "stock_point": "Stock point",
}


def location_column(metric: str) -> str:
    """Name the interval table's location column for a metric.

    Stock-point metrics use a stock_point column. Every other metric keeps the
    station column, which is null for a system metric.
    """
    return "stock_point" if METRICS[metric].scope == "stock_point" else "station"


def check_request(metric: str, station: str | None, stock_point: str | None) -> None:
    """Reject an unknown metric or a location argument that its scope lacks."""
    if metric not in METRICS:
        raise metric_error(metric)
    scope = METRICS[metric].scope
    kind = scope_name(metric)
    if station is not None and scope != "station":
        raise ValueError(
            f"{metric!r} is a {kind} metric, so it takes no station=. Station "
            "metrics such as 'mean_wait' take station=."
        )
    if stock_point is not None and scope != "stock_point":
        raise ValueError(
            f"{metric!r} is a {kind} metric, so it takes no stock_point=. "
            "Stock-point metrics such as 'fill_rate' take stock_point=."
        )


def locations(
    experiment: Experiment,
    metric: str,
    station: str | None,
    stock_point: str | None,
) -> list[str | None]:
    """Return the locations a checked request covers in one experiment.

    A system metric covers one location, None. A station or stock-point metric
    covers the named location or, when none is named, every one in definition
    order. A metric that the model cannot measure raises Inapplicable.
    """
    stations = list(experiment.settings.capacities)
    stock_points = experiment.stock_point_names
    # Every supply chain has a stock point, and no service network has one.
    error = inapplicable(
        metric,
        stations=bool(stations),
        stock_points=bool(stock_points),
        supply=bool(stock_points),
    )
    if error is not None:
        raise error
    scope = METRICS[metric].scope
    if scope == "system":
        return [None]
    if scope == "station":
        names, chosen, kind = stations, station, "station"
    else:
        names, chosen, kind = stock_points, stock_point, "stock point"
    if chosen is None:
        return names
    if chosen not in names:
        raise unknown(
            kind=kind,
            name=chosen,
            choices=names,
        )
    return [chosen]


def scenario_locations(
    experiments: Mapping[str, Experiment],
    metric: str,
    station: str | None,
    stock_point: str | None,
) -> dict[str, list[str | None]]:
    """Return the locations a checked request covers in each scenario.

    A named location must exist in every scenario. Without one, a scenario
    whose model cannot measure the metric adds no station or stock-point rows
    and a row of missing or zero system values, so a comparison of a supply
    chain with and without production stations still reports the jobs of the
    scenarios that have them. The request fails only when no scenario applies.
    """
    found = {}
    skipped = []
    for name, experiment in experiments.items():
        try:
            found[name] = locations(
                experiment=experiment,
                metric=metric,
                station=station,
                stock_point=stock_point,
            )
        except Inapplicable as error:
            if station is not None or stock_point is not None:
                raise ValueError(f"Scenario {name!r}: {error}") from None
            skipped.append(error)
            found[name] = [None] if METRICS[metric].scope == "system" else []
        except ValueError as error:
            raise ValueError(f"Scenario {name!r}: {error}") from None
    if len(skipped) == len(experiments):
        raise skipped[0]
    return found


def run_values(
    experiment: Experiment,
    metric: str,
    names: list[str | None],
) -> dict[str | None, np.ndarray]:
    """Return each location's values, one per replication in replication order."""
    pooled = getattr(experiment, METRICS[metric].table)
    column = location_column(metric)
    expected = list(range(1, len(experiment.runs) + 1))
    values = {}
    for name in names:
        rows = pooled if name is None else pooled.filter(pl.col(column) == name)
        rows = rows.sort("replication")
        if rows.get_column("replication").to_list() != expected:
            raise ValueError("Some replications are missing or duplicated.")
        values[name] = np.asarray(
            rows.get_column(metric).to_numpy(),
            dtype=float,
        )
    return values


def estimate_rows(
    experiment: Experiment,
    metric: str,
    names: list[str | None],
    level: float,
) -> list[dict]:
    """Estimate one interval per location across an experiment's runs."""
    values = run_values(
        experiment=experiment,
        metric=metric,
        names=names,
    )
    return [
        {
            "metric": metric,
            location_column(metric): name,
            "runs": len(experiment.runs),
            **interval_estimate(values[name], level),
            "confidence": level,
        }
        for name in names
    ]


def experiment_intervals(
    experiment: Experiment,
    metric: str,
    station: str | None,
    stock_point: str | None,
    confidence: float,
) -> pl.DataFrame:
    level = confidence_level(confidence)
    check_request(
        metric=metric,
        station=station,
        stock_point=stock_point,
    )
    names = locations(
        experiment=experiment,
        metric=metric,
        station=station,
        stock_point=stock_point,
    )
    return interval_frame(
        rows=estimate_rows(
            experiment=experiment,
            metric=metric,
            names=names,
            level=level,
        ),
        keys=["metric", location_column(metric)],
    )


def comparison_intervals(
    experiments: Mapping[str, Experiment],
    metric: str,
    station: str | None,
    stock_point: str | None,
    confidence: float,
) -> pl.DataFrame:
    level = confidence_level(confidence)
    check_request(
        metric=metric,
        station=station,
        stock_point=stock_point,
    )
    found = scenario_locations(
        experiments=experiments,
        metric=metric,
        station=station,
        stock_point=stock_point,
    )
    rows = []
    for name, experiment in experiments.items():
        try:
            estimates = estimate_rows(
                experiment=experiment,
                metric=metric,
                names=found[name],
                level=level,
            )
        except ValueError as error:
            raise ValueError(f"Scenario {name!r}: {error}") from None
        rows += [{"scenario": name, **row} for row in estimates]
    return interval_frame(
        rows=rows,
        keys=["scenario", "metric", location_column(metric)],
    )


def comparison_differences(
    experiments: Mapping[str, Experiment],
    reference: str,
    metric: str,
    station: str | None,
    stock_point: str | None,
    confidence: float,
) -> pl.DataFrame:
    """Estimate each scenario minus the baseline within matched replications.

    Each scenario is paired with the baseline at every location they share. A
    missing value in either run excludes that pair, not other observations.
    """
    level = confidence_level(confidence)
    check_request(
        metric=metric,
        station=station,
        stock_point=stock_point,
    )
    found = scenario_locations(
        experiments=experiments,
        metric=metric,
        station=station,
        stock_point=stock_point,
    )
    column = location_column(metric)
    seeds = [run.settings.seed for run in experiments[reference].runs]
    try:
        baseline = run_values(
            experiment=experiments[reference],
            metric=metric,
            names=found[reference],
        )
    except ValueError as error:
        raise ValueError(f"Scenario {reference!r}: {error}") from None
    rows = []
    for name, experiment in experiments.items():
        if name == reference:
            continue
        if [run.settings.seed for run in experiment.runs] != seeds:
            raise ValueError("Paired scenarios need identical replication seeds.")
        shared = [place for place in found[reference] if place in found[name]]
        try:
            values = run_values(
                experiment=experiment,
                metric=metric,
                names=shared,
            )
        except ValueError as error:
            raise ValueError(f"Scenario {name!r}: {error}") from None
        rows += [
            {
                "scenario": name,
                "baseline": reference,
                "metric": metric,
                column: place,
                "runs": len(experiment.runs),
                **interval_estimate(values[place] - baseline[place], level),
                "confidence": level,
            }
            for place in shared
        ]
    return interval_frame(
        rows=rows,
        keys=["scenario", "baseline", "metric", column],
    )


def interval_figure(
    table: pl.DataFrame,
    metric: str,
    time_unit: str,
    *,
    differences: bool = False,
) -> go.Figure:
    """Draw each interval-table row as a mean with its confidence limits.

    Rows are scenarios in a comparison and locations in an experiment. When a
    comparison covers several locations, each row names both, and each location
    has its own color.
    """
    column = location_column(metric)
    rows = table.to_dicts()
    places = list(dict.fromkeys(row[column] for row in rows))
    several = len(places) > 1
    scenarios = "scenario" in table.columns

    def row_label(row: dict) -> str:
        place = "System" if row[column] is None else label(row[column])
        if not scenarios:
            return place
        return label(row["scenario"]) + (f"<br>{place}" if several else "")

    figure = go.Figure()
    for index, place in enumerate(places):
        chosen = [row for row in rows if row[column] == place]
        where = "" if place is None else f"<br>{label(place)}"
        color = (
            STAGE_COLORS[index % len(STAGE_COLORS)] if scenarios and several else BLUE
        )
        figure.add_trace(
            go.Scatter(
                x=[row["mean"] for row in chosen],
                y=[row_label(row) for row in chosen],
                name="System" if place is None else label(place),
                meta=place,
                mode="markers",
                marker={
                    "size": 12,
                    "color": color,
                    "line": {"color": "black", "width": 1},
                },
                error_x={
                    "type": "data",
                    "array": [
                        None if row["upper"] is None else row["upper"] - row["mean"]
                        for row in chosen
                    ],
                    "thickness": 2.5,
                    "width": 5,
                },
                showlegend=scenarios and several,
                hovertemplate=(
                    f"%{{y}}{'' if scenarios and several else where}"
                    "<br>Estimate: %{x:.3f}<extra></extra>"
                ),
            )
        )
    fraction = METRICS[metric].kind == "fraction"
    axis_label = METRICS[metric].label
    if len(places) == 1 and places[0] is not None:
        axis_label += f" at {places[0]}"
    if not fraction:
        axis_label += f" ({metric_units(metric, time_unit)})"
    if differences:
        axis_label = "Difference in " + axis_label[0].lower() + axis_label[1:]
    if scenarios:
        y_label = "Scenario"
    elif places and places[0] is not None:
        y_label = _HEADINGS[column]
    else:
        y_label = ""
    style(
        figure=figure,
        x_label=axis_label,
        y_label=y_label,
    )
    figure.update_layout(
        height=max(240, 150 + 50 * len(rows)),
        margin={"l": 155, "r": 35, "t": 35, "b": 80},
    )
    # List rows top to bottom in the order they were defined.
    figure.update_yaxes(
        autorange="reversed",
        automargin=True,
    )
    if fraction:
        figure.update_xaxes(tickformat=".0%")
    if differences:
        figure.add_vline(
            x=0,
            line_color=GRAY,
            line_dash="dash",
        )
    return figure


def window_text(
    metric: str,
    *,
    duration: float,
    warmup: float,
    drain: bool,
    time_unit: str,
) -> str:
    """Describe the measurement window behind a page's intervals."""
    if METRICS[metric].scope == "stock_point":
        return (
            f"Stock points review each period until {duration:g} {time_unit}. "
            f"Measurement begins at {warmup:g} {time_unit}."
        )
    return (
        f"Operating hours end at {duration:g} {time_unit}. "
        f"Measurement begins at {warmup:g} {time_unit}. "
        + (
            "Arrivals stopped at closing, and the run continued until every "
            "customer who was not rejected had completed service or abandoned."
            if drain
            else "Service stops at closing. Waiting and flow averages include "
            "observed outcomes."
        )
    )


def page(
    *,
    heading: str,
    text: str,
    metric: str,
    table: pl.DataFrame,
    time_unit: str,
    confidence: float,
    means: go.Figure,
    changes: go.Figure | None = None,
    reference: str | None = None,
) -> str:
    """Fill the offline report template with one metric's intervals.

    The page shows the interval plot and table, and, when changes is given,
    the paired differences from the reference scenario.
    """
    # plots.style sets an 800-pixel width, so let each card set the width.
    for figure in (means, changes):
        if figure is not None:
            figure.update_layout(width=None, autosize=True)
    means_html = means.to_html(
        full_html=False,
        include_plotlyjs=True,
        div_id="scenario-means",
    )
    fraction = METRICS[metric].kind == "fraction"
    units = html.escape("percent" if fraction else metric_units(metric, time_unit))
    column = location_column(metric)
    # The location column appears when the table names a location.
    keys = [
        key
        for key in ["scenario", column]
        if key in table.columns and table.get_column(key).drop_nulls().len() > 0
    ]

    def cell(row: dict, key: str) -> str:
        if row["mean"] is None:
            return "Not observed"
        if row[key] is None:
            return "Needs two runs"
        return f"{row[key]:.1%}" if fraction else f"{row[key]:.3f}"

    header = "".join(f"<th>{_HEADINGS[key]}</th>" for key in keys) + "".join(
        f"<th>{name} ({units})</th>" for name in ["Mean", "Lower limit", "Upper limit"]
    )
    header += "<th>Observed runs</th>"
    table_rows = ""
    for row in table.to_dicts():
        cells = [
            *[html.escape(row[key]) for key in keys],
            *[cell(row, key) for key in ["mean", "lower", "upper"]],
            str(row["observed_runs"]),
        ]
        table_rows += "<tr>" + "".join(f"<td>{value}</td>" for value in cells) + "</tr>"
    title = METRICS[metric].label
    places = table.get_column(column).unique(maintain_order=True).to_list()
    if len(places) == 1 and places[0] is not None:
        title += f" at {places[0]}"
    differences = ""
    if changes is not None:
        changes_html = changes.to_html(
            full_html=False,
            include_plotlyjs=False,
            div_id="scenario-differences",
        )
        differences = (
            f"<section><h2>Difference from {html.escape(reference)}</h2>\n"
            "<p>Each difference is the scenario value minus its baseline value "
            "within the same\nreplication. Negative values indicate a smaller "
            "metric. The dashed line marks zero.</p>\n"
            f"{changes_html}</section>"
        )
    values = {
        "HEADING": html.escape(heading),
        "TEXT": html.escape(text),
        "TITLE": html.escape(title),
        "CONFIDENCE": f"{confidence * 100:g}%",
        "MEANS": means_html,
        "HEADER": header,
        "TABLE_ROWS": table_rows,
        "DIFFERENCES": differences,
    }
    template = Path(__file__).with_name("comparison.html").read_text(encoding="utf-8")
    # One pass over the template, so a placeholder-like scenario name or
    # Plotly text inside a value is never replaced.
    return re.sub(
        pattern=r"__([A-Z_]+)__",
        repl=lambda match: values[match.group(1)],
        string=template,
    )


def export_tables(
    directory: str | Path,
    *,
    summary: pl.DataFrame,
    stations: pl.DataFrame,
    stock_points: pl.DataFrame | None,
    intervals: pl.DataFrame,
    differences: pl.DataFrame | None,
    metadata: dict,
) -> Path:
    """Write pooled run tables, intervals, and metadata, removing stale files."""
    destination = Path(directory)
    destination.mkdir(
        parents=True,
        exist_ok=True,
    )
    tables = {
        "runs.csv": summary,
        "stations.csv": stations,
        "stock_points.csv": stock_points,
        "intervals.csv": intervals,
        "differences.csv": differences,
    }
    written = {name for name, table in tables.items() if table is not None}
    for name in written:
        tables[name].write_csv(destination / name)
    _write_metadata(destination / "metadata.json", metadata)
    remove_stale_exports(destination, written | {"metadata.json"})
    return destination


def request_metadata(
    experiment: Experiment,
    metric: str,
    station: str | None,
    stock_point: str | None,
    confidence: float,
) -> dict:
    """Describe an export's request, settings, and replication seeds."""
    settings = experiment.settings
    return {
        "metric": metric,
        "station": station,
        "stock_point": stock_point,
        "confidence": confidence,
        "time_unit": settings.time_unit,
        "duration": settings.duration,
        "warmup": settings.warmup,
        "drain": settings.drain,
        "replication_seeds": [run.settings.seed for run in experiment.runs],
    }
