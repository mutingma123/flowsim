"""Time three representative FlowSim workloads for the code-health baseline.

Each case runs in a fresh Python process so its peak memory is its own. The
timed span excludes imports and model construction. Cases:

- run: one 192,000-minute run of the two-server service network (about
  64,000 customers).
- compare: the service-day comparison, i.e., three staffing levels times
  20 replications of an eight-hour day, with drain.
- dashboard: build that comparison's dashboard page. Peak memory includes
  the comparison it is built from.

`pixi run bench` runs every case three times and prints the median, the
range, and peak resident memory. `--case NAME` runs one case once in this
process and prints one JSON line.
"""

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output" / "bench"
CASES = ("run", "compare", "dashboard")


def _peak_mb() -> float | None:
    """Return this process's peak resident memory in MB, or None on Windows."""
    try:
        import resource
    except ImportError:
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports kilobytes and macOS reports bytes.
    return peak / 1024**2 if sys.platform == "darwin" else peak / 1024


def _run_case(case: str) -> dict:
    sys.path.insert(0, str(ROOT))
    from examples.models import service_network
    from examples.service_day import DAY_LENGTH, DAYS, STAFFING
    from flowsim import compare

    if case == "run":
        model = service_network(service_capacity=2)
        start = time.perf_counter()
        results = model.run(duration=192_000, seed=7)
        results.summary
        seconds = time.perf_counter() - start
    else:
        scenarios = {
            name: service_network(service_capacity=servers)
            for servers, name in STAFFING.items()
        }
        start = time.perf_counter()
        comparison = compare(
            scenarios=scenarios,
            duration=DAY_LENGTH,
            replications=DAYS,
            seed=42,
            drain=True,
        )
        comparison.intervals()
        seconds = time.perf_counter() - start
        if case == "dashboard":
            OUTPUT.mkdir(parents=True, exist_ok=True)
            page = OUTPUT / "comparison.html"
            start = time.perf_counter()
            comparison.viewer(page)
            seconds = time.perf_counter() - start
    return {"case": case, "seconds": seconds, "peak_mb": _peak_mb()}


def _measure(case: str, repeat: int) -> dict:
    samples = []
    for _ in range(repeat):
        completed = subprocess.run(
            [sys.executable, __file__, "--case", case],
            check=True,
            capture_output=True,
            text=True,
        )
        samples.append(json.loads(completed.stdout.strip().splitlines()[-1]))
    seconds = [sample["seconds"] for sample in samples]
    peaks = [sample["peak_mb"] for sample in samples if sample["peak_mb"] is not None]
    return {
        "case": case,
        "seconds": seconds,
        "seconds_median": statistics.median(seconds),
        "peak_mb": peaks,
        "peak_mb_median": statistics.median(peaks) if peaks else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Time FlowSim benchmark cases.")
    parser.add_argument("--case", choices=CASES)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--json-out", type=Path)
    arguments = parser.parse_args()
    if arguments.case:
        print(json.dumps(_run_case(arguments.case)))
        return
    report = [_measure(case, arguments.repeat) for case in CASES]
    for row in report:
        low, high = min(row["seconds"]), max(row["seconds"])
        peak = row["peak_mb_median"]
        peak_text = "n/a" if peak is None else f"{peak:.0f} MB"
        print(
            f"{row['case']:<10} median {row['seconds_median']:.3f} s "
            f"(range {low:.3f} to {high:.3f}), peak {peak_text}",
        )
    if arguments.json_out:
        arguments.json_out.parent.mkdir(parents=True, exist_ok=True)
        arguments.json_out.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
