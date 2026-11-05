"""Model diagrams of service networks and supply chains."""

import math
import re

import numpy as np
import pytest

from flowsim import Model, exponential, moving_average, order_up_to
from flowsim.plots import chain_positions, layout_layers
from tests.models import (
    beer_chain,
    deterministic_queue,
    one_stage_chain,
    producing_factory,
)


def marked(figure) -> dict[str, str]:
    """Map each node label in the diagram's warning trace to its hover note."""
    (trace,) = [trace for trace in figure.data if trace.meta == "problem"]
    return dict(zip(trace.text, trace.customdata))


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


def test_diagram_curves_an_arrow_that_skips_a_layer():
    model = Model()
    walk_ins = model.source(
        name="Walk-ins",
        interarrival=1,
    )
    register, exam = (
        model.station(
            name=name,
            capacity=1,
            service_time=1,
        )
        for name in ["Register", "Exam"]
    )
    model.branch(walk_ins, {register: 0.5, exam: 0.5})
    model.route([register, exam, model.exit])
    figure = model.diagram()
    # Four layers on one row: x runs 700 / 3.9 = 179.49 pixels per layer, and
    # y runs 270 pixels per unit. The straight arrow from Walk-ins to Exam
    # crosses Register, so it bends 60 pixels up at its middle, i.e., its
    # control point sits 120 pixels above Register: (1, 120 / 270 = 0.4444).
    (shape,) = figure.layout.shapes
    numbers = [float(value) for value in re.findall(r"-?[\d.]+", shape.path)]
    # The curve leaves Walk-ins toward the control point, whose direction in
    # pixels is (179.49, 120) / 215.91 = (0.8313, 0.5558), 0.17 of a layer
    # (30.51 pixels) from its center: x = 30.51 * 0.8313 / 179.49 = 0.1413 and
    # y = 30.51 * 0.5558 / 270 = 0.0628. It reaches Exam symmetrically.
    assert [round(value, 4) for value in numbers] == [
        0.1413,
        0.0628,
        1.0,
        0.4444,
        1.8587,
        0.0628,
    ]
    # The curve's arrowhead ends at its tip, and the other arrows stay straight.
    assert arrows(figure)[1][2:] == (1.86, 0.06)
    # The curve's share sits on its middle: x = (0.1413 + 2 + 1.8587) / 4 = 1
    # and y = (0.0628 + 2 * 0.4444 + 0.0628) / 4 = 0.2536.
    labels = {
        (item.text, round(item.x, 4), round(item.y, 4))
        for item in figure.layout.annotations
        if not item.showarrow
    }
    assert ("50%", 1.0, 0.2536) in labels


def test_diagram_keeps_a_curve_inside_the_plot():
    # Two parallel lines, with a branch from S1 that skips A1 to reach B1. A
    # curve upward would leave the plot, whose top is 0.35 above S1's row.
    model = Model()
    s1, s2 = (
        model.source(
            name=name,
            interarrival=1,
        )
        for name in ["S1", "S2"]
    )
    a1, b1, a2, b2 = (
        model.station(
            name=name,
            capacity=1,
            service_time=1,
        )
        for name in ["A1", "B1", "A2", "B2"]
    )
    model.branch(s1, {a1: 0.5, b1: 0.5})
    model.route([a1, b1, model.exit])
    model.route([s2, a2, b2, model.exit])
    figure = model.diagram()
    (shape,) = figure.layout.shapes
    x0, y0, cx, cy, x1, y1 = (
        float(value) for value in re.findall(r"-?[\d.]+", shape.path)
    )
    bottom, top = figure.layout.yaxis.range
    for step in range(41):
        share = step / 40
        y = (1 - share) ** 2 * y0 + 2 * (1 - share) * share * cy + share**2 * y1
        assert bottom < y < top
    # The curve bends down, toward S2's row, and its share sits on it.
    assert cy < 0.5
    assert [item.text for item in figure.layout.annotations if item.text] == [
        "50%",
        "50%",
    ]


def test_chain_diagram_drops_a_twin_shift_that_would_cross_a_station():
    model, consumers, factory = producing_factory()
    fast, slow = (
        model.station(
            name=name,
            capacity=1,
            service_time=0.01,
        )
        for name in ("Fast", "Slow")
    )
    model.branch(factory, {fast: 0.1, slow: 0.9})
    model.route([fast, factory])
    model.route([slow, factory])
    model.supply(
        [consumers, factory],
        period=1,
    )
    figure = model.diagram()
    assert not figure.layout.shapes
    # Shifted 0.2 to its left, the arrow from the factory at (0, 0) to Slow at
    # (1, -2) would cross Fast's label, so it keeps its unshifted line: unit
    # vector (0.4472, -0.8944), 0.35 from the factory past its label and 0.17
    # from Slow, i.e., (0.16, -0.31) to (1 - 0.08, -2 + 0.15).
    assert (0.16, -0.31, 0.92, -1.85) in arrows(figure)


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


def test_chain_diagram_labels_production_branch_shares():
    model, consumers, factory = producing_factory()
    fast, slow = (
        model.station(
            name=name,
            capacity=1,
            service_time=0.01,
        )
        for name in ("Fast", "Slow")
    )
    model.branch(factory, {fast: 0.1, slow: 0.9})
    model.route([fast, factory])
    model.route([slow, factory])
    model.supply(
        [consumers, factory],
        period=1,
    )
    figure = model.diagram()
    labels = {
        item.text: (item.x, item.y)
        for item in figure.layout.annotations
        if not item.showarrow and item.text.endswith("%")
    }
    # Fast sits at (1, -1) and Slow at (1, -2) below the factory at (0, 0), so
    # each share sits between the factory and its station.
    assert set(labels) == {"10%", "90%"}
    assert 0 < labels["10%"][0] < 1 and -1 < labels["10%"][1] < 0
    assert 0 < labels["90%"][0] < 1 and -2 < labels["90%"][1] < 0
    # Routes taken by every job carry no share.
    plain = one_stage_chain(produce=True).diagram()
    assert not [
        item.text
        for item in plain.layout.annotations
        if not item.showarrow and item.text.endswith("%")
    ]


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
