"""Check the README: its Python blocks run, and its reference tables match the catalog."""

import re
from pathlib import Path

import plotly.graph_objects as go
import pytest

from flowsim import metrics
from flowsim.catalog import COLUMNS, METRICS

README = Path(__file__).parents[1] / "README.md"

# Display labels for the catalog's scopes, used only in the README table.
SCOPE_LABELS = {
    "system": "System",
    "station": "Station",
    "stock_point": "Stock point",
}

# Where each catalog table appears, shown as the summary line of its column
# table. A table added to the catalog needs an entry here, or rendering fails.
TABLE_TITLES = {
    "customers": "results.customers, one row per customer",
    "visits": "results.visits, one row per station visit",
    "states": "results.states, one row per station and recorded time",
    "activities": "results.activities, one row per processing, paused, or blocked interval",
    "failures": "results.failures, one row per server failure",
    "inventory": "results.inventory, one row per stock point and review period",
    "shipments": "results.shipments, one row per shipment",
    "summary": "results.summary, one row per run",
    "stations": "results.stations, one row per station",
    "stock_points": "results.stock_points, one row per stock point",
    "intervals": "intervals() and differences(), one row per scenario and location",
    "pooled": "columns that experiments and comparisons add to stacked tables",
    "fits": "fits.table, one row per fitted family",
}


def cell(text: str) -> str:
    """Escape a catalog string for one Markdown table cell."""
    return text.replace("|", "\\|")


def metric_table() -> str:
    """Render the replication metrics in catalog order as a Markdown table."""
    lines = [
        "| Metric | Scope | Units | Window | Meaning |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in metrics().iter_rows(named=True):
        lines.append(
            f"| `{row['name']}` | {SCOPE_LABELS[row['scope']]} | {cell(row['units'])} "
            f"| {cell(row['window'])} | {cell(row['meaning'])} |"
        )
    return "\n".join(lines)


def column_tables() -> str:
    """Render each table's columns that are not replication metrics.

    The metric columns of summary, stations, and stock_points are in the metric
    table, so a table whose columns are all metrics renders nothing here.
    """
    tables: dict[str, list[tuple[str, str, str]]] = {}
    for (table, column), entry in COLUMNS.items():
        metric = METRICS.get(column)
        if metric is not None and metric.table == table:
            continue
        tables.setdefault(table, []).append((column, entry.units, entry.meaning))
    sections = []
    for table, rows in tables.items():
        sections += [
            "<details>",
            f"<summary><code>{table}</code>: {TABLE_TITLES[table]}</summary>",
            "",
            "| Column | Units | Meaning |",
            "| --- | --- | --- |",
            *(
                f"| `{column}` | {cell(units)} | {cell(meaning)} |"
                for column, units, meaning in rows
            ),
            "",
            "</details>",
            "",
        ]
    return "\n".join(sections).rstrip("\n")


def generated(name: str) -> str:
    """Return the README text between a pair of generated-table markers."""
    text = README.read_text()
    start = f"<!-- {name} start -->\n"
    end = f"\n<!-- {name} end -->"
    assert text.count(start) == 1 and text.count(end) == 1, (
        f"The README needs exactly one {start.strip()} and one {end.strip()} marker."
    )
    return text.split(start)[1].split(end)[0]


@pytest.mark.parametrize(
    argnames=("name", "render"),
    argvalues=[
        ("metrics table", metric_table),
        ("column tables", column_tables),
    ],
)
def test_readme_tables_match_catalog(name, render):
    expected = render()
    assert generated(name) == expected, (
        f"The README's {name} differs from the catalog in flowsim/catalog.py. "
        f"Replace the text between its markers with:\n\n{expected}\n"
    )


def python_blocks() -> list[tuple[str, str]]:
    """Return each Python block with the nearest heading above it.

    Fenced blocks of every language are skipped when looking for headings, so a
    shell comment such as "# macOS" is never read as a heading.
    """
    blocks = []
    heading = None
    lines = README.read_text().splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("```"):
            end = lines.index("```", index + 1)
            if line.strip() == "```python":
                blocks.append((heading, "\n".join(lines[index + 1 : end]) + "\n"))
            index = end + 1
            continue
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
        index += 1
    return blocks


def test_readme_python_blocks_run_on_their_own(tmp_path, monkeypatch):
    blocks = python_blocks()
    assert len(blocks) >= 14
    # Blocks write under output/ and show figures, so isolate both.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        target=go.Figure,
        name="show",
        value=lambda self, *args, **kwargs: None,
    )
    for index, (heading, block) in enumerate(blocks, start=1):
        label = f"README block {index} (under {heading!r})"
        # The package ships only flowsim, so a block that imports the
        # repository's examples fails for a reader outside the repository.
        imported = re.findall(
            pattern=r"^\s*(?:from|import)\s+(\w+)",
            string=block,
            flags=re.MULTILINE,
        )
        assert "examples" not in imported, (
            f"{label} imports from examples/, which is not installed with FlowSim."
        )
        # A fresh namespace per block, so each block runs when copied alone.
        namespace: dict = {"__name__": "readme_block"}
        try:
            exec(
                compile(
                    source=block,
                    filename=label,
                    mode="exec",
                ),
                namespace,
            )
        except Exception as error:
            raise AssertionError(f"{label} failed: {error!r}") from error


def github_anchor(heading: str) -> str:
    """Return the anchor GitHub gives a heading: lowercase, punctuation dropped,
    spaces as hyphens."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def test_readme_contents_links_resolve():
    text = README.read_text()
    outside_code = re.sub(
        pattern=r"```.*?```",
        repl="",
        string=text,
        flags=re.DOTALL,
    )
    anchors = {
        github_anchor(line.lstrip("#"))
        for line in outside_code.splitlines()
        if line.startswith("#")
    }
    links = re.findall(r"\]\(#([^)]+)\)", outside_code)
    assert links, "The README has no contents links."
    missing = sorted(set(links) - anchors)
    assert not missing, f"README links point to no heading: {missing}"
