"""Distribution fitting checked against hand-calculated fits and KS statistics."""

import numpy as np
import polars as pl
import pytest
import scipy.stats as st

from flowsim import FAMILIES, Model, best_fit, sampler


def test_uniform_fit_and_ks_match_a_hand_calculation():
    # The uniform MLE spans the sample, so loc = 2 and scale = 10 - 2 = 8. The CDF at
    # 2, 3, 5, 10 is 0, 1/8, 3/8, 1 against empirical steps of 1/4, 1/2, 3/4, 1, so
    # the largest gap is 1/2 - 1/8 = 3/4 - 3/8 = 3/8.
    fits = best_fit(
        data=[2.0, 3.0, 5.0, 10.0],
        families=["uniform"],
    )
    row = fits.row(0, named=True)
    assert row["rank"] == 1
    assert row["family"] == "uniform"
    assert row["params"] == pytest.approx([2, 8])
    assert row["ks"] == pytest.approx(0.375)
    assert (row["lower"], row["upper"]) == pytest.approx((2, 10))


def test_ranking_is_sorted_by_the_ks_statistic_of_each_fit():
    data = np.random.default_rng(3).gamma(
        shape=2,
        scale=3,
        size=200,
    )
    fits = best_fit(data)
    assert fits.columns == [
        "rank",
        "family",
        "ks",
        "params",
        "lower",
        "upper",
        "loc_fixed",
    ]
    assert set(fits["family"]) <= set(FAMILIES)
    assert fits["rank"].to_list() == list(range(1, fits.height + 1))
    assert fits["ks"].is_sorted()
    for row in fits.iter_rows(named=True):
        fitted = getattr(st, row["family"])(*row["params"])
        assert row["ks"] == pytest.approx(st.kstest(data, fitted.cdf).statistic)


def test_the_ranking_is_the_same_on_every_call():
    data = np.random.default_rng(4).lognormal(size=150)
    assert best_fit(data).equals(best_fit(pl.Series(data)))


def test_a_family_whose_fit_fails_is_left_out(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("bad start")

    monkeypatch.setattr(st.expon, "fit", fail)
    fits = best_fit(
        data=[1.0, 2.0, 4.0, 7.0],
        families=["expon", "uniform"],
    )
    assert fits["family"].to_list() == ["uniform"]
    with pytest.raises(ValueError, match="No family"):
        best_fit(
            data=[1.0, 2.0, 4.0, 7.0],
            families=["expon"],
        )


@pytest.mark.parametrize(
    "data",
    [[1.0], [1.0, float("nan")], [[1.0, 2.0], [3.0, 4.0]]],
)
def test_fitting_data_is_validated(data):
    with pytest.raises(ValueError, match="Fitting data"):
        best_fit(data)


@pytest.mark.parametrize(
    "families", ["norm", [], ["norm", "poisson"], ["not_a_family"]]
)
def test_family_names_are_validated(families):
    with pytest.raises(ValueError, match="famil"):
        best_fit(
            data=[1.0, 2.0, 3.0],
            families=families,
        )


def test_sampler_rejects_invalid_parameters():
    with pytest.raises(ValueError, match="not valid for norm"):
        sampler(
            family="norm",
            params=[0, -1],
        )
    with pytest.raises(ValueError, match="continuous distribution"):
        sampler(
            family="binom",
            params=[3, 0.5],
        )


def test_sampler_drives_a_station_with_draws_from_the_fitted_range():
    # Customers arrive every 10 minutes and a uniform(1, 3) service ends before the
    # next arrival, so no one waits and every service time lies in [1, 3].
    def run(seed):
        model = Model()
        source = model.source(
            name="Jobs",
            interarrival=10,
            first_arrival=0,
            limit=20,
        )
        station = model.station(
            name="Machine",
            capacity=1,
            service_time=sampler(
                family="uniform",
                params=[1, 2],
            ),
        )
        model.route([source, station, model.exit])
        return model.run(
            duration=300,
            seed=seed,
        ).visits

    visits = run(seed=8)
    assert visits.height == 20
    assert visits["wait_time"].to_list() == [0.0] * 20
    assert visits["service_time"].is_between(1, 3).all()
    assert visits["service_time"].n_unique() == 20
    assert visits.equals(run(seed=8))
    assert not visits.equals(run(seed=9))


def test_a_negative_draw_stops_the_run():
    model = Model()
    source = model.source(
        name="Jobs",
        interarrival=10,
        first_arrival=0,
        limit=1,
    )
    station = model.station(
        name="Machine",
        capacity=1,
        service_time=sampler(
            family="norm",
            params=[-5, 0.001],
        ),
    )
    model.route([source, station, model.exit])
    with pytest.raises(ValueError, match="at least zero"):
        model.run(
            duration=30,
            seed=1,
        )


def test_a_fit_that_starts_below_zero_is_refitted_at_zero():
    # On right-skewed positive data, the free lognormal fit shifts its start below
    # zero. The default refits it with loc held at zero, i.e., SciPy's floc=0.
    data = np.random.default_rng(1).gamma(
        shape=2.78,
        scale=1.62,
        size=300,
    )
    free = best_fit(
        data=data,
        families=["lognorm"],
        nonnegative=False,
    ).row(0, named=True)
    assert free["lower"] < 0
    assert free["loc_fixed"] is False
    fixed = best_fit(
        data=data,
        families=["lognorm"],
    ).row(0, named=True)
    assert fixed["loc_fixed"] is True
    assert fixed["lower"] == 0
    assert fixed["params"] == pytest.approx(list(st.lognorm.fit(data, floc=0)))
    refitted = st.lognorm(*fixed["params"])
    assert fixed["ks"] == pytest.approx(st.kstest(data, refitted.cdf).statistic)


def test_nonnegative_fits_never_start_below_zero():
    data = np.random.default_rng(1).gamma(
        shape=2.78,
        scale=1.62,
        size=300,
    )
    fits = best_fit(data)
    assert (fits["lower"] >= 0).all()
    # The normal reaches below zero wherever its mean is, so it is left out.
    assert "norm" not in fits["family"].to_list()
    assert "norm" in best_fit(data, nonnegative=False)["family"].to_list()
    # A fit that already starts at or above zero is not refitted.
    uniform = best_fit(
        data=[2.0, 3.0, 5.0, 10.0],
        families=["uniform"],
    ).row(0, named=True)
    assert uniform["loc_fixed"] is False


def test_negative_data_need_nonnegative_false():
    data = [-2.0, -1.0, 0.5, 3.0]
    with pytest.raises(ValueError, match="nonnegative=False"):
        best_fit(data)
    fits = best_fit(
        data=data,
        families=["uniform"],
        nonnegative=False,
    )
    assert fits.row(0, named=True)["lower"] == pytest.approx(-2)
