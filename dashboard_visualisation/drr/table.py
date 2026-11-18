"""The compound table for a DRR dataset, from the paper's Table S8 (FREYA-3011).

The room asked for one row per compound carrying its summary scores. For the
A549-ACE2 validation screen the only per-compound scores are in Table S8 of Asp
et al. (iScience 29, 116673, CC BY 4.0): a morphology score, an infection rate
and a cell count, each measured at about four doses. A compound row needs one
value, so each compound shows **the dose with its highest morphology score**,
and the infection rate and cell count measured at that same dose: a row's
numbers always describe one measured condition, and the cell count keeps a low
infection rate at a toxic dose from reading as protection. A tie takes the lower
dose. The reasoning, and what would change it, is recorded in the DRR packet
``version-one-scope`` §11.

Rows are the published table's treated compounds, read from ``pert_type`` rather
than from the shape of the id: a prefixless id can be a treatment and a
CBCS-shaped id can hold only controls. Compounds outside Table S8 keep their row
and show "not reported" — never a zero — because the validation screen only
carried the primary screen's hits forward.

The workbook itself is never copied into media; precompute writes the derived
``table.parquet`` and the page reads that. One selection function serves both the
page and its CSV export, so the two can never disagree about which rows a filter
selects.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import polars as pl
from django.utils.html import strip_tags

# Table S8's own headers, mapped to ours. Its legend columns are ignored.
S8_COLUMNS: dict[str, str] = {
    "Compound_name": "compound_name",
    "Concentration (uM)": "dose_um",
    "morphology_score": "morphology_score",
    "Cell count (%)": "cell_count_pct",
    "Infection rate (%)": "infection_rate_pct",
}
_NUMERIC_COLUMNS = ["dose_um", "morphology_score", "cell_count_pct", "infection_rate_pct"]

# Table S8's legend prints the hit threshold as ">0.5 morphology score": exclusive.
HIT_THRESHOLD = 0.5

NOT_REPORTED = "not reported"

TABLE_COLUMNS: list[str] = [
    "cbkid",
    "name",
    "broad_moa",
    "broad_target",
    "morphology_score",
    "infection_rate_pct",
    "cell_count_pct",
    "dose_um",
]
_TEXT_COLUMNS = TABLE_COLUMNS[:4]
_SCORE_COLUMNS = TABLE_COLUMNS[4:]

TABLE_HEADERS: list[str] = [
    "Compound id",
    "Name",
    "Mechanism (broad MoA)",
    "Target",
    "Morphology score",
    "Infection rate (%)",
    "Cell count (%)",
    "Dose (µM)",
]

# Sort keys a reader may choose; a leading "-" sorts descending.
SORT_OPTIONS: list[tuple[str, str]] = [
    ("-morphology_score", "Morphology score, highest first"),
    ("morphology_score", "Morphology score, lowest first"),
    ("infection_rate_pct", "Infection rate, lowest first"),
    ("-infection_rate_pct", "Infection rate, highest first"),
    ("-cell_count_pct", "Cell count, highest first"),
    ("cell_count_pct", "Cell count, lowest first"),
]
DEFAULT_SORT = "-morphology_score"

# Range filters: query parameter -> (column, lower bound?).
RANGE_FILTERS: dict[str, tuple[str, bool]] = {
    "morph_min": ("morphology_score", True),
    "morph_max": ("morphology_score", False),
    "inf_min": ("infection_rate_pct", True),
    "inf_max": ("infection_rate_pct", False),
}


def load_table_s8(path: Path) -> pl.DataFrame:
    """Load Table S8's measured columns, with every value numeric.

    The sheet stores doses as text (``'0.008'``, ``'1'``), so each numeric column
    is cast here, and a value that is not a number — or a blank — stops the run
    rather than becoming a silent null.

    Args:
        path: Path to the supplementary workbook ``…-mmc9.xlsx``.

    Returns:
        One row per sheet row, with ``compound_name`` and four float columns.

    Raises:
        ValueError: If a required column is missing or holds a non-numeric value.
    """
    # Every cell is read as text and cast here: left to infer, the reader would
    # type a column from its first rows and turn a later "n/a" into a silent null.
    raw = pl.read_excel(path, engine="calamine", read_options={"dtypes": "string"})
    missing = [column for column in S8_COLUMNS if column not in raw.columns]
    if missing:
        raise ValueError(
            f"Table S8 is missing the required column(s) {missing}. Found: {raw.columns[:8]}."
        )
    frame = (
        raw.select([pl.col(source).alias(target) for source, target in S8_COLUMNS.items()])
        .with_columns(pl.all().str.strip_chars())
        .filter(pl.col("compound_name").is_not_null() & (pl.col("compound_name") != ""))
    )
    for column in _NUMERIC_COLUMNS:
        parsed = frame[column].cast(pl.Float64, strict=False)
        if parsed.null_count():
            raise ValueError(f"Table S8 column '{column}' holds a value that is not a number.")
        frame = frame.with_columns(parsed.alias(column))
    return frame


def reduce_to_compounds(s8: pl.DataFrame) -> pl.DataFrame:
    """Reduce Table S8 to one row per compound: its best-morphology dose.

    Duplicated ``(name, dose)`` rows simply take part in the max, so they never
    add rows. A tie on the score takes the lower dose.

    Args:
        s8: The loaded sheet, from ``load_table_s8``.

    Returns:
        One row per ``compound_name``, sorted by name.
    """
    return (
        s8.sort(
            ["compound_name", "morphology_score", "dose_um"],
            descending=[False, True, False],
            nulls_last=True,
        )
        .group_by("compound_name", maintain_order=True)
        .first()
    )


def treated_ids(features: pl.DataFrame) -> list[str]:
    """Return the ids with at least one treated row in the published table.

    Args:
        features: The published feature frame, after any plate exclusion; needs
            ``cbkid`` and ``pert_type``.

    Returns:
        The treated ``cbkid`` values, sorted.
    """
    return sorted(
        features.filter(pl.col("pert_type") == "trt")["cbkid"].unique().drop_nulls().to_list()
    )


def _match_name(
    candidates: tuple[str | None, str | None],
    exact: set[str],
    folded: dict[str, str],
) -> str | None:
    """Return the Table S8 name a compound matches, trying each key in order."""
    pert_iname, name = candidates
    if pert_iname and pert_iname in exact:
        return pert_iname
    if pert_iname and pert_iname.casefold() in folded:
        return folded[pert_iname.casefold()]
    if name and name.casefold() in folded:
        return folded[name.casefold()]
    return None


def build_compound_table(
    compound_index: pl.DataFrame,
    treated: list[str],
    reduced: pl.DataFrame,
) -> tuple[pl.DataFrame, dict[str, Any]]:
    """Join each treated compound to its Table S8 scores by name.

    Names are matched on the exact ``pert_iname`` first, then on it case-folded,
    then on the index's CBCS ``name`` case-folded. Two ids may share one S8 name;
    both rows then show its score, and the name is reported.

    Args:
        compound_index: The index precompute builds (``compounds.parquet``).
        treated: The treated ids, from ``treated_ids``.
        reduced: Table S8 reduced to one row per compound.

    Returns:
        The table (``TABLE_COLUMNS``, sorted by ``cbkid``) and a JSON-serialisable
        report: ``n_rows``, ``n_scored``, ``unmatched_names``, ``shared_names``.
    """
    index = compound_index.with_columns(
        [
            pl.lit(None, dtype=pl.String).alias(column)
            for column in ("name", "broad_moa", "broad_target", "pert_iname")
            if column not in compound_index.columns
        ]
    ).filter(pl.col("cbkid").is_in(treated))

    names = reduced["compound_name"].to_list()
    exact = set(names)
    folded: dict[str, str] = {}
    for name in names:
        folded.setdefault(name.casefold(), name)

    matches = [
        _match_name((row["pert_iname"], row["name"]), exact, folded)
        for row in index.select("pert_iname", "name").iter_rows(named=True)
    ]
    index = index.with_columns(pl.Series("compound_name", matches, dtype=pl.String))

    table = index.join(reduced, on="compound_name", how="left").select(TABLE_COLUMNS).sort("cbkid")

    used = Counter(match for match in matches if match is not None)
    report = {
        "n_rows": table.height,
        "n_scored": table.filter(pl.col("morphology_score").is_not_null()).height,
        "unmatched_names": sorted(set(names) - set(used)),
        "shared_names": sorted(name for name, count in used.items() if count > 1),
    }
    return table, report


def _number(value: object) -> float | None:
    """Parse a query value as a finite float, or ``None`` if it is not one."""
    try:
        number = float(str(value).strip())
    except TypeError, ValueError:
        return None
    return number if math.isfinite(number) else None


def _cell(value: object) -> str:
    """Render one score cell; a missing value is said in words."""
    if value is None:
        return NOT_REPORTED
    return f"{value:g}"


def table_rows(frame: pl.DataFrame) -> list[list[str]]:
    """Render the table as display cells, in ``TABLE_HEADERS`` order.

    Args:
        frame: A table with ``TABLE_COLUMNS``.

    Returns:
        One list of strings per row; a missing score is ``NOT_REPORTED``.
    """
    return [
        [row[column] or "" for column in _TEXT_COLUMNS]
        + [_cell(row[column]) for column in _SCORE_COLUMNS]
        for row in frame.select(TABLE_COLUMNS).iter_rows(named=True)
    ]


def sort_key(params: Mapping[str, str]) -> str:
    """Return the requested sort key, or the default when it is not one we offer."""
    requested = params.get("sort", "")
    return requested if requested in dict(SORT_OPTIONS) else DEFAULT_SORT


def select_rows(frame: pl.DataFrame, params: Mapping[str, str]) -> pl.DataFrame:
    """Apply a reader's filters, search and sort — the one selection for view and export.

    The search is the shared data table's own semantics (a case-insensitive
    substring of any rendered cell, ``cms/services/data_table.py``), applied here
    too so the CSV export carries exactly the rows the table counts.

    Args:
        frame: A table with ``TABLE_COLUMNS``.
        params: The request's query parameters.

    Returns:
        The selected rows, sorted, unscored rows last.
    """
    selected = frame
    for parameter, (column, is_lower) in RANGE_FILTERS.items():
        bound = _number(params.get(parameter, ""))
        if bound is None:
            continue
        selected = selected.filter(pl.col(column) >= bound if is_lower else pl.col(column) <= bound)
    if params.get("hits"):
        selected = selected.filter(pl.col("morphology_score") > HIT_THRESHOLD)

    term = str(params.get("search", "")).strip().lower()
    if term:
        mask = [
            any(term in strip_tags(str(cell)).lower() for cell in row)
            for row in table_rows(selected)
        ]
        selected = selected.filter(pl.Series(mask, dtype=pl.Boolean))

    key = sort_key(params)
    column = key.lstrip("-")
    return selected.sort(
        [column, "cbkid"], descending=[key.startswith("-"), False], nulls_last=True
    )


def filter_state(params: Mapping[str, str]) -> dict[str, str]:
    """Return the reader's current controls, cleaned, for the form to re-render."""
    state = {
        parameter: params.get(parameter, "")
        for parameter in RANGE_FILTERS
        if _number(params.get(parameter, "")) is not None
    }
    state["hits"] = "1" if params.get("hits") else ""
    state["sort"] = sort_key(params)
    return state
