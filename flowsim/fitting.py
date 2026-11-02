"""Fit common distribution families to data and turn a fit into a duration sampler.

This module imports only `flowsim.validation` from FlowSim, so a notebook can fit
data without building a model.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Sequence

import numpy as np
import polars as pl
import scipy.stats as st

from flowsim.validation import Sampler

# Eight families that an operations course can explain: symmetric data (normal,
# uniform), a minimum, mode, and maximum estimated without data (triangular),
# interarrival times (exponential), right-skewed durations (lognormal, gamma,
# Weibull), and bounded data (beta). The short list keeps the search to about
# a tenth of a second and its winner explainable, where SciPy's 100-plus
# families rank obscure ones first by margins in the third decimal place.
FAMILIES = (
    "norm",
    "lognorm",
    "uniform",
    "triang",
    "expon",
    "gamma",
    "weibull_min",
    "beta",
)

_SCHEMA = {
    "family": pl.String,
    "ks": pl.Float64,
    "params": pl.List(pl.Float64),
    "lower": pl.Float64,
    "upper": pl.Float64,
}


def best_fit(data, families: Sequence[str] = FAMILIES) -> pl.DataFrame:
    """Rank families by the one-sample Kolmogorov-Smirnov statistic of each fit.

    Each family is fitted by maximum likelihood with SciPy's `fit`, and the KS
    statistic is the largest vertical gap between the data's empirical CDF and the
    fitted CDF. The statistic uses no random draws, so the ranking is the same on
    every run. A family whose fit raises an error or yields no finite statistic is
    left out of the table. `lower` and `upper` are the fitted distribution's
    support, so an infinite `upper` means draws have no ceiling and a finite one
    (e.g., beta, triangular, uniform) means no draw can exceed it.
    """
    values = _data(data)
    rows = []
    for name in _names(families):
        family = getattr(st, name)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                params = family.fit(values)
                fitted = family(*params)
                ks = float(st.kstest(values, fitted.cdf).statistic)
                lower, upper = fitted.support()
        # SciPy's optimizers raise several error types on a bad start, and a
        # failed fit means only that this family is not ranked.
        except Exception:
            continue
        if not math.isfinite(ks):
            continue
        rows.append(
            {
                "family": name,
                "ks": ks,
                "params": [float(p) for p in params],
                "lower": float(lower),
                "upper": float(upper),
            }
        )
    if not rows:
        raise ValueError("No family produced a valid fit to the data.")
    return (
        pl.DataFrame(rows, schema=_SCHEMA)
        .sort("ks", maintain_order=True)
        .with_row_index("rank", offset=1)
    )


def sampler(family: str, params: Sequence[float]) -> Sampler:
    """Return a duration sampler that draws from a fitted family.

    `family` and `params` are one row of `best_fit`, and the sampler draws with the
    generator FlowSim passes it, so a run's seed fixes every draw. Draws are not
    clipped. A family with negative support (e.g., a normal near zero) can
    produce a negative duration, which FlowSim rejects with an error during the
    run.
    """
    (name,) = _names([family])
    values = [float(p) for p in params]
    fitted = getattr(st, name)(*values)
    lower, upper = fitted.support()
    if (
        not all(math.isfinite(p) for p in values)
        or math.isnan(lower)
        or math.isnan(upper)
    ):
        raise ValueError(f"The parameters {list(params)!r} are not valid for {name}.")

    def draw(rng: np.random.Generator) -> float:
        return float(fitted.rvs(random_state=rng))

    return draw


def _data(data) -> np.ndarray:
    values = np.asarray(data, dtype=float)
    if values.ndim != 1 or values.size < 2:
        raise ValueError(
            "Fitting data must be a one-dimensional sequence of at least two values."
        )
    if not np.isfinite(values).all():
        raise ValueError("Fitting data must contain only finite numbers.")
    return values


def _names(families: Sequence[str]) -> list[str]:
    if isinstance(families, str):
        raise ValueError(
            "families must be a sequence of SciPy family names, not one string."
        )
    names = list(families)
    if not names:
        raise ValueError("families must name at least one distribution.")
    unknown = [
        n
        for n in names
        if not isinstance(n, str)
        or not isinstance(getattr(st, n, None), st.rv_continuous)
    ]
    if unknown:
        raise ValueError(
            f"Each family must name a continuous distribution in scipy.stats, not {unknown!r}."
        )
    return names
