"""Reprs, attribute hints, and error messages that teach."""

import copy
import pickle

import pytest

import flowsim
import flowsim.plots
from flowsim import Model, compare, exponential
from flowsim.results import metric_units
from tests.models import (
    beer_chain,
    branching_service,
    job_shop,
    service_network,
)


@pytest.fixture(autouse=True)
def no_viewer(monkeypatch):
    """A display must never build a viewer page."""

    def refuse(*args, **kwargs):
        raise AssertionError("A display built a viewer.")

    # Every run page and dashboard reads run_payload or page_parts.
    monkeypatch.setattr(flowsim.plots, "run_payload", refuse)
    monkeypatch.setattr(flowsim.plots, "page_parts", refuse)


def objects():
    """Return (object, facts that its displays must hold)."""
    chain = beer_chain()
    network = service_network()
    scenarios = compare(
        {"Base": network, "Wider": service_network(3)},
        duration=30,
        replications=3,
    )
    return [
        (network, ["Customers -> Check-in -> Service -> Exit", "model.run("]),
        (
            branching_service(),
            ["Triage -> Routine (70%), Specialist (30%)", "Routine -> Exit"],
        ),
        (job_shop(), ["[A] A orders -> Mill -> Lathe -> Exit", "[B] B orders"]),
        (chain, ["Consumers -> Retailer -> Wholesaler", "period 1"]),
        (network.run(30), ["Seed", "42", "Check-in", "results.report()", "spawns"]),
        (chain.run(10), ["Retailer", "fill_rate", "results.plot_inventory()"]),
        (
            network.experiment(30, replications=3),
            ["3 replications", "Service", "experiment.intervals("],
        ),
        (scenarios, ["Base (baseline)", "Wider", "comparison.differences("]),
        (network.nodes["Service"], ["Service", "capacity", "2"]),
        (exponential(mean=3), ["Exponential(mean=3)"]),
    ]


def test_every_display_has_its_facts_and_stays_short():
    for item, facts in objects():
        text = repr(item)
        markup = item._repr_html_()
        assert len(text.splitlines()) <= 20
        for fact in facts:
            assert fact.replace("->", "-&gt;") in markup or fact in markup, fact
            if not isinstance(item, flowsim.Distribution):
                assert fact in text, fact
        assert "<" in markup


def test_html_escapes_text():
    model = Model()
    model.source(
        name="<b>A</b>",
        interarrival=1,
    )
    assert "<b>A</b>" not in model._repr_html_()
    assert "&lt;b&gt;" in model._repr_html_()


def test_model_reports_a_problem_without_raising():
    model = Model()
    model.source(
        name="Customers",
        interarrival=1,
    )
    text = repr(model)
    assert "Validate: fails:" in text
    assert "\n" not in text.split("Validate: ")[1].split("\n")[0]
    assert "Validate: passes" in repr(service_network())


def test_station_repr_omits_unset_fields():
    text = repr(service_network().nodes["Check-in"])
    assert "patience" not in text
    assert "buffer" not in text
    assert "service_time: <function>" in text
    assert "capacity: 1" in text
    named = Model().station(
        name="S",
        capacity=1,
        service_time=exponential(mean=4),
    )
    assert "service_time: Exponential(mean=4)" in repr(named)


def test_results_hints():
    results = service_network().run(20)
    for name in ["intervals", "differences", "plot"]:
        with pytest.raises(AttributeError, match="model.experiment"):
            getattr(results, name)
    for old, new in [
        ("queue_plot", "plot_queue"),
        ("wait_plot", "plot_wait"),
        ("utilization_plot", "plot_utilization"),
        ("resource_plot", "plot_resources"),
        ("customer_plot", "plot_customer"),
        ("inventory_plot", "plot_inventory"),
        ("orders_plot", "plot_orders"),
    ]:
        with pytest.raises(AttributeError, match=new):
            getattr(results, old)
    for name in [
        "duration",
        "warmup",
        "drain",
        "seed",
        "time_unit",
        "end_time",
        "capacities",
    ]:
        with pytest.raises(AttributeError, match=f"results.settings.{name}"):
            getattr(results, name)
    with pytest.raises(AttributeError, match="Close matches: summary"):
        results.sumary


def test_underscore_names_get_a_plain_error():
    results = service_network().run(20)
    assert getattr(results, "__deepcopy__", None) is None
    with pytest.raises(AttributeError) as error:
        results._private
    assert "Close matches" not in str(error.value)
    assert "moved" not in str(error.value)
    # Results holds read-only mappings, so it could never be copied or pickled.
    with pytest.raises(TypeError, match="mappingproxy"):
        copy.deepcopy(results)
    with pytest.raises(TypeError, match="mappingproxy"):
        pickle.dumps(results)
    assert copy.copy(results).summary.equals(results.summary)


def test_experiment_and_comparison_hints():
    model = service_network()
    experiment = model.experiment(20, replications=3)
    comparison = compare(
        {"A": model, "B": service_network(3)},
        duration=20,
        replications=3,
    )
    for owner, label in [(experiment, "experiment"), (comparison, "comparison")]:
        for name in ["duration", "warmup", "drain", "time_unit"]:
            with pytest.raises(AttributeError, match=f"{label}.settings.{name}"):
                getattr(owner, name)
        with pytest.raises(AttributeError, match="Close matches: summary"):
            owner.sumary
        assert getattr(owner, "__deepcopy__", None) is None
    with pytest.raises(AttributeError, match="flowsim.compare"):
        experiment.differences


def test_string_route_message():
    model = Model()
    model.source(
        name="A",
        interarrival=1,
    )
    with pytest.raises(ValueError, match="not names. You passed the string 'A'"):
        model.route(["A", model.exit])
    with pytest.raises(ValueError, match="You passed the string 'A'"):
        model.branch("A", {model.exit: 1})


def test_other_model_message():
    other = Model()
    foreign = other.station(
        name="Elsewhere",
        capacity=1,
        service_time=1,
    )
    model = Model()
    with pytest.raises(ValueError, match="created by a different Model"):
        model.route([foreign, model.exit])


def test_schedule_entry_message():
    model = Model()
    with pytest.raises(
        ValueError,
        match=r"Arrival rate schedule entry 0 must be a \(start time, rate\) pair, "
        r"e\.g\. rates=\[\(0, 10\), \(120, 20\)\], not 0\.",
    ):
        model.source(
            name="A",
            rates=(0, 1),
        )
    with pytest.raises(ValueError, match="entry 1 must be"):
        model.source(
            name="B",
            rates=[(0, 1), (5, 1, 2)],
        )


def test_rates_read_per_singular_unit():
    assert metric_units("throughput", "minutes") == "customers per minute"
    assert metric_units("throughput", "weeks") == "customers per week"
    assert metric_units("throughput", "s") == "customers per s"
    assert metric_units("throughput", "min") == "customers per min"
    # Abbreviations and other labels are not plural words, so they stay as given.
    assert metric_units("throughput", "ms") == "customers per ms"
    assert metric_units("throughput", "µs") == "customers per µs"
    assert metric_units("throughput", "ticks") == "customers per ticks"
    assert metric_units("mean_wait", "minutes") == "minutes"


def test_a_very_large_model_display_skips_validation(monkeypatch):
    model = Model()
    arrivals = model.source(
        name="Customers",
        interarrival=1,
    )
    stations = [
        model.station(
            name=f"Step {index}",
            capacity=1,
            service_time=0.5,
        )
        for index in range(201)
    ]
    model.route([arrivals, *stations, model.exit])

    def fail():
        raise AssertionError("display ran validate()")

    monkeypatch.setattr(model, "validate", fail)
    assert "not checked" in repr(model)
