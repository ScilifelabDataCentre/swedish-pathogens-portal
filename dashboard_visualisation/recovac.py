"""RECOVAC dashboard visualisation (zip of named source workbooks).

Editors upload a single ``.zip`` whose members match the filenames used by
the legacy pandas scripts. Members may be ``.xlsx`` (production) or ``.csv``
with the same stem (tests / CSV export).

Figure IDs (Wagtail ``plotly_figure`` / ``DashboardData.data`` keys):

* ``swedishpop_subplot`` — coverage (%) and ICU admissions by age
  (legacy blob ``swedishpop_subplot_button.json``)
* ``comorbidity_subplot`` — coverage (%) and COVID-19 cases by comorbidity
  (legacy blob ``comorbs_subplot_button.json``)

Set each ``plotly_figure`` StreamField height to **1100** so the two subplot
rows stay readable (the figure JSON also records ``layout.height`` 1100).
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
import polars as pl
from plotly.subplots import make_subplots

from dashboard_visualisation.utils.plotly import figure_to_json
from dashboard_visualisation.utils.uploads import (
    SourceFile,
    is_field_file,
    rewind_source_file,
)

REQUIRED_ZIP_STEMS: tuple[str, ...] = (
    "vacc_pop_18plus",
    "vacc_pop_18-59",
    "vacc_pop_60plus",
    "iva_vacc_18plus",
    "iva_vacc_18-59",
    "iva_vacc_60plus",
    "cm_cvd_cardio_vacc_SciLifeLab",
    "cm_dm_vacc_SciLifeLab",
    "cm_resp_dis1_vacc_SciLifeLab",
    "cm_sos_cancer_vacc_SciLifeLab",
    "cm_cvd_cardio_covid_vacc_SciLifeLab",
    "cm_dm_covid_vacc_SciLifeLab",
    "cm_resp_dis1_covid_vacc_SciLifeLab",
    "cm_sos_cancer_covid_vacc_SciLifeLab",
)

_ALLOWED_MEMBER_EXTENSIONS = {".csv", ".xls", ".xlsx"}
_SKIP_NAME_PARTS = {"__macosx"}
_CASES_MIN_DATE = date(2020, 1, 31)
_TRACES_PER_GROUP = 7
_PANEL_COUNT = 2
_VACC_COVERAGE_COLS = ("vacc1", "vacc2", "vacc3", "vacc4", "vacc5", "vacc6")
_VACC_COUNT_COLS = ("vacc0", "vacc1", "vacc2", "vacc3", "vacc4", "vacc5", "vacc6")
_DOSE_SHARE_COLS = (
    "no_dose",
    "one_dose",
    "two_dose",
    "three_dose",
    "four_dose",
    "five_dose",
    "six_dose",
)
_DOSE_COLUMN_NAMES = ("vacc0", "vacc1", "vacc2", "vacc3", "vacc4", "vacc5", "vacc6")
_KNOWN_COLUMNS = {
    "wk",
    *_DOSE_COLUMN_NAMES,
    "c19_i1",
    "c19_d2",
}
_COVERAGE_REQUIRED_COLUMNS = ("wk", *_VACC_COVERAGE_COLS)
_ICU_REQUIRED_COLUMNS = ("wk", *_VACC_COUNT_COLS, "c19_i1")
_CASES_REQUIRED_COLUMNS = ("wk", *_VACC_COUNT_COLS, "c19_d2")

# Darker gold than the legacy yellow ``rgba(235,235,0,1)``, which fails contrast
# on a white plot background. Same label on area and bar traces so legendgroup
# can isolate one dose across both subplot rows.
_TWO_DOSE_COLOR = "#C4A000"
_AREA_SERIES = (
    ("six_dose", "Six Doses", "grey"),
    ("five_dose", "Five Doses", "black"),
    ("four_dose", "Four Doses", "rgba(5,48,97,1)"),
    ("three_dose", "Three Doses", "rgba(146,197,222,1)"),
    ("two_dose", "Two Doses", _TWO_DOSE_COLOR),
    ("one_dose", "One Dose", "rgba(244,165,130,1)"),
    ("no_dose", "No Doses", "rgba(178,24,43,1)"),
)
_BAR_SERIES = (
    ("vacc6", "Six Doses", "grey"),
    ("vacc5", "Five Doses", "black"),
    ("vacc4", "Four Doses", "rgba(5,48,97,1)"),
    ("vacc3", "Three Doses", "rgba(146,197,222,1)"),
    ("vacc2", "Two Doses", _TWO_DOSE_COLOR),
    ("vacc1", "One Dose", "rgba(244,165,130,1)"),
    ("vacc0", "No Doses", "rgba(178,24,43,1)"),
)
_COVERAGE_HOVER = "%{fullData.name}: %{y:.1f}%<extra></extra>"
_COUNT_HOVER = "%{fullData.name}: %{y:.0f}<extra></extra>"
_COUNT_HOVER_WITH_TOTAL = (
    "%{fullData.name}: %{y:.0f} (week total: %{customdata:.0f})<extra></extra>"
)
_FIGURE_HEIGHT = 1100
# Live plots put menus at 0.1 so Age / Comorbidity / Timeframe stay visible.
_BUTTON_MENU_X = 0.1
_BUTTON_LABEL_X = -0.03
_XAXIS_SPIKE: dict[str, Any] = {
    "type": "date",
    "showspikes": True,
    "spikemode": "across",
    "spikethickness": 1,
    "spikecolor": "#4b5563",
    "hoverformat": "%b %d, %Y",
}

_SWEDISH_GROUPS: tuple[tuple[str, str, str], ...] = (
    ("> 18", "vacc_pop_18plus", "iva_vacc_18plus"),
    ("18-59", "vacc_pop_18-59", "iva_vacc_18-59"),
    ("> 60", "vacc_pop_60plus", "iva_vacc_60plus"),
)
_COMORBIDITY_GROUPS: tuple[tuple[str, str, str], ...] = (
    (
        "Cardiovascular disease",
        "cm_cvd_cardio_vacc_SciLifeLab",
        "cm_cvd_cardio_covid_vacc_SciLifeLab",
    ),
    ("Diabetes", "cm_dm_vacc_SciLifeLab", "cm_dm_covid_vacc_SciLifeLab"),
    (
        "Respiratory disease",
        "cm_resp_dis1_vacc_SciLifeLab",
        "cm_resp_dis1_covid_vacc_SciLifeLab",
    ),
    ("Cancer", "cm_sos_cancer_vacc_SciLifeLab", "cm_sos_cancer_covid_vacc_SciLifeLab"),
)


def _source_filename(source_file: SourceFile, filename: str) -> str:
    """Return a display filename for the upload."""
    if filename:
        return filename
    return getattr(source_file, "name", "") or ""


def _file_extension(name: str) -> str:
    """Return the lowercased suffix including the leading dot, or empty."""
    if "." not in Path(name).name:
        return ""
    return Path(name).suffix.lower()


def _read_source_bytes(source_file: SourceFile) -> bytes:
    """Read the upload into memory and rewind file-like objects."""
    rewind_source_file(source_file)
    if isinstance(source_file, (str, Path)):
        return Path(source_file).read_bytes()

    if is_field_file(source_file) and getattr(source_file, "name", None):
        with source_file.open("rb") as handle:
            return handle.read()

    if not hasattr(source_file, "read"):
        raise TypeError(f"Unsupported file type for zip reading: {type(source_file)!r}")

    rewind_source_file(source_file)
    raw = source_file.read()
    rewind_source_file(source_file)
    if isinstance(raw, str):
        return raw.encode("utf-8")
    return raw


def _is_skipped_zip_name(member_name: str) -> bool:
    """Return True for directories and junk zip entries (macOS metadata)."""
    path = Path(member_name)
    parts_lower = {part.lower() for part in path.parts}
    if parts_lower & _SKIP_NAME_PARTS:
        return True
    if member_name.endswith("/"):
        return True
    name = path.name
    return not name or name.startswith(".") or name.startswith("__")


def _index_zip_members(archive: zipfile.ZipFile) -> dict[str, str] | str:
    """Map required stems to zip member paths, or return an error string."""
    by_stem: dict[str, str] = {}
    for member_name in archive.namelist():
        if _is_skipped_zip_name(member_name):
            continue
        basename = Path(member_name).name
        extension = _file_extension(basename)
        if extension not in _ALLOWED_MEMBER_EXTENSIONS:
            return (
                f'"{basename}" in the zip is not a supported table '
                f"({', '.join(sorted(_ALLOWED_MEMBER_EXTENSIONS))})."
            )
        stem = Path(basename).stem
        if stem in by_stem:
            return f'The zip contains more than one file for "{stem}".'
        by_stem[stem] = member_name
    return by_stem


def _member_is_readable_table(archive: zipfile.ZipFile, member_name: str) -> str | None:
    """Return an error when a zip member is empty or not a headered table."""
    basename = Path(member_name).name
    try:
        payload = archive.read(member_name)
    except zipfile.BadZipFile as exc:
        return f'Could not read "{basename}" in the zip: {exc}'

    if not payload.strip():
        return f'"{basename}" in the zip is empty.'

    extension = _file_extension(basename)
    if extension != ".csv":
        try:
            frame = _read_member_dataframe(archive, member_name)
        except Exception as exc:
            return f'Could not read "{basename}" in the zip: {exc}'
        missing_cols = _table_missing_required_columns(frame, Path(basename).stem)
        if missing_cols:
            return f'"{basename}" is missing columns: {", ".join(missing_cols)}.'
        return None

    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        return f'"{basename}" in the zip is not valid UTF-8 text.'

    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error as exc:
        return f'Could not parse "{basename}" in the zip: {exc}'

    if len(rows) < 2:
        return f'"{basename}" in the zip must have a header row and at least one data row.'

    header = {_canonical_column_name(col) for col in rows[0]}
    missing_cols = [
        column for column in _required_columns_for_stem(Path(basename).stem) if column not in header
    ]
    if missing_cols:
        return f'"{basename}" is missing columns: {", ".join(missing_cols)}.'
    return None


def _table_missing_required_columns(df: pl.DataFrame, stem: str) -> list[str]:
    """Return required column names still missing after aliasing."""
    columns = set(_normalise_columns(df).columns)
    return [column for column in _required_columns_for_stem(stem) if column not in columns]


def _required_columns_for_stem(stem: str) -> tuple[str, ...]:
    """Return the header columns expected for a named RECOVAC workbook."""
    if stem.startswith("iva_vacc_"):
        return _ICU_REQUIRED_COLUMNS
    if "_covid_vacc_" in stem:
        return _CASES_REQUIRED_COLUMNS
    return _COVERAGE_REQUIRED_COLUMNS


def validate_source_file(
    source_file: SourceFile,
    *,
    filename: str = "",
    size_bytes: int | None = None,
) -> str | None:
    """Validate a RECOVAC DashboardData source upload (zip of named tables).

    Used by the registry instead of the generic CSV path. Members may be
    ``.xlsx`` (production) or ``.csv`` with the same stem (tests / CSV export).
    """
    name = _source_filename(source_file, filename)
    if _file_extension(name) != ".zip":
        display = name or "the uploaded file"
        return (
            f'"{display}" is not supported for the RECOVAC dashboard. '
            "Upload a .zip containing the 14 named source workbooks."
        )

    if size_bytes == 0:
        return "The uploaded zip file is empty."

    try:
        raw = _read_source_bytes(source_file)
    except (OSError, TypeError, ValueError) as exc:
        return f"Could not read the uploaded zip: {exc}"

    if not raw:
        return "The uploaded zip file is empty."

    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return "The uploaded file is not a valid zip archive."

    with archive:
        indexed = _index_zip_members(archive)
        if isinstance(indexed, str):
            return indexed

        missing = [f"{stem}.xlsx" for stem in REQUIRED_ZIP_STEMS if stem not in indexed]
        if missing:
            return "Missing required files in the zip: " + ", ".join(missing)

        extra = sorted(stem for stem in indexed if stem not in REQUIRED_ZIP_STEMS)
        if extra:
            names = [Path(indexed[stem]).name for stem in extra]
            return "Unexpected files in the zip: " + ", ".join(names)

        for stem in REQUIRED_ZIP_STEMS:
            member_error = _member_is_readable_table(archive, indexed[stem])
            if member_error:
                return member_error

    return None


def _read_member_dataframe(archive: zipfile.ZipFile, member_name: str) -> pl.DataFrame:
    """Read one zip member as a Polars table (CSV or Excel)."""
    payload = archive.read(member_name)
    extension = _file_extension(member_name)
    if extension == ".csv":
        return pl.read_csv(io.BytesIO(payload))
    return pl.read_excel(io.BytesIO(payload), engine="calamine")


def _load_tables(source_file: SourceFile) -> dict[str, pl.DataFrame]:
    """Open the RECOVAC zip and return a DataFrame per required stem."""
    raw = _read_source_bytes(source_file)
    archive = zipfile.ZipFile(io.BytesIO(raw))
    with archive:
        indexed = _index_zip_members(archive)
        if isinstance(indexed, str):
            raise ValueError(indexed)
        missing = [stem for stem in REQUIRED_ZIP_STEMS if stem not in indexed]
        if missing:
            raise ValueError("Missing required files in the zip: " + ", ".join(missing))
        return {
            stem: _normalise_columns(_read_member_dataframe(archive, indexed[stem]))
            for stem in REQUIRED_ZIP_STEMS
        }


def _canonical_column_name(column: str) -> str:
    """Map a workbook header onto the names used by the legacy pandas scripts.

    Population coverage files use ``vacc1``…``vacc6``. Comorbidity coverage
    files use the same values under prefixes such as ``cvd_cardio_vacc1``.
    The old comorbidity dataprep renamed by column *position*; we rename by
    suffix so extra columns cannot scramble the mapping.
    """
    stripped = column.strip()
    lowered = stripped.lower()
    if lowered in _KNOWN_COLUMNS:
        return lowered
    for dose in _DOSE_COLUMN_NAMES:
        if lowered.endswith(f"_{dose}"):
            return dose
    return stripped


def _normalise_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Strip header whitespace and alias known RECOVAC / prefixed dose columns."""
    taken = set(df.columns)
    rename: dict[str, str] = {}
    for column in df.columns:
        target = _canonical_column_name(column)
        if target == column:
            continue
        if target in taken:
            continue
        rename[column] = target
        taken.add(target)
        taken.discard(column)
    return df.rename(rename) if rename else df


def _numeric_or_zero(
    df: pl.DataFrame,
    columns: tuple[str, ...],
    *,
    fill_null: bool = True,
) -> pl.DataFrame:
    """Cast named columns to float, treating blanks and missing columns as 0.

    When ``fill_null`` is False, empty cells stay null so a later forward-fill
    can match the legacy comorbidity coverage dataprep.
    """
    exprs: list[pl.Expr] = []
    for name in columns:
        if name not in df.columns:
            exprs.append(pl.lit(0.0).alias(name))
            continue
        parsed = (
            pl.col(name)
            .cast(pl.Utf8)
            .str.strip_chars()
            .replace("", None)
            .cast(pl.Float64, strict=False)
        )
        if fill_null:
            parsed = parsed.fill_null(0.0)
        exprs.append(parsed.alias(name))
    return df.with_columns(exprs)


def _monday_from_iso_week(year: int, week_no: int) -> date | None:
    """Return Monday of an ISO week, or None when the week number is invalid."""
    try:
        return date.fromisocalendar(year, week_no, 1)
    except ValueError:
        return None


def _prep_week_dates(
    df: pl.DataFrame,
    *,
    min_date: date | None = None,
) -> pl.DataFrame:
    """Convert ``wk`` (``2021w03``) to Monday-of-week ``date``; drop year 2019."""
    if "wk" not in df.columns:
        raise ValueError('Table is missing the "wk" column.')

    prepared = (
        df.with_columns(pl.col("wk").cast(pl.Utf8).str.strip_chars())
        .with_columns(
            pl.col("wk").str.split("w").list.get(0).cast(pl.Int32, strict=False).alias("_year"),
            pl.col("wk").str.split("w").list.get(1).cast(pl.Int32, strict=False).alias("_week_no"),
        )
        .filter(pl.col("_year").is_not_null() & pl.col("_week_no").is_not_null())
        .filter(pl.col("_year") != 2019)
        .with_columns(
            pl.struct(["_year", "_week_no"])
            .map_elements(
                lambda row: _monday_from_iso_week(row["_year"], row["_week_no"]),
                return_dtype=pl.Date,
            )
            .alias("date")
        )
        .drop(["_year", "_week_no", "wk"])
        .filter(pl.col("date").is_not_null())
    )
    if min_date is not None:
        prepared = prepared.filter(pl.col("date") >= min_date)
    return prepared.with_columns(pl.col("date").dt.strftime("%Y-%m-%d"))


def _prep_coverage(df: pl.DataFrame, *, ffill: bool = False) -> pl.DataFrame:
    """De-cumulate coverage shares (0–1) into exclusive dose-level percents.

    Comorbidity tables forward-fill the cumulative dose columns first (legacy
    ``ffill`` after empty Excel cells), then treat remaining leading nulls as 0.
    """
    df = _normalise_columns(df)
    prepared = _prep_week_dates(_numeric_or_zero(df, _VACC_COVERAGE_COLS, fill_null=False))
    if ffill:
        prepared = prepared.with_columns(pl.col(_VACC_COVERAGE_COLS).forward_fill())
    prepared = prepared.with_columns(pl.col(_VACC_COVERAGE_COLS).fill_null(0.0))
    prepared = prepared.with_columns(
        ((1 - pl.col("vacc1")) * 100).alias("no_dose"),
        ((pl.col("vacc1") - pl.col("vacc2")) * 100).alias("one_dose"),
        ((pl.col("vacc2") - pl.col("vacc3")) * 100).alias("two_dose"),
        ((pl.col("vacc3") - pl.col("vacc4")) * 100).alias("three_dose"),
        ((pl.col("vacc4") - pl.col("vacc5")) * 100).alias("four_dose"),
        ((pl.col("vacc5") - pl.col("vacc6")) * 100).alias("five_dose"),
        (pl.col("vacc6") * 100).alias("six_dose"),
    ).drop(list(_VACC_COVERAGE_COLS))
    if prepared.is_empty():
        raise ValueError("Coverage table has no rows after dropping year 2019.")
    return prepared


def _prep_counts(
    df: pl.DataFrame,
    *,
    total_column: str,
    min_date: date | None = None,
) -> pl.DataFrame:
    """Parse week dates on an ICU / cases count table."""
    df = _normalise_columns(df)
    had_total = total_column in df.columns
    numeric_cols = _VACC_COUNT_COLS + ((total_column,) if had_total else ())
    prepared = _prep_week_dates(_numeric_or_zero(df, numeric_cols), min_date=min_date)
    if not had_total:
        prepared = prepared.with_columns(pl.sum_horizontal(_VACC_COUNT_COLS).alias(total_column))
    if prepared.is_empty():
        raise ValueError("Count table has no rows after date filtering.")
    return prepared


def _date_values(df: pl.DataFrame) -> list[str]:
    """Return ISO date strings from a prepared table."""
    return df.get_column("date").to_list()


def _xaxis_ranges(coverage_dates: list[str], count_dates: list[str]) -> dict[str, dict[str, Any]]:
    """Return Plotly x-axis settings for full timeline vs aligned overlap."""
    coverage_start, coverage_end = min(coverage_dates), max(coverage_dates)
    count_start, count_end = min(count_dates), max(count_dates)
    aligned_start = max(coverage_start, count_start)
    aligned_end = min(coverage_end, count_end)
    return {
        "all": {
            "xaxis": {
                "title": "<b>Date</b>",
                "range": [coverage_start, coverage_end],
                "anchor": "y",
                **_XAXIS_SPIKE,
            },
            "xaxis2": {
                "title": "<b>Date</b>",
                "showgrid": True,
                "linecolor": "black",
                "range": [count_start, count_end],
                "anchor": "y2",
                **_XAXIS_SPIKE,
            },
        },
        "align": {
            "xaxis": {
                "title": "<b>Date</b>",
                "range": [aligned_start, aligned_end],
                "anchor": "y",
                **_XAXIS_SPIKE,
            },
            "xaxis2": {
                "title": "<b>Date</b>",
                "showgrid": True,
                "linecolor": "black",
                "range": [aligned_start, aligned_end],
                "anchor": "y2",
                **_XAXIS_SPIKE,
            },
        },
    }


def _group_visibility(
    n_groups: int,
    group_index: int,
    *,
    traces_per_group: int = _TRACES_PER_GROUP,
    n_panels: int = _PANEL_COUNT,
) -> list[bool]:
    """Return a Plotly ``visible`` mask covering both subplot panels for one group.

    Traces are added as all groups on the top panel, then all groups on the
    bottom panel. The legacy scripts only flagged the top panel (half length);
    this mask is always ``n_groups * traces_per_group * n_panels`` long.
    """
    panel_len = n_groups * traces_per_group
    mask = [False] * (panel_len * n_panels)
    for panel in range(n_panels):
        start = panel * panel_len + group_index * traces_per_group
        mask[start : start + traces_per_group] = [True] * traces_per_group
    return mask


def _add_area_traces(
    fig: go.Figure,
    frames: list[pl.DataFrame],
    *,
    series: tuple[tuple[str, str, str], ...],
) -> None:
    """Add stacked coverage area traces (one group after another) on row 1."""
    for group_index, frame in enumerate(frames):
        dates = _date_values(frame)
        visible = group_index == 0
        for column, name, color in series:
            fig.add_trace(
                go.Scatter(
                    x=dates,
                    y=frame.get_column(column).to_list(),
                    name=name,
                    mode="lines",
                    line={"width": 2, "color": color},
                    fillcolor=color,
                    stackgroup="one",
                    legendgroup=name,
                    visible=visible,
                    hovertemplate=_COVERAGE_HOVER,
                    showlegend=group_index == 0,
                ),
                row=1,
                col=1,
            )


def _add_bar_traces(
    fig: go.Figure,
    frames: list[pl.DataFrame],
    *,
    series: tuple[tuple[str, str, str], ...],
    total_column: str,
) -> None:
    """Add stacked count bar traces (one group after another) on row 2."""
    for group_index, frame in enumerate(frames):
        dates = _date_values(frame)
        visible = group_index == 0
        weekly_total = frame.get_column(total_column).to_list()
        for series_index, (column, name, color) in enumerate(series):
            include_week_total = series_index == 0
            fig.add_trace(
                go.Bar(
                    name=name,
                    x=dates,
                    y=frame.get_column(column).to_list(),
                    marker={"color": color, "line": {"color": "#000000", "width": 1}},
                    legendgroup=name,
                    visible=visible,
                    showlegend=False,
                    customdata=weekly_total if include_week_total else None,
                    hovertemplate=(_COUNT_HOVER_WITH_TOTAL if include_week_total else _COUNT_HOVER),
                ),
                row=2,
                col=1,
            )


def _two_panel_subplot_fig(
    groups: list[tuple[str, pl.DataFrame, pl.DataFrame]],
    *,
    filter_label: str,
    count_axis_title: str,
    count_subplot_title: str,
    count_dtick: int,
    total_column: str,
) -> go.Figure:
    """Build a 2-row subplot with group buttons and a timeframe toggle."""
    labels = [label for label, _, _ in groups]
    coverage_frames = [coverage for _, coverage, _ in groups]
    count_frames = [counts for _, _, counts in groups]
    n_groups = len(groups)

    fig = make_subplots(
        rows=2,
        cols=1,
        vertical_spacing=0.2,
        subplot_titles=("Vaccine coverage (%)", count_subplot_title),
    )
    _add_area_traces(fig, coverage_frames, series=_AREA_SERIES)
    _add_bar_traces(fig, count_frames, series=_BAR_SERIES, total_column=total_column)

    x_axes = _xaxis_ranges(_date_values(coverage_frames[0]), _date_values(count_frames[0]))
    highest = max(max(frame.get_column(total_column).to_list()) for frame in count_frames)
    y_top = max(1, int(highest * 1.05))

    group_buttons = [
        {
            "label": label,
            "method": "update",
            "args": [{"visible": _group_visibility(n_groups, index)}],
        }
        for index, label in enumerate(labels)
    ]
    button_layer_1_height = 1.22
    button_layer_2_height = 1.14

    fig.update_layout(
        title=" ",
        height=_FIGURE_HEIGHT,
        yaxis={
            "title": "<b>People with this dose level (%)</b>",
            "ticktext": ["0 ", "20 ", "40 ", "60 ", "80 ", "100 "],
            "tickvals": [0, 20, 40, 60, 80, 100],
            "range": [0, 100],
        },
        yaxis2={
            "title": count_axis_title,
            "showgrid": True,
            "gridcolor": "lightgrey",
            "linecolor": "black",
            "dtick": count_dtick,
            "range": [0, y_top],
        },
        xaxis=x_axes["all"]["xaxis"],
        xaxis2=x_axes["all"]["xaxis2"],
        barmode="stack",
        plot_bgcolor="white",
        autosize=True,
        font={"size": 12},
        margin={"r": 180, "t": 200, "b": 60, "l": 80},
        showlegend=True,
        legend={
            "title": {
                "text": (
                    "<b>Vaccine doses</b><br>"
                    "<span style='font-size:11px'>Click to hide; "
                    "double-click to isolate</span>"
                ),
            },
            "yanchor": "top",
            "y": 1.0,
            "xanchor": "left",
            "x": 1.02,
            "font": {"size": 12},
            "tracegroupgap": 0,
        },
        hoverlabel={"align": "left"},
        hovermode="x unified",
        spikedistance=-1,
        updatemenus=[
            {
                "buttons": group_buttons,
                "type": "buttons",
                "direction": "right",
                "pad": {"r": 10, "t": 10},
                "showactive": True,
                "x": _BUTTON_MENU_X,
                "xanchor": "left",
                "y": button_layer_1_height,
                "yanchor": "top",
            },
            {
                "buttons": [
                    {
                        "label": "Select full timeline",
                        "method": "relayout",
                        "args": [x_axes["all"]],
                    },
                    {
                        "label": "Align both plots",
                        "method": "relayout",
                        "args": [x_axes["align"]],
                    },
                ],
                "type": "buttons",
                "direction": "right",
                "pad": {"r": 10, "t": 10},
                "showactive": True,
                "x": _BUTTON_MENU_X,
                "xanchor": "left",
                "y": button_layer_2_height,
                "yanchor": "top",
            },
        ],
    )
    fig.add_annotation(
        text=filter_label,
        x=_BUTTON_LABEL_X,
        xref="paper",
        y=button_layer_1_height * 0.978,
        yref="paper",
        align="left",
        showarrow=False,
    )
    fig.add_annotation(
        text="Timeframe:",
        x=_BUTTON_LABEL_X,
        xref="paper",
        y=button_layer_2_height * 0.978,
        yref="paper",
        align="left",
        showarrow=False,
    )
    return fig


def _swedishpop_subplot_fig(tables: dict[str, pl.DataFrame]) -> go.Figure:
    """Coverage vs ICU admissions for the three Swedish age groups."""
    groups = [
        (
            label,
            _prep_coverage(tables[coverage_stem]),
            _prep_counts(tables[count_stem], total_column="c19_i1"),
        )
        for label, coverage_stem, count_stem in _SWEDISH_GROUPS
    ]
    return _two_panel_subplot_fig(
        groups,
        filter_label="Age Range:",
        count_axis_title="<b>Admissions to ICU (number of people)</b>",
        count_subplot_title="ICU admissions (count)",
        count_dtick=50,
        total_column="c19_i1",
    )


def _comorbidity_subplot_fig(tables: dict[str, pl.DataFrame]) -> go.Figure:
    """Coverage vs COVID-19 cases for the four comorbidity groups."""
    groups = [
        (
            label,
            _prep_coverage(tables[coverage_stem], ffill=True),
            _prep_counts(
                tables[count_stem],
                total_column="c19_d2",
                min_date=_CASES_MIN_DATE,
            ),
        )
        for label, coverage_stem, count_stem in _COMORBIDITY_GROUPS
    ]
    return _two_panel_subplot_fig(
        groups,
        filter_label="Comorbidity:",
        count_axis_title="<b>COVID-19 cases (number of people)</b>",
        count_subplot_title="COVID-19 cases (count)",
        count_dtick=500,
        total_column="c19_d2",
    )


def generate_figures(source_file: SourceFile) -> dict[str, Any]:
    """Build both RECOVAC subplot figures from the uploaded zip."""
    tables = _load_tables(source_file)
    return {
        "swedishpop_subplot": figure_to_json(_swedishpop_subplot_fig(tables)),
        "comorbidity_subplot": figure_to_json(_comorbidity_subplot_fig(tables)),
    }
