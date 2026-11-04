"""Plotly figures and an offline viewer, with no notebook dependency."""

from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import TYPE_CHECKING

import networkx as nx
import plotly.graph_objects as go
import polars as pl
from plotly.offline import get_plotlyjs

from flowsim.results import METRICS, Phase, Status, unknown
from flowsim.validation import integer

if TYPE_CHECKING:
    from flowsim.model import Model
    from flowsim.results import Results

BLUE = "#0072B2"
ORANGE = "#D55E00"
GREEN = "#009E73"
PURPLE = "#CC79A7"
GRAY = "#667085"
# Marks a diagram node that keeps the model from running.
WARNING = "#C62828"

# Customer timeline activities in legend order, with their bar colors.
TIMELINE_COLORS = {
    "Waiting": BLUE,
    "In service": ORANGE,
    "Paused": PURPLE,
    "Blocked": GREEN,
    "Outside": GRAY,
}


def label(text: str) -> str:
    """Escape model text, since Plotly renders a subset of HTML in labels."""
    return html.escape(text, quote=False)


def style(figure: go.Figure, x_label: str, y_label: str) -> go.Figure:
    figure.update_layout(
        template="plotly_white",
        width=800,
        height=500,
        font={"family": "Georgia, serif", "size": 14},
        xaxis={"title": label(x_label), "rangemode": "tozero"},
        yaxis={"title": label(y_label), "rangemode": "tozero"},
        margin={"l": 85, "r": 30, "t": 35, "b": 70},
        legend={"orientation": "h", "y": 1.14, "x": 0},
        hovermode="closest",
    )
    return figure


def station_menu(figure: go.Figure, stations: list[str]) -> None:
    """Add a station menu that shows the traces whose meta names that station.

    The viewer's station choice selects traces by the same meta value.
    """
    if not stations:
        return
    buttons = [
        {
            "label": label(station),
            "method": "update",
            # Plotly's own code makes Pyright infer figure.data as a Figure,
            # but it is the tuple of traces.
            "args": [
                {
                    "visible": [
                        trace.meta == station  # pyright: ignore[reportAttributeAccessIssue]
                        for trace in figure.data
                    ]
                }
            ],
        }
        for station in stations
    ]
    figure.update_layout(
        updatemenus=[{"buttons": buttons, "x": 1, "y": 1.16, "xanchor": "right"}],
    )


def layout_layers(model: Model) -> list[list[str]]:
    """Group nodes into left-to-right layers for the network diagram.

    The exit always sits alone in the last layer. An acyclic graph places the
    other nodes by topological generations. Routes that cycle across customer
    types have none, so sources come first and each station sits at its fewest
    steps from a source. In an incomplete model, a node that no source reaches
    sits in the first layer, and an exit without routes still comes last.
    """
    others = nx.DiGraph(model.graph)
    others.remove_node(model.exit.name)
    if nx.is_directed_acyclic_graph(others):
        layers = [list(names) for names in nx.topological_generations(others)]
    else:
        sources = [node.name for node in model.nodes.values() if node.kind == "source"]
        steps = nx.multi_source_dijkstra_path_length(others, sources) if sources else {}
        steps = {name: steps.get(name, 0) for name in others}
        layers = [
            [name for name in others if steps[name] == step]
            # Unweighted path lengths are whole numbers of steps.
            for step in range(int(max(steps.values(), default=-1)) + 1)
        ]
    return [*layers, [model.exit.name]]


def edge_label(data: dict) -> str:
    """Name each type that may take a typed edge, or give an untyped share."""
    if "probability" in data:
        return "" if data["probability"] == 1 else f"{data['probability']:.0%}"
    return ", ".join(
        label(kind) if probability == 1 else f"{label(kind)} {probability:.0%}"
        for kind, probability in data["types"].items()
    )


def network_diagram(model: Model, problems: dict[str, str]) -> go.Figure:
    """Draw the network's nodes and routes left to right.

    Each node named in problems is drawn in the warning color with its note on
    hover, and a title explains the marks.
    """
    graph = model.graph
    positions = {}
    layers = layout_layers(model)
    for layer, names in enumerate(layers):
        for index, name in enumerate(names):
            positions[name] = (layer, (len(names) - 1) / 2 - index)
    figure = go.Figure()
    for origin, target, data in graph.edges(data=True):
        x_start, y_start = positions[origin]
        x_end, y_end = positions[target]
        x_label = (x_start + x_end) / 2
        y_label = (y_start + y_end) / 2 + 0.1
        twin = graph.has_edge(target, origin)
        if x_end > x_start and not twin:
            # A forward edge stops short of each node horizontally.
            x_start, x_end = x_start + 0.17, x_end - 0.17
        else:
            # Other edges stop short along their direction, and an edge whose
            # reverse also exists shifts to its own left, so the two stay apart.
            dx, dy = x_end - x_start, y_end - y_start
            length = math.hypot(dx, dy)
            ux, uy = dx / length, dy / length
            # A vertical pair shifts farther, past the station labels.
            shift = 0 if not twin else 0.2 if abs(dy) > abs(dx) else 0.08
            x_start, y_start = (
                x_start + 0.17 * ux - shift * uy,
                y_start + 0.17 * uy + shift * ux,
            )
            x_end, y_end = (
                x_end - 0.17 * ux - shift * uy,
                y_end - 0.17 * uy + shift * ux,
            )
            # A label sits just outside its arrow, on the same side.
            away = 0.1 if twin else 0
            x_label = (x_start + x_end) / 2 - away * uy
            y_label = (y_start + y_end) / 2 + away * ux + (0 if twin else 0.1)
        figure.add_annotation(
            x=x_end,
            y=y_end,
            ax=x_start,
            ay=y_start,
            xref="x",
            yref="y",
            axref="x",
            ayref="y",
            showarrow=True,
            arrowhead=2,
            arrowwidth=2,
            arrowcolor=GRAY,
            text="",
        )
        text = edge_label(data)
        if text:
            figure.add_annotation(
                x=x_label,
                y=y_label,
                text=text,
                showarrow=False,
                bgcolor="white",
            )

    def node_label(node) -> str:
        text = label(node.name)
        if node.kind == "station":
            suffix = "server" if node.capacity == 1 else "servers"
            text += f"<br>{node.capacity} {suffix}"
        return text

    for kind, color in [
        ("source", GREEN),
        ("station", BLUE),
        ("exit", ORANGE),
        ("problem", WARNING),
    ]:
        # A node with a problem moves from its kind's trace to the warning trace.
        if kind == "problem":
            nodes = [node for node in model.nodes.values() if node.name in problems]
        else:
            nodes = [
                node
                for node in model.nodes.values()
                if node.kind == kind and node.name not in problems
            ]
        figure.add_trace(
            go.Scatter(
                x=[positions[node.name][0] for node in nodes],
                y=[positions[node.name][1] for node in nodes],
                mode="markers+text",
                text=[node_label(node) for node in nodes],
                customdata=[label(problems.get(node.name, "")) for node in nodes],
                textposition="bottom center",
                marker={
                    "size": 30,
                    "color": color,
                    "line": {"color": "black", "width": 1},
                },
                hovertemplate=(
                    "%{text}<br>%{customdata}<extra></extra>"
                    if kind == "problem"
                    else "%{text}<extra></extra>"
                ),
                meta=kind,
                showlegend=False,
            )
        )
    if problems:
        figure.update_layout(
            title={
                "text": "Red nodes need routes before the model can run. Hover "
                "over one for the reason.",
                "font": {"size": 14},
            },
        )
    style(
        figure=figure,
        x_label="",
        y_label="",
    )
    figure.update_layout(
        height=400,
        xaxis={"visible": False, "range": [-0.45, len(layers) - 0.55]},
        yaxis={
            "visible": False,
            "range": [
                min(y for _, y in positions.values()) - 0.65,
                max(y for _, y in positions.values()) + 0.35,
            ],
        },
        margin={"l": 50, "r": 50, "t": 50, "b": 80},
    )
    return figure


def require_stations(result: Results) -> None:
    """Explain that a run without stations has no station plots."""
    if not result.settings.capacities:
        if result._supply is not None:
            raise ValueError(
                "This run has no stations. plot_inventory() and plot_orders() "
                "show its stock points."
            )
        raise ValueError(
            "This run has no stations, so it has no station plots. Its summary "
            "table holds the customer totals, and plot_customer() shows one "
            "customer's timeline."
        )


def chosen_stations(result: Results, station: str | None) -> list[str]:
    """Return the stations a station plot draws, every one unless one is named.

    A run without stations draws empty station figures, as the viewer needs,
    and the public plot methods call require_stations first.
    """
    names = list(result._capacities)
    if station is None:
        return names
    require_stations(result)
    if station not in names:
        raise unknown(
            kind="station",
            name=station,
            choices=names,
            intro=f"Station {station!r} is not in this run.",
        )
    return [station]


def chosen_stock_points(result: Results, stock_point: str | None) -> list[str]:
    """Return the stock points a plot draws, every one unless one is named."""
    names = stock_point_names(result)
    if not names:
        raise ValueError(
            "This run has no stock points. plot_queue(), plot_wait(), "
            "plot_utilization(), and plot_resources() show its stations."
        )
    if stock_point is None:
        return names
    if stock_point not in names:
        raise unknown(
            kind="stock point",
            name=stock_point,
            choices=names,
            intro=f"Stock point {stock_point!r} is not in this run.",
        )
    return [stock_point]


def plot_queue(result: Results, station: str | None = None) -> go.Figure:
    """Plot waiting customers and occupied servers over time at each station.

    Without a station, a menu chooses among the stations, and the first is
    shown. A named station is the only one drawn.
    """
    names = chosen_stations(result, station)
    figure = go.Figure()
    for index, place in enumerate(names):
        history = result.states.filter(pl.col("station") == place)
        for field, color, name in [
            ("waiting", BLUE, "Waiting"),
            ("busy", ORANGE, "Occupied servers"),
        ]:
            figure.add_trace(
                go.Scatter(
                    x=history.get_column("time").to_list(),
                    y=history.get_column(field).to_list(),
                    name=name,
                    mode="lines",
                    line={"shape": "hv", "color": color, "width": 2},
                    visible=index == 0,
                    meta=place,
                    hovertemplate=f"%{{x:.2f}} {label(result.settings.time_unit)}"
                    "<br>%{y} customers<extra>%{fullData.name}</extra>",
                )
            )
    station_menu(
        figure=figure,
        stations=names if station is None else [],
    )
    style(
        figure=figure,
        x_label=f"Simulation time ({result.settings.time_unit})",
        y_label="Customers",
    )
    figure.update_xaxes(rangeslider={"visible": True, "thickness": 0.1})
    if result.settings.drain:
        figure.add_vline(
            x=result.settings.duration,
            line_color=GRAY,
            line_dash="dash",
        )
    warmup_line(figure, result)
    return figure


def plot_wait(result: Results, station: str | None = None) -> go.Figure:
    """Plot each station's observed waits for station arrivals after warm-up."""
    names = chosen_stations(result, station)
    figure = go.Figure()
    for index, place in enumerate(names):
        waits = (
            result.visits.filter(
                (pl.col("station") == place)
                & (pl.col("arrival_time") >= result.settings.warmup)
                & pl.col("wait_time").is_not_null()
            )
            .get_column("wait_time")
            .to_list()
        )
        figure.add_trace(
            go.Histogram(
                x=waits,
                name=label(place),
                visible=index == 0,
                meta=place,
                marker={"color": BLUE, "line": {"color": "black", "width": 1}},
                hovertemplate="Wait bin: %{x}<br>Customers: %{y}<extra></extra>",
            )
        )
    station_menu(
        figure=figure,
        stations=names if station is None else [],
    )
    figure.update_layout(showlegend=False)
    return style(
        figure=figure,
        x_label=f"Waiting time ({result.settings.time_unit})",
        y_label="Customers",
    )


def plot_utilization(result: Results, station: str | None = None) -> go.Figure:
    """Plot each station's occupied share of installed capacity, or one station's."""
    names = chosen_stations(result, station)
    stations = result.stations.filter(pl.col("station").is_in(names))
    figure = go.Figure(
        go.Scatter(
            x=stations.get_column("utilization").to_list(),
            y=[label(name) for name in stations.get_column("station")],
            mode="markers",
            marker={"size": 12, "color": BLUE, "line": {"color": "black", "width": 1}},
            hovertemplate="%{y}<br>Occupied capacity: %{x:.1%}<extra></extra>",
        )
    )
    style(
        figure=figure,
        x_label="Occupied server capacity",
        y_label="Station",
    )
    figure.update_xaxes(
        range=[0, 1.05],
        tickformat=".0%",
    )
    figure.update_layout(height=max(220, 150 + 40 * len(names)))
    return figure


def plot_resources(result: Results, station: str | None = None) -> go.Figure:
    """Plot each station's processing, blocked, paused, down, and staffed servers."""
    names = chosen_stations(result, station)
    figure = go.Figure()
    fields = [
        ("processing", ORANGE, "Processing"),
        ("blocked", GREEN, "Blocked"),
        ("paused", PURPLE, "Paused"),
        ("down", "#222222", "Down"),
        ("available", GRAY, "Available"),
        ("scheduled", BLUE, "Scheduled"),
    ]
    for index, place in enumerate(names):
        history = result.states.filter(pl.col("station") == place)
        for field, color, name in fields:
            figure.add_trace(
                go.Scatter(
                    x=history.get_column("time").to_list(),
                    y=history.get_column(field).to_list(),
                    name=name,
                    mode="lines",
                    line={
                        "shape": "hv",
                        "color": color,
                        "width": 2,
                        "dash": "dash"
                        if field in {"scheduled", "available"}
                        else "solid",
                    },
                    visible=index == 0,
                    meta=place,
                )
            )
    station_menu(
        figure=figure,
        stations=names if station is None else [],
    )
    style(
        figure=figure,
        x_label=f"Simulation time ({result.settings.time_unit})",
        y_label="Servers",
    )
    figure.update_layout(
        legend={"orientation": "v", "x": 1.02, "y": 1},
        margin={"l": 85, "r": 175, "t": 60, "b": 70},
    )
    if result.settings.drain:
        figure.add_vline(
            x=result.settings.duration,
            line_color=GRAY,
            line_dash="dash",
        )
    warmup_line(figure, result)
    return figure


def timeline_spans(result: Results) -> pl.DataFrame:
    """Return every customer's timeline bars, grouped in TIMELINE_COLORS order.

    Waiting runs from station arrival to service start or abandonment, and the
    server activity rows give service, paused, and blocked time. A customer who
    waited outside a full buffer gets an "Outside" bar until admission or
    abandonment. An open end runs to the end time. Zero-length service writes no
    activity row, so it draws no bar.
    """
    waiting = result.visits.select(
        "customer_id",
        pl.lit("Waiting").alias("activity"),
        "station",
        pl.col("arrival_time").alias("start"),
        pl.coalesce("service_start", "abandon_time").alias("end"),
    )
    activities = [
        result.activities.filter(pl.col("state") == state).select(
            "customer_id",
            pl.lit(activity).alias("activity"),
            "station",
            "start",
            "end",
        )
        for activity, state in [
            ("In service", Phase.PROCESSING),
            ("Paused", Phase.PAUSED),
            ("Blocked", Phase.BLOCKED),
        ]
    ]
    outside = result.customers.filter(
        (pl.col("status") == Status.OUTSIDE)
        | (pl.col("outside_wait").is_not_null() & (pl.col("outside_wait") != 0))
        | (
            (pl.col("status") == Status.ABANDONED)
            & pl.col("admission_time").is_null()
            & (pl.col("abandon_time") > pl.col("arrival_time"))
        )
    ).select(
        "customer_id",
        pl.lit("Outside").alias("activity"),
        pl.lit("Outside").alias("station"),
        pl.col("arrival_time").alias("start"),
        pl.coalesce("admission_time", "abandon_time").alias("end"),
    )
    return pl.concat([waiting, *activities, outside]).with_columns(
        pl.col("end").fill_null(result.settings.end_time),
    )


def plot_customer(result: Results, customer_id: int) -> go.Figure:
    identifier = integer(customer_id, "Customer ID")
    if result.customers.filter(pl.col("customer_id") == identifier).is_empty():
        raise ValueError(f"Customer {identifier} does not exist in this run.")
    spans = timeline_spans(result).filter(pl.col("customer_id") == identifier)
    figure = go.Figure()
    for activity, color in TIMELINE_COLORS.items():
        bars = spans.filter(pl.col("activity") == activity)
        figure.add_trace(
            go.Bar(
                base=bars.get_column("start").to_list(),
                x=(bars.get_column("end") - bars.get_column("start")).to_list(),
                y=[label(station) for station in bars.get_column("station")],
                orientation="h",
                name=activity,
                marker={
                    "color": color,
                    "line": {"color": "black", "width": 1},
                },
                hovertemplate="%{y}<br>Duration: %{x:.2f}<extra>%{fullData.name}</extra>",
            )
        )
    style(
        figure=figure,
        x_label=f"Simulation time ({result.settings.time_unit})",
        y_label="Station",
    )
    figure.update_layout(barmode="overlay")
    figure.update_yaxes(autorange="reversed")
    return figure


def figure_data(figure: go.Figure) -> dict:
    """Return a figure as the plain JSON data the viewer pages embed."""
    text = figure.to_json()
    # Plotly returns None only for a JSON engine it does not know, and it
    # rejects one before that point.
    assert text is not None
    return json.loads(text)


def viewer_html(result: Results) -> str:
    figures = {
        "queues": figure_data(plot_queue(result)),
        "waits": figure_data(plot_wait(result)),
        "utilization": figure_data(plot_utilization(result)),
    }
    if any(
        definition["staffing"] is not None
        or definition["buffer"] is not None
        or definition["failures_enabled"]
        for definition in result._definitions.values()
    ):
        figures["resources"] = figure_data(plot_resources(result))
    payload = {
        "figures": figures,
        "customers": result.customers.to_dicts(),
        "visits": result.visits.to_dicts(),
        # Table cells for these station metrics display as percentages.
        "percent_columns": [
            name for name, metric in METRICS.items() if metric.kind == "fraction"
        ],
        # Downloads use the export column order, even for empty tables.
        "columns": {
            "customers": result.customers.columns,
            "visits": result.visits.columns,
        },
        # The viewer draws these bars as given, so it matches plot_customer.
        "timeline": timeline_spans(result).to_dicts(),
        "timeline_colors": TIMELINE_COLORS,
        "failures": result.failures.to_dicts(),
        "stations": result.stations.to_dicts(),
        "summary": result.summary.to_dicts()[0],
        "duration": result.settings.duration,
        "end_time": result.settings.end_time,
        "drain": result.settings.drain,
        "warmup": result.settings.warmup,
        "time_unit": result.settings.time_unit,
        "seed": result.settings.seed,
    }
    # Escape '<' so model labels cannot terminate the embedded JSON script.
    data = json.dumps(payload, allow_nan=False).replace("<", "\\u003c")
    template = Path(__file__).with_name("viewer.html").read_text(encoding="utf-8")
    return template.replace("__PLOTLY_JS__", get_plotlyjs()).replace(
        "__RESULT_JSON__", data
    )


# Stock-point order traces cycle through these colors, after consumer demand.
STAGE_COLORS = [BLUE, ORANGE, GREEN, PURPLE, "#E69F00", "#56B4E9"]


def stock_point_names(result: Results) -> list[str]:
    return [] if result._supply is None else result._supply["chain"][1:]


def warmup_line(figure: go.Figure, result: Results) -> None:
    if result.settings.warmup > 0:
        figure.add_vline(
            x=result.settings.warmup,
            line_color=GRAY,
            line_dash="dash",
        )


def plot_orders(result: Results) -> go.Figure:
    """Plot consumer demand and every stage's orders, which shows the bullwhip."""
    names = chosen_stock_points(result, None)
    # chosen_stock_points raises for a run without a supply chain.
    supply = result._supply
    assert supply is not None
    figure = go.Figure()
    retailer = result.inventory.filter(pl.col("stock_point") == names[0])
    figure.add_trace(
        go.Scatter(
            x=retailer.get_column("time").to_list(),
            y=retailer.get_column("demand").to_list(),
            name=label(supply["chain"][0]),
            mode="lines",
            line={"color": GRAY, "width": 2, "dash": "dot"},
        )
    )
    for index, name in enumerate(names):
        rows = result.inventory.filter(pl.col("stock_point") == name)
        figure.add_trace(
            go.Scatter(
                x=rows.get_column("time").to_list(),
                y=rows.get_column("order_quantity").to_list(),
                name=label(f"{name} orders"),
                mode="lines",
                line={"color": STAGE_COLORS[index % len(STAGE_COLORS)], "width": 2},
            )
        )
    style(
        figure=figure,
        x_label=f"Review time ({result.settings.time_unit})",
        y_label="Units per period",
    )
    warmup_line(figure, result)
    # Startup orders can dwarf the measured weeks, so the initial view scales
    # to the periods after warm-up. Autoscaling restores the full range.
    measured = result.inventory.filter(pl.col("time") >= result.settings.warmup)
    if result.settings.warmup > 0 and not measured.is_empty():
        top = measured.select(
            pl.max_horizontal(
                pl.col("order_quantity").max(),
                pl.col("demand").max(),
            )
        ).item()
        figure.update_yaxes(range=[0, 1.05 * top])
    return figure


def plot_inventory(result: Results, stock_point: str | None = None) -> go.Figure:
    """Plot a stock point's stock, backorders, and orders over review times.

    Without a stock point, a menu chooses among the stock points, and the
    first is shown. A named stock point is the only one drawn.
    """
    names = chosen_stock_points(result, stock_point)
    figure = go.Figure()
    fields = [
        ("on_hand", BLUE, "On hand", "solid"),
        ("backorders", ORANGE, "Backorders", "solid"),
        ("order_quantity", GREEN, "Orders placed", "solid"),
        ("demand", GRAY, "Orders received", "dot"),
    ]
    for index, name in enumerate(names):
        rows = result.inventory.filter(pl.col("stock_point") == name)
        for field, color, trace_name, dash in fields:
            figure.add_trace(
                go.Scatter(
                    x=rows.get_column("time").to_list(),
                    y=rows.get_column(field).to_list(),
                    name=trace_name,
                    mode="lines",
                    line={"color": color, "width": 2, "dash": dash},
                    visible=index == 0,
                    meta=name,
                )
            )
    station_menu(
        figure=figure,
        stations=names if stock_point is None else [],
    )
    style(
        figure=figure,
        x_label=f"Review time ({result.settings.time_unit})",
        y_label="Units at the end of the period",
    )
    warmup_line(figure, result)
    return figure


def supply_viewer_html(result: Results) -> str:
    figures = {
        "orders": figure_data(plot_orders(result)),
        "inventory": figure_data(plot_inventory(result)),
    }
    # A top stage that produces adds its stations, whose customers are jobs.
    if result.settings.capacities:
        queues = plot_queue(result)
        queues.update_yaxes(title_text="Jobs")
        queues.update_traces(
            hovertemplate=f"%{{x:.2f}} {label(result.settings.time_unit)}"
            "<br>%{y} jobs<extra>%{fullData.name}</extra>"
        )
        figures["queues"] = figure_data(queues)
        figures["utilization"] = figure_data(plot_utilization(result))
    # plot_orders above raises for a run without a supply chain.
    supply = result._supply
    assert supply is not None
    payload = {
        "figures": figures,
        "chain": supply["chain"],
        "period": supply["period"],
        "stock_points": result.stock_points.to_dicts(),
        "inventory": result.inventory.to_dicts(),
        "shipments": result.shipments.to_dicts(),
        "stations": result.stations.to_dicts(),
        "jobs": result.customers.to_dicts(),
        "summary": result.summary.to_dicts()[0],
        # Downloads use the export column order, even for empty tables.
        "columns": {
            "inventory": result.inventory.columns,
            "shipments": result.shipments.columns,
            "jobs": result.customers.columns,
        },
        "percent_columns": [
            name for name, metric in METRICS.items() if metric.kind == "fraction"
        ],
        "duration": result.settings.duration,
        "warmup": result.settings.warmup,
        "time_unit": result.settings.time_unit,
        "seed": result.settings.seed,
    }
    # Escape '<' so model labels cannot terminate the embedded JSON script.
    data = json.dumps(payload, allow_nan=False).replace("<", "\\u003c")
    template = Path(__file__).with_name("supply.html").read_text(encoding="utf-8")
    return template.replace("__PLOTLY_JS__", get_plotlyjs()).replace(
        "__RESULT_JSON__", data
    )
