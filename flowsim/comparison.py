"""Scenario comparisons with matched replication seeds and paired intervals."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import plotly.graph_objects as go
import polars as pl

from flowsim.model import Model
from flowsim.reporting import (
    comparison_differences,
    comparison_intervals,
    export_tables,
    interval_figure,
    page,
    request_metadata,
    window_text,
)
from flowsim.results import (
    Experiment,
    Settings,
    _run_settings,
    unknown,
)
from flowsim.viewer import Viewer


class Comparison:
    def __init__(self, experiments: dict[str, Experiment]):
        if len(experiments) < 2:
            raise ValueError("A comparison needs at least two experiments.")
        self.experiments = experiments
        self.baseline = next(iter(experiments))
        first = experiments[self.baseline].runs[0]
        if any(
            _run_settings(experiment.runs[0]) != _run_settings(first)
            for experiment in experiments.values()
        ):
            raise ValueError(
                "Compared scenarios need the same duration, warm-up, drain rule, "
                "and time unit."
            )

    @property
    def settings(self) -> Settings:
        """Return the settings every scenario shares.

        The seed and end time differ by run, and capacities differ by scenario,
        so they are None here. Each run's own settings hold them.
        """
        return replace(
            self.experiments[self.baseline].settings,
            capacities=None,
        )

    # The combined tables are built from the experiments on each access, so
    # estimates and exports always read the same replication values.
    @property
    def summary(self) -> pl.DataFrame:
        return pl.concat(
            [
                experiment.summary.select(pl.lit(name).alias("scenario"), pl.all())
                for name, experiment in self.experiments.items()
            ]
        )

    @property
    def stations(self) -> pl.DataFrame:
        return pl.concat(
            [
                experiment.stations.select(pl.lit(name).alias("scenario"), pl.all())
                for name, experiment in self.experiments.items()
            ]
        )

    @property
    def stock_points(self) -> pl.DataFrame:
        return pl.concat(
            [
                experiment.stock_points.select(pl.lit(name).alias("scenario"), pl.all())
                for name, experiment in self.experiments.items()
            ]
        )

    def _reference(self, baseline: str | None) -> str:
        reference = self.baseline if baseline is None else baseline
        if reference not in self.experiments:
            raise unknown(
                kind="baseline scenario",
                name=reference,
                choices=list(self.experiments),
                intro=f"Unknown baseline scenario {reference!r}.",
            )
        return reference

    def intervals(
        self,
        metric: str = "mean_total_wait",
        *,
        station: str | None = None,
        stock_point: str | None = None,
        confidence: float = 0.95,
    ) -> pl.DataFrame:
        """Estimate a metric in each scenario with Student t intervals.

        The rows follow Experiment.intervals within each scenario, so a station
        metric without station= gives one row per station per scenario.
        """
        return comparison_intervals(
            experiments=self.experiments,
            metric=metric,
            station=station,
            stock_point=stock_point,
            confidence=confidence,
        )

    def differences(
        self,
        metric: str = "mean_total_wait",
        *,
        baseline: str | None = None,
        station: str | None = None,
        stock_point: str | None = None,
        confidence: float = 0.95,
    ) -> pl.DataFrame:
        """Estimate each scenario minus the baseline within matched replications.

        A station or stock-point metric without a location gives one row per
        location that the scenario shares with the baseline.
        """
        return comparison_differences(
            experiments=self.experiments,
            reference=self._reference(baseline),
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
        differences: bool = False,
        baseline: str | None = None,
    ) -> go.Figure:
        """Plot each scenario's interval, or its paired difference from the baseline."""
        table = (
            self.differences(
                metric=metric,
                baseline=baseline,
                station=station,
                stock_point=stock_point,
                confidence=confidence,
            )
            if differences
            else self.intervals(
                metric=metric,
                station=station,
                stock_point=stock_point,
                confidence=confidence,
            )
        )
        return interval_figure(
            table=table,
            metric=metric,
            time_unit=self.settings.time_unit,
            differences=differences,
        )

    def viewer(
        self,
        path: str | Path | None = None,
        *,
        metric: str = "mean_total_wait",
        station: str | None = None,
        stock_point: str | None = None,
        confidence: float = 0.95,
        baseline: str | None = None,
    ) -> Viewer:
        """Build an offline page with intervals and paired differences.

        The page is saved when a path is given.
        """
        reference = self._reference(baseline)
        request = {
            "metric": metric,
            "station": station,
            "stock_point": stock_point,
            "confidence": confidence,
        }
        settings = self.settings
        document = page(
            heading="Scenario comparison",
            text=window_text(
                metric,
                duration=settings.duration,
                warmup=settings.warmup,
                drain=settings.drain,
                time_unit=settings.time_unit,
            ),
            metric=metric,
            table=self.intervals(**request),
            time_unit=settings.time_unit,
            confidence=confidence,
            means=self.plot(**request),
            changes=self.plot(
                **request,
                differences=True,
                baseline=reference,
            ),
            reference=reference,
        )
        viewer = Viewer(
            document=document,
            kind="comparison page",
            height=1100,
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
        baseline: str | None = None,
    ) -> Path:
        """Write pooled run tables, intervals, differences, and metadata."""
        reference = self._reference(baseline)
        request = {
            "metric": metric,
            "station": station,
            "stock_point": stock_point,
            "confidence": confidence,
        }
        supply = any(
            experiment.stock_point_names for experiment in self.experiments.values()
        )
        return export_tables(
            directory,
            summary=self.summary,
            stations=self.stations,
            stock_points=self.stock_points if supply else None,
            intervals=self.intervals(**request),
            differences=self.differences(
                **request,
                baseline=reference,
            ),
            metadata={
                "baseline": reference,
                **request_metadata(
                    experiment=self.experiments[reference],
                    **request,
                ),
                "difference": "Scenario minus baseline within matched replication",
            },
        )


def compare(
    scenarios: Mapping[str, Model],
    duration: float,
    *,
    replications: int = 20,
    seed: int = 42,
    warmup: float = 0,
    drain: bool = False,
) -> Comparison:
    """Run named scenarios using the same independent replication seeds."""
    if not isinstance(scenarios, Mapping) or len(scenarios) < 2:
        raise ValueError("A comparison needs at least two named models.")
    for name, model in scenarios.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Each scenario needs a nonempty name.")
        if not isinstance(model, Model):
            raise ValueError(f"Scenario {name!r} must contain a Model.")
        model.validate()
    if len({model.time_unit for model in scenarios.values()}) != 1:
        raise ValueError("Compared scenarios must declare the same time unit.")
    return Comparison(
        {
            name: model.experiment(
                duration=duration,
                replications=replications,
                seed=seed,
                warmup=warmup,
                drain=drain,
            )
            for name, model in scenarios.items()
        }
    )
