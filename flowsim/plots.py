"""Plotly figures and an offline viewer, with no notebook dependency."""

from __future__ import annotations

import contextlib
import contextvars
import functools
import html
import json
import math
import re
from collections.abc import Callable, Iterator
from numbers import Real
from pathlib import Path
from typing import TYPE_CHECKING

import networkx as nx
import plotly.graph_objects as go
import polars as pl
from plotly.offline import get_plotlyjs

from flowsim.catalog import METRICS, unknown
from flowsim.distributions import Distribution
from flowsim.records import SUPPLIER, Phase, Status
from flowsim.validation import integer

if TYPE_CHECKING:
    import numpy as np

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


# True while a page is built. A page holds the shared template once and adds it
# back in the browser, and setting it costs about 7 ms per figure, which a
# dashboard's hundreds of figures turn into many seconds.
_BUILDING_PAGE = contextvars.ContextVar("building_page", default=False)


@contextlib.contextmanager
def building_page() -> Iterator[None]:
    """Leave the shared template out of figures styled inside the block."""
    token = _BUILDING_PAGE.set(True)
    try:
        yield
    finally:
        _BUILDING_PAGE.reset(token)


def trace_values(values: pl.Series) -> list | np.ndarray:
    """Return a record column for a trace: an array on a page, a list otherwise.

    Plotly writes an array as compact base64 data, which keeps run pages small
    and fast to write. A column with a null or NaN stays a list, so its gaps
    reach the page as they always have. Figures returned to users hold lists.
    """
    if not _BUILDING_PAGE.get() or values.null_count() > 0:
        return values.to_list()
    if values.dtype.is_float() and values.is_nan().any():
        return values.to_list()
    return values.to_numpy()


def style(figure: go.Figure, x_label: str, y_label: str) -> go.Figure:
    if not _BUILDING_PAGE.get():
        figure.update_layout(template="plotly_white")
    figure.update_layout(
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


Point = tuple[float, float]


def node_boxes(
    texts: dict[str, str],
    positions: dict[str, Point],
    scale: Point,
) -> dict[str, tuple[float, float, float, float]]:
    """Return each node's marker and label as (left, right, bottom, top) in pixels.

    A diagram node is a 30-pixel marker with its label below it in 14-point
    Georgia, about 7 pixels per character and 17 per line. Each box adds a
    4-pixel margin. scale gives the pixels per data unit along x and y.
    """
    boxes = {}
    for name, text in texts.items():
        lines = text.split("<br>")
        x = positions[name][0] * scale[0]
        y = positions[name][1] * scale[1]
        half = max(15, 3.5 * max(len(html.unescape(line)) for line in lines)) + 4
        boxes[name] = (x - half, x + half, y - 19 - 17 * len(lines), y + 19)
    return boxes


def curve_point(tail: Point, control: Point, tip: Point, share: float) -> Point:
    """Return the point a share of the way along a quadratic curve."""
    rest = 1 - share
    return (
        rest * rest * tail[0] + 2 * rest * share * control[0] + share * share * tip[0],
        rest * rest * tail[1] + 2 * rest * share * control[1] + share * share * tip[1],
    )


Box = tuple[float, float, float, float]


def crossings(points: list[Point], boxes: list[Box], scale: Point) -> int:
    """Count the boxes (in pixels) that a path through data points enters."""
    pixels = [(x * scale[0], y * scale[1]) for x, y in points]
    return sum(
        any(left < x < right and bottom < y < top for x, y in pixels)
        for left, right, bottom, top in boxes
    )


def arrow_path(
    straight: tuple[Point, Point],
    unshifted: tuple[Point, Point],
    centers: tuple[Point, Point],
    gaps: Callable[[Point, Point], Point],
    boxes: list[Box],
    scale: Point,
    bounds: Box,
) -> tuple[Point, Point, Point | None]:
    """Choose an arrow's tail, tip, and control point (None for a straight arrow).

    The straight arrow wins if it misses every other node's box (see
    node_boxes). Otherwise the arrow without its twin shift wins if it misses
    them, since the twin shifts the other way. Otherwise, like the builder
    page's arrows, it curves 60 to 220 pixels to either side at its middle,
    leaving one node's center and reaching the other's toward the control
    point. gaps maps the pixel directions out of the first node and into the
    second to the pixel distances where the arrow starts and stops. The first
    curve that misses every box wins, or the one that crosses the fewest. A
    curve must stay 10 pixels inside bounds, i.e., the (left, right, bottom,
    top) axis ranges, so that it and its label show, and the straight arrow
    stays when no curve does.
    """
    for tail, tip in (straight, unshifted):
        # A control point halfway along keeps the curve on the straight line.
        halfway = ((tail[0] + tip[0]) / 2, (tail[1] + tip[1]) / 2)
        line = [curve_point(tail, halfway, tip, step / 40) for step in range(41)]
        if not crossings(line, boxes, scale):
            return tail, tip, None

    def unit(start: Point, end: Point) -> Point:
        dx = (end[0] - start[0]) * scale[0]
        dy = (end[1] - start[1]) * scale[1]
        length = math.hypot(dx, dy)
        return dx / length, dy / length

    def inside(point: Point) -> bool:
        left, right, bottom, top = bounds
        x_margin, y_margin = 10 / scale[0], 10 / scale[1]
        return (
            left + x_margin <= point[0] <= right - x_margin
            and bottom + y_margin <= point[1] <= top - y_margin
        )

    middle = (
        (centers[0][0] + centers[1][0]) / 2,
        (centers[0][1] + centers[1][1]) / 2,
    )
    normal = unit(centers[0], centers[1])
    normal = (-normal[1], normal[0])
    best = None
    for offset in [60, -60, 100, -100, 150, -150, 220, -220]:
        # A control point twice the offset away puts the curve's middle at it.
        control = (
            middle[0] + 2 * offset * normal[0] / scale[0],
            middle[1] + 2 * offset * normal[1] / scale[1],
        )
        out = unit(centers[0], control)
        into = unit(control, centers[1])
        leave, reach = gaps(out, into)
        tail = (
            centers[0][0] + leave * out[0] / scale[0],
            centers[0][1] + leave * out[1] / scale[1],
        )
        tip = (
            centers[1][0] - reach * into[0] / scale[0],
            centers[1][1] - reach * into[1] / scale[1],
        )
        points = [curve_point(tail, control, tip, step / 40) for step in range(41)]
        if not all(inside(point) for point in points):
            continue
        hits = crossings(points, boxes, scale)
        if best is None or hits < best[0]:
            best = (hits, tail, tip, control)
        if not hits:
            break
    if best is None:
        return (*straight, None)
    return best[1], best[2], best[3]


def draw_arrow(
    figure: go.Figure,
    tail: Point,
    tip: Point,
    control: Point | None,
) -> None:
    """Draw a straight arrow, or a curved one through a control point."""
    start = tail
    if control is not None:
        figure.add_shape(
            type="path",
            path=(
                f"M {tail[0]},{tail[1]} Q {control[0]},{control[1]} {tip[0]},{tip[1]}"
            ),
            xref="x",
            yref="y",
            line={"color": GRAY, "width": 2},
            layer="below",
        )
        # The arrowhead points along the curve's last stretch.
        start = curve_point(tail, control, tip, 0.9)
    figure.add_annotation(
        x=tip[0],
        y=tip[1],
        ax=start[0],
        ay=start[1],
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


def node_text(node) -> str:
    """Label a diagram node with its name, and a station with its servers."""
    text = label(node.name)
    if node.kind == "station":
        suffix = "server" if node.capacity == 1 else "servers"
        text += f"<br>{node.capacity} {suffix}"
    return text


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
    rows = [y for _, y in positions.values()]
    bounds = (-0.45, len(layers) - 0.55, min(rows) - 0.65, max(rows) + 0.35)
    # The figure is 800 by 400 pixels with 50 at each side, 50 above, and 80
    # below.
    scale = (700 / (bounds[1] - bounds[0]), 270 / (bounds[3] - bounds[2]))
    boxes = node_boxes(
        texts={node.name: node_text(node) for node in model.nodes.values()},
        positions=positions,
        scale=scale,
    )
    figure = go.Figure()
    for origin, target, data in graph.edges(data=True):
        x_start, y_start = positions[origin]
        x_end, y_end = positions[target]
        dx, dy = x_end - x_start, y_end - y_start
        length = math.hypot(dx, dy)
        ux, uy = dx / length, dy / length
        twin = graph.has_edge(target, origin)
        # Other edges stop short along their direction, and an edge whose
        # reverse also exists shifts to its own left, so the two stay apart. A
        # vertical pair shifts farther, past the station labels.
        shift = 0 if not twin else 0.2 if abs(dy) > abs(dx) else 0.08
        unshifted = (
            (x_start + 0.17 * ux, y_start + 0.17 * uy),
            (x_end - 0.17 * ux, y_end - 0.17 * uy),
        )
        if x_end > x_start and not twin:
            # A forward edge stops short of each node horizontally.
            straight = ((x_start + 0.17, y_start), (x_end - 0.17, y_end))
            x_label = (x_start + x_end) / 2
            y_label = (y_start + y_end) / 2 + 0.1
        else:
            straight = (
                (unshifted[0][0] - shift * uy, unshifted[0][1] + shift * ux),
                (unshifted[1][0] - shift * uy, unshifted[1][1] + shift * ux),
            )
            # A label sits just outside its arrow, on the same side.
            away = 0.1 if twin else 0
            x_label = (straight[0][0] + straight[1][0]) / 2 - away * uy
            y_label = (
                (straight[0][1] + straight[1][1]) / 2 + away * ux + (0 if twin else 0.1)
            )

        def gaps(out: Point, into: Point) -> Point:
            """Return a curve's pixel gaps, past a label it leaves or reaches."""
            # Each box's bottom is its label's, below the node's center.
            below = {
                name: positions[name][1] * scale[1] - boxes[name][2]
                for name in (origin, target)
            }
            return (
                below[origin] if out[1] < -0.5 else 0.17 * scale[0],
                below[target] if into[1] > 0.5 else 0.17 * scale[0],
            )

        # An arrow that would cross another node, e.g., one that skips a
        # layer, curves around it, 0.17 of a layer from each node's center.
        tail, tip, control = arrow_path(
            straight=straight,
            unshifted=unshifted,
            centers=(positions[origin], positions[target]),
            gaps=gaps,
            boxes=[box for name, box in boxes.items() if name not in (origin, target)],
            scale=scale,
            bounds=bounds,
        )
        draw_arrow(
            figure=figure,
            tail=tail,
            tip=tip,
            control=control,
        )
        if tail == unshifted[0] and straight != unshifted:
            x_label = (tail[0] + tip[0]) / 2
            y_label = (tail[1] + tip[1]) / 2 + 0.1
        if control is not None:
            # The label sits on the curve's middle.
            x_label, y_label = curve_point(tail, control, tip, 0.5)
        text = edge_label(data)
        if text:
            figure.add_annotation(
                x=x_label,
                y=y_label,
                text=text,
                showarrow=False,
                bgcolor="white",
            )

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
                text=[node_text(node) for node in nodes],
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
        xaxis={"visible": False, "range": [bounds[0], bounds[1]]},
        yaxis={"visible": False, "range": [bounds[2], bounds[3]]},
        margin={"l": 50, "r": 50, "t": 50, "b": 80},
    )
    return figure


def chain_positions(model: Model) -> dict[str, tuple[float, float]]:
    """Place a supply chain's stages in one row, with goods moving left to right.

    The outside supplier sits at x = 0 unless the top stage produces. The stock
    points follow from the top of the chain down to the stage nearest
    consumers, and demand comes last, all at y = 0. A producing stage's
    stations sit in the rows below and to the right of it: a station k steps
    along the production route from the stage is k columns to its right, and
    stations at the same step stack downward from y = -1, so the arrows of a
    branch leave the stage at different slopes. A station on no production
    route follows the line in the row y = -1.
    """
    supply = model.supply_chain
    assert supply is not None
    top = supply.stock_points[-1]
    produces = top.lead_time is None
    order = [] if produces else [SUPPLIER]
    order += [node.name for node in reversed(supply.stock_points)]
    order.append(supply.demand.name)
    positions = {name: (float(x), 0.0) for x, name in enumerate(order)}
    if produces:
        line = nx.DiGraph(model.graph)
        line.remove_node(model.exit.name)
        # A stock point enters the graph only with its first route, and an
        # unfinished model may not have one yet.
        line.add_node(top.name)
        # The return to the producing stage closes a loop, so it is left out.
        line.remove_edges_from(list(line.in_edges(top.name)))
        steps = nx.single_source_shortest_path_length(line, top.name)
        column = positions[top.name][0]
        stacked: dict[int, int] = {}
        for name, step in steps.items():
            if name == top.name:
                continue
            row = stacked.get(step, 0)
            stacked[step] = row + 1
            positions[name] = (column + step, -1.0 - row)
    # A station on no production route is drawn after the line, not hidden.
    unrouted = [
        node.name
        for node in model.nodes.values()
        if node.kind == "station" and node.name not in positions
    ]
    start = max((x for x, y in positions.values() if y < 0), default=-1.0) + 1
    for index, name in enumerate(unrouted):
        positions[name] = (start + index, -1.0)
    return positions


def lead_time_label(lead_time: object, time_unit: str) -> str:
    """Show a lead time as a number with its unit, a distribution, or 'random'."""
    if isinstance(lead_time, Distribution):
        return repr(lead_time)
    if callable(lead_time):
        return "random"
    # Stock points accept any real scalar, including NumPy numbers.
    assert isinstance(lead_time, Real)
    return f"{float(lead_time):g} {time_unit}"


def chain_diagram(model: Model) -> go.Figure:
    """Draw a supply chain's stages left to right with lead times on the arrows.

    Each arrow into a stock point carries that stock point's lead time. A
    producing stage's stations sit below it with their production route.
    """
    supply = model.supply_chain
    assert supply is not None
    positions = chain_positions(model)
    names = list(positions)
    # The chain row was placed first, in left-to-right order.
    row = [name for name in names if positions[name][1] == 0]
    shipments = list(zip(row, row[1:]))
    stages = {node.name: node for node in supply.stock_points}
    # Each production edge keeps its branch share, which labels its arrow.
    shares = {
        (origin, target): edge_label(data)
        for origin, target, data in model.graph.edges(data=True)
        if model.exit.name not in (origin, target)
    }
    production = list(shares)

    def label_gap(name: str) -> float:
        """Return the distance below a node that clears its label."""
        # A station's label has a second line for its servers.
        node = model.nodes.get(name)
        return 0.5 if node is not None and node.kind == "station" else 0.35

    texts = {
        name: node_text(model.nodes[name]) if name in model.nodes else label(name)
        for name in names
    }
    lowest = min(y for _, y in positions.values())
    # A short chain keeps the spacing of a five-column one, so arrows and their
    # offsets keep their size instead of stretching across the width.
    right = max(x for x, _ in positions.values())
    span = max(right + 0.9, 5)
    middle = right / 2
    bounds = (middle - span / 2, middle + span / 2, lowest - 0.65, 0.45)
    # The figure is 800 pixels wide, with 50 at each side, and 300 tall plus
    # 100 per row of stations, with 130 in its margins.
    scale = (700 / span, (170 + 100 * int(-lowest)) / (1.1 - lowest))
    boxes = node_boxes(
        texts=texts,
        positions=positions,
        scale=scale,
    )
    figure = go.Figure()
    for origin, target in [*shipments, *production]:
        x_start, y_start = positions[origin]
        x_end, y_end = positions[target]
        dx, dy = x_end - x_start, y_end - y_start
        length = math.hypot(dx, dy)
        ux, uy = dx / length, dy / length
        # An arrow whose reverse also exists shifts to its own left, so a
        # one-station production route draws two separate arrows.
        twin = (target, origin) in production
        shift = 0 if not twin else 0.2 if abs(dy) > abs(dx) else 0.08
        # Labels sit below the nodes, so an arrow that leaves a node downward
        # or reaches one from below stops farther away, past the label.
        leave = label_gap(origin) if uy < -0.5 else 0.17
        reach = label_gap(target) if uy > 0.5 else 0.17
        unshifted = (
            (x_start + leave * ux, y_start + leave * uy),
            (x_end - reach * ux, y_end - reach * uy),
        )
        straight = (
            (unshifted[0][0] - shift * uy, unshifted[0][1] + shift * ux),
            (unshifted[1][0] - shift * uy, unshifted[1][1] + shift * ux),
        )

        def gaps(out: Point, into: Point) -> Point:
            """Return a curve's pixel gaps, past a label it leaves or reaches."""
            return (
                (label_gap(origin) * scale[1] if out[1] < -0.5 else 0.17 * scale[0]),
                (label_gap(target) * scale[1] if into[1] > 0.5 else 0.17 * scale[0]),
            )

        # An arrow that would cross another station, e.g., a branch arrow
        # passing the station above it, curves around it.
        tail, tip, control = arrow_path(
            straight=straight,
            unshifted=unshifted,
            centers=(positions[origin], positions[target]),
            gaps=gaps,
            boxes=[box for name, box in boxes.items() if name not in (origin, target)],
            scale=scale,
            bounds=bounds,
        )
        draw_arrow(
            figure=figure,
            tail=tail,
            tip=tip,
            control=control,
        )
        if shares.get((origin, target)):
            # A branch share sits on its own arrow, 40% of the way from the
            # branching node, so it cannot be read as the share of a return
            # route or of a neighboring arrow in the fan.
            # A control point at the middle of a straight arrow keeps the
            # curve on it.
            halfway = ((tail[0] + tip[0]) / 2, (tail[1] + tip[1]) / 2)
            x_label, y_label = curve_point(
                tail,
                halfway if control is None else control,
                tip,
                0.4,
            )
            figure.add_annotation(
                x=x_label,
                y=y_label,
                text=shares[(origin, target)],
                showarrow=False,
                bgcolor="white",
            )
        if (origin, target) in shipments and target in stages:
            figure.add_annotation(
                x=(x_start + x_end) / 2,
                y=0.12,
                text=label(lead_time_label(stages[target].lead_time, model.time_unit)),
                showarrow=False,
                bgcolor="white",
            )
    kinds = [
        ("supplier", GREEN, [SUPPLIER] if SUPPLIER in positions else []),
        ("stock_point", BLUE, list(stages)),
        ("demand", ORANGE, [supply.demand.name]),
        ("station", PURPLE, [name for name in names if positions[name][1] < 0]),
    ]
    for kind, color, members in kinds:
        text = [texts[name] for name in members]
        figure.add_trace(
            go.Scatter(
                x=[positions[name][0] for name in members],
                y=[positions[name][1] for name in members],
                mode="markers+text",
                text=text,
                textposition="bottom center",
                marker={
                    "size": 30,
                    "color": color,
                    "line": {"color": "black", "width": 1},
                },
                hovertemplate="%{text}<extra></extra>",
                meta=kind,
                showlegend=False,
            )
        )
    title = "Goods move left to right."
    if any(target in stages for _, target in shipments):
        title += " Each arrow into a stock point shows its lead time."
    if any(y < 0 for _, y in positions.values()):
        title += " The stations below the top stage make its goods."
    figure.update_layout(
        title={
            "text": title,
            "font": {"size": 14},
        },
    )
    style(
        figure=figure,
        x_label="",
        y_label="",
    )
    figure.update_layout(
        height=300 + 100 * int(-lowest),
        xaxis={
            "visible": False,
            "range": [bounds[0], bounds[1]],
        },
        yaxis={"visible": False, "range": [bounds[2], bounds[3]]},
        margin={"l": 50, "r": 50, "t": 50, "b": 80},
    )
    return figure


def require_stations(result: Results) -> None:
    """Explain that a run without stations has no station plots."""
    if not result.settings.capacities:
        if result.supply is not None:
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
    # Only a comparison's shared settings hold no capacities.
    capacities = result.settings.capacities
    assert capacities is not None
    names = list(capacities)
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
    names = result.stock_point_names
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
                    x=trace_values(history.get_column("time")),
                    y=trace_values(history.get_column(field)),
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
        waits = trace_values(
            result.visits.filter(
                (pl.col("station") == place)
                & (pl.col("arrival_time") >= result.settings.warmup)
                & pl.col("wait_time").is_not_null()
            ).get_column("wait_time")
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
            x=trace_values(stations.get_column("utilization")),
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


# Server-state lines in legend order, with their colors and dashes.
RESOURCE_LINES = [
    ("processing", ORANGE, "Processing", "solid"),
    ("blocked", GREEN, "Blocked", "solid"),
    ("paused", PURPLE, "Paused", "solid"),
    ("down", "#222222", "Down", "solid"),
    ("available", GRAY, "Available", "dash"),
    ("scheduled", BLUE, "Scheduled", "dash"),
]
# Stacked server states from the bottom up. Each server counts in one layer.
RESOURCE_LAYERS = [
    ("processing", ORANGE, "Processing"),
    ("blocked", GREEN, "Blocked"),
    ("paused", PURPLE, "Paused"),
    ("down", "#222222", "Down"),
    ("idle", "#BFC9D1", "Idle"),
]


def server_layers(result: Results, station: str) -> pl.DataFrame:
    """Count one station's servers in each stacked layer at every states time.

    The states table counts each condition on its own, so a down server that
    holds a paused job is both paused and down there, and the table cannot
    say which down servers hold a job. This function rebuilds each server's
    condition after every event at each states time from the activities
    table (its job and phase), the failures table (its repairs), and the
    states table's scheduled count (server k is on duty while that count is
    at least k, since shifts staff the lowest-numbered servers). A server
    holding a job counts in its phase, a down server without a job counts as
    down, and an on-duty server that is up and has no job is idle. An
    off-duty server with no job and no repair is not counted. Thus, the
    layers sum to the scheduled servers plus any off-duty server that still
    holds a job or is under repair.
    """
    capacities = result.settings.capacities
    assert capacities is not None
    capacity = capacities[station]
    # The recorded count, not the staffing schedule, since a run that stops at
    # closing does not execute a shift change scheduled exactly then.
    times = result.states.filter(pl.col("station") == station).select(
        "time",
        "scheduled",
    )
    # Zero-length intervals hold no state after the events at their time.
    jobs = result.activities.filter(
        (pl.col("station") == station)
        & (pl.col("end").is_null() | (pl.col("end") > pl.col("start")))
    )
    repairs = result.failures.filter(
        (pl.col("station") == station)
        & (
            pl.col("repair_end").is_null()
            | (pl.col("repair_end") > pl.col("failure_time"))
        )
    )
    servers = []
    for server in range(1, capacity + 1):
        # A server's intervals never overlap, so the latest one that starts at
        # or before a time is the only one that can cover it.
        servers.append(
            times.join_asof(
                jobs.filter(pl.col("server_id") == server)
                .select("start", "end", "state")
                .sort("start"),
                left_on="time",
                right_on="start",
                strategy="backward",
            )
            .join_asof(
                repairs.filter(pl.col("server_id") == server)
                .select("failure_time", "repair_end")
                .sort("failure_time"),
                left_on="time",
                right_on="failure_time",
                strategy="backward",
            )
            .select(
                "time",
                pl.when(pl.col("end").is_null() | (pl.col("time") < pl.col("end")))
                .then(pl.col("state"))
                .alias("phase"),
                (
                    pl.col("failure_time").is_not_null()
                    & (
                        pl.col("repair_end").is_null()
                        | (pl.col("time") < pl.col("repair_end"))
                    )
                ).alias("down"),
                (pl.col("scheduled") >= server).alias("on_duty"),
            )
        )
    free = pl.col("phase").is_null()
    return (
        pl.concat(servers)
        .group_by("time", maintain_order=True)
        .agg(
            *[
                (pl.col("phase") == phase).sum().cast(pl.Int64).alias(phase)
                for phase in [Phase.PROCESSING, Phase.BLOCKED, Phase.PAUSED]
            ],
            (free & pl.col("down")).sum().cast(pl.Int64).alias("down"),
            (free & ~pl.col("down") & pl.col("on_duty"))
            .sum()
            .cast(pl.Int64)
            .alias("idle"),
            pl.col("on_duty").sum().cast(pl.Int64).alias("scheduled"),
        )
        .sort("time")
    )


def plot_resources(
    result: Results,
    station: str | None = None,
    stacked: bool = False,
) -> go.Figure:
    """Plot each station's server states over time, as lines or stacked.

    The lines are the states table's processing, blocked, paused, down,
    available, and scheduled counts, which overlap (e.g., a down server
    holding a paused job counts as both paused and down). The stacked view
    counts each server in one layer from server_layers and draws the
    scheduled count as a dashed line over the stack.
    """
    names = chosen_stations(result, station)
    figure = go.Figure()
    hover = "%{x:.2f} " + label(result.settings.time_unit)
    for index, place in enumerate(names):
        history = result.states.filter(pl.col("station") == place)
        times = trace_values(history.get_column("time"))
        if stacked:
            layers = server_layers(result, place)
            for field, color, name in RESOURCE_LAYERS:
                figure.add_trace(
                    go.Scatter(
                        x=times,
                        y=trace_values(layers.get_column(field)),
                        name=name,
                        mode="lines",
                        # Each station stacks its own layers.
                        stackgroup=f"station {index}",
                        line={"shape": "hv", "color": color, "width": 0.5},
                        fillcolor=color,
                        visible=index == 0,
                        meta=place,
                        hovertemplate=hover
                        + "<br>%{y} servers<extra>%{fullData.name}</extra>",
                    )
                )
        lines = (
            [line for line in RESOURCE_LINES if line[0] == "scheduled"]
            if stacked
            else RESOURCE_LINES
        )
        for field, color, name, dash in lines:
            figure.add_trace(
                go.Scatter(
                    x=times,
                    y=trace_values(history.get_column(field)),
                    name=name,
                    mode="lines",
                    line={"shape": "hv", "color": color, "width": 2, "dash": dash},
                    visible=index == 0,
                    meta=place,
                    hovertemplate=hover
                    + "<br>%{y} servers<extra>%{fullData.name}</extra>",
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


def service_payload(result: Results) -> dict:
    """Return the data the service-network run view draws."""
    figures = {
        "queues": page_figure(plot_queue(result)),
        "waits": page_figure(plot_wait(result)),
        "utilization": page_figure(plot_utilization(result)),
    }
    if result._resources_vary:
        figures["resources"] = page_figure(plot_resources(result))
        # The page's switch swaps this figure into the resources chart.
        stacked = page_figure(
            plot_resources(
                result,
                stacked=True,
            )
        )
    else:
        stacked = None
    return {
        "kind": "service",
        "figures": figures,
        "stacked_resources": stacked,
        # Record tables go column by column, which is about half the size of
        # rows, and the run view rebuilds the rows it needs.
        "customers": result.customers.to_dict(as_series=False),
        "visits": result.visits.to_dict(as_series=False),
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
        "timeline": timeline_spans(result).to_dict(as_series=False),
        "timeline_colors": TIMELINE_COLORS,
        "failures": result.failures.to_dict(as_series=False),
        "stations": result.stations.to_dict(as_series=False),
        "summary": result.summary.to_dicts()[0],
        "duration": result.settings.duration,
        "end_time": result.settings.end_time,
        "drain": result.settings.drain,
        "warmup": result.settings.warmup,
        "time_unit": result.settings.time_unit,
        "seed": result.settings.seed,
    }


# Stock-point order traces cycle through these colors, after consumer demand.
STAGE_COLORS = [BLUE, ORANGE, GREEN, PURPLE, "#E69F00", "#56B4E9"]


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
    supply = result.supply
    assert supply is not None
    figure = go.Figure()
    retailer = result.inventory.filter(pl.col("stock_point") == names[0])
    figure.add_trace(
        go.Scatter(
            x=trace_values(retailer.get_column("time")),
            y=trace_values(retailer.get_column("demand")),
            name=label(supply.chain[0]),
            mode="lines",
            line={"color": GRAY, "width": 2, "dash": "dot"},
        )
    )
    for index, name in enumerate(names):
        rows = result.inventory.filter(pl.col("stock_point") == name)
        figure.add_trace(
            go.Scatter(
                x=trace_values(rows.get_column("time")),
                y=trace_values(rows.get_column("order_quantity")),
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
                    x=trace_values(rows.get_column("time")),
                    y=trace_values(rows.get_column(field)),
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


def supply_payload(result: Results) -> dict:
    """Return the data the supply-chain run view draws."""
    figures = {
        "orders": page_figure(plot_orders(result)),
        "inventory": page_figure(plot_inventory(result)),
    }
    # A top stage that produces adds its stations, whose customers are jobs.
    if result.settings.capacities:
        queues = plot_queue(result)
        queues.update_yaxes(title_text="Jobs")
        queues.update_traces(
            hovertemplate=f"%{{x:.2f}} {label(result.settings.time_unit)}"
            "<br>%{y} jobs<extra>%{fullData.name}</extra>"
        )
        figures["queues"] = page_figure(queues)
        figures["utilization"] = page_figure(plot_utilization(result))
    # plot_orders above raises for a run without a supply chain.
    supply = result.supply
    assert supply is not None
    return {
        "kind": "supply",
        "figures": figures,
        "chain": list(supply.chain),
        "period": supply.period,
        # Record tables go column by column, as in service_payload.
        "stock_points": result.stock_points.to_dict(as_series=False),
        "inventory": result.inventory.to_dict(as_series=False),
        "shipments": result.shipments.to_dict(as_series=False),
        "stations": result.stations.to_dict(as_series=False),
        "jobs": result.customers.to_dict(as_series=False),
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


def run_payload(result: Results) -> dict:
    """Return one run's data for a run view, the service or supply-chain one."""
    return (
        supply_payload(result) if result.supply is not None else service_payload(result)
    )


@functools.cache
def page_template() -> dict:
    """Return the Plotly template every FlowSim figure uses, as page JSON."""
    return figure_data(go.Figure(layout={"template": "plotly_white"}))["layout"][
        "template"
    ]


def page_figure(figure: go.Figure) -> dict:
    """Return a figure's JSON without its template.

    Every page figure is styled with the shared template, which the page holds
    once and each figure adds back when drawn, so this saves about 8 kB per
    figure. Plotly writes its default template for a figure styled while a
    page is built, and that copy is dropped too.
    """
    data = figure_data(figure)
    data["layout"].pop("template", None)
    return data


def page_json(payload: object) -> str:
    """Return JSON that is safe inside a page's script element.

    Escaping '<' keeps model labels from ending the script element.
    """
    return json.dumps(payload, allow_nan=False).replace("<", "\\u003c")


def fill_template(name: str, values: dict[str, str]) -> str:
    """Fill a page template's __NAME__ placeholders in one pass.

    One pass means a placeholder-like name inside a value (e.g., in a
    scenario name or in Plotly's code) is never replaced.
    """
    template = Path(__file__).with_name(name).read_text(encoding="utf-8")
    return re.sub(
        pattern=r"__([A-Z_]+)__",
        repl=lambda match: values[match.group(1)],
        string=template,
    )


def page_parts() -> dict[str, str]:
    """Return the style, Plotly, template, and run views that every page holds."""
    folder = Path(__file__).parent
    return {
        "STYLE": (folder / "page.css").read_text(encoding="utf-8"),
        "PLOTLY_JS": get_plotlyjs(),
        "TEMPLATE_JSON": page_json(page_template()),
        "SERVICE_RUN": (folder / "service_run.html").read_text(encoding="utf-8"),
        "SUPPLY_RUN": (folder / "supply_run.html").read_text(encoding="utf-8"),
    }


def run_page_html(result: Results) -> str:
    """Return the offline page of one run."""
    with building_page():
        payload = run_payload(result)
    heading = (
        "FlowSim supply chain" if payload["kind"] == "supply" else "FlowSim results"
    )
    return fill_template(
        "run.html",
        {
            **page_parts(),
            "HEADING": heading,
            "RESULT_JSON": page_json(payload),
        },
    )
