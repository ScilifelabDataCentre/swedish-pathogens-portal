# 12. Data processing tools for visualisations

**Date**: 2026-09-18

## Status

Accepted

## Context

The portal's dashboards and the DRR pipeline ingest tabular data — editorial uploads through the Wagtail admin, and files handed to an offline management command.
Until now nothing recorded which libraries were sanctioned for that work, or why.

The stack arrived by inheritance rather than by decision.
`pandas`, `polars`, `numpy`, `fastexcel` and `plotly` were all pinned together in the repository's first commit (`84cd1e5`, *Initiate spp-wagtail*, 11 March 2026), carried over from the earlier `swedish-pathogens-portal-django` repository.
`pandas` was removed later, in `cc7158e` (*Replace Padas with Polars*, PR #56), without an ADR.
The result is a stack that works but whose composition was never argued: Polars is used consistently, while NumPy and `fastexcel` were never examined against the architecture that grew around them.

Three properties of the current code shape this decision.

**Processing runs on the write path, not the request path.**
Figures are generated when an editor saves a `DashboardData` snippet (`cms/snippets/dashboard_data.py`, `_regenerate_figures_from_storage`) and stored as Plotly JSON in the database, or precomputed offline by `cms/management/commands/drr_precompute.py`.
Public page views serve those cached artefacts.
There is one deliberate exception: `DrrDatasetPage.download_compound` (`cms/pages/drr_dataset.py`) filters the Parquet feature table per download request.

**The consumers are Plotly figures.**
ADR-0004 selected Plotly for dashboards; this ADR covers the layer that feeds it.
Plotly 7 reads dataframes through `narwhals`, which supports Polars natively, so the plotting layer exerts no pull back towards pandas.

**Not every data path is frame-shaped.**
`dashboard_visualisation/liver_resource/` is a port of an R pipeline whose work is set membership and per-gene classification, not tabular transformation.
`dashboard_visualisation/` and `portal_data/` are plain packages rather than Django apps (ADR-0009).

## Decision

We will use **Polars** as the single dataframe library for tabular ingest, with a narrow and stated role for each remaining tool.

| Tool             | Pinned   | Role                                                            |
|------------------|----------|-----------------------------------------------------------------|
| Polars           | `1.44.1` | The dataframe layer: all tabular ingest and transformation      |
| NumPy            | `2.5.2`  | The array boundary only: linear algebra and matrix construction |
| fastexcel        | `0.21.0` | The Excel ingest engine, via Polars' `calamine` engine          |
| Standard library | —        | Work that is not frame-shaped                                   |

### Polars — the dataframe layer

Every dashboard registered in `dashboard_visualisation/registry.py`, the whole DRR pipeline (`dashboard_visualisation/drr/`), and the generic upload reader `read_csv_dataframe` (`dashboard_visualisation/utils/uploads.py`) read and transform data with Polars.
It covers every format the portal ingests: CSV, TSV, Excel and Parquet.

Polars was preferred over pandas for its explicit schema handling, its lazy API, and a single Rust runtime in place of pandas' own NumPy coupling.
Because Plotly reaches dataframes through `narwhals`, nothing in the rendering path requires pandas to be reinstated.

Dataframe-shaped work — reading, filtering, joining, grouping, reshaping, aggregating — belongs here and not in NumPy.

### NumPy — the array boundary

NumPy is admitted only where data has stopped being a dataframe and become an array.
It has three call sites outside tests:

- `build_pca` (`dashboard_visualisation/drr/figures.py`) computes the DRR principal-component figure with `np.linalg.svd`.
  Polars has no linear algebra, the figure is a required part of the DRR dataset page, and the alternatives are worse: SciPy and scikit-learn are substantially larger, and hand-writing an SVD on a scientific figure is not acceptable.
- `FeatureTable.numeric_matrix` (`dashboard_visualisation/drr/loader.py`) materialises the float64 feature matrix that the SVD consumes and rejects it if any value is missing or non-finite.
  The check belongs in NumPy: it validates the exact array returned, and because Polars nulls become `NaN` in `to_numpy()`, a single `np.isfinite` covers nulls, `NaN` and infinities together.
- `get_qual_plots` (`dashboard_visualisation/slu_wastewater/qualitative_plots.py`) masks a pivoted table with `np.where` to build the two-dimensional `z` and `customdata` matrices a Plotly heatmap trace expects.

NumPy is **not** for frame-shaped work.
Where a transformation can be expressed as a Polars expression, it is written as one.

### fastexcel — the Excel ingest engine

`fastexcel` is never imported directly.
It backs `pl.read_excel(..., engine="calamine")` in `_read_member_dataframe` (`dashboard_visualisation/recovac.py`), which reads the fourteen workbooks inside an uploaded RECOVAC zip archive.
It is declared explicitly because Polars treats it as an optional extra rather than a hard requirement.

The alternative was examined and rejected on measurement.
`openpyxl` is already a hard Wagtail dependency (`openpyxl<4.0,>=3.0.10`) and Polars supports it as an engine, so switching would have removed a direct dependency at no install cost.
Benchmarked on RECOVAC-shaped data (fourteen workbooks of ~280 rows, median of repeated runs; frames identical after column normalisation and forward-fill):

| Step                          | calamine (fastexcel) | openpyxl | Ratio |
|-------------------------------|----------------------|----------|-------|
| Read 14 `.xlsx`               | 28.2 ms              | 174.0 ms | 6.2×  |
| Full `generate_figures` (zip) | 198.2 ms             | 356.1 ms | 1.8×  |

Excel parsing cost is roughly linear in cell count, so the read gap widens as workbooks grow: at ten times the measured size the same read is an estimated ~280 ms against ~1.7 s.
The team decided on 2026-09-17 to keep `fastexcel` and revisit after the production release, since switching also requires changes to the RECOVAC scripts.

### The standard library — work that is not frame-shaped

Where data is not tabular, the standard library is the correct tool and no dataframe library is introduced to make the code look uniform.

`dashboard_visualisation/liver_resource/` is a **deliberate and documented exception** to the Polars rule, not drift.
Its computation, reference-data and export modules use `csv`, dictionaries and sets, and `math.log2`.
The reasons, from Abdullah who ported the R scripts:

- It is a port of `run_tln_analysis.R`, not another tabular dashboard ingest.
  Until the research group accepts that the Python colours, module ratios and gene CSVs are the results they want, the code must stay readable against the R original.
- The work is gene-to-module set membership — R's `intersect()` against Python's `&` on sets — and per-gene up/down classification.
  A dataframe does not make that simpler, and it would obscure the one-to-one correspondence with the R functions.
- The arithmetic is comparison and division against the same fold-change cutoffs as R, kept as `math.log2` constants in `liver_resource/computation.py`.
- Parity was verified against R's `module_scores.csv`: all module ratios matched, with a maximum difference of about 5 × 10⁻⁷.
- It is **not** a performance workaround. Roughly 18,000 genes complete in well under a second.

The TLN graph JSON and its Cytoscape layout are not tabular and will remain outside any dataframe layer regardless of future changes.

The standard library is also correct in smaller places: `csv.Sniffer` for delimiter detection before handing a file to Polars, and CSV export in `portal_data/services.py`.

### Admitting a new data-processing dependency

A new data-processing library is admitted only when all three hold:

1. **It serves a use the current stack cannot express.**
   `np.linalg.svd` qualifies because Polars has no linear algebra. Convenience or familiarity does not.
2. **The case rests on measurement, not assertion.**
   The `calamine` / `openpyxl` comparison above is the standard: a benchmark on representative data, with the outputs shown to match.
3. **If it is needed only by the offline precompute, it is declared in a non-default dependency group.**
   `pyproject.toml` sets `default-groups = []` and the production image syncs only `--group prod`, so a precompute-only dependency leaves the deployed image untouched.

## Consequences

**Positive**

- One dataframe library across every dashboard, so transformations read the same way wherever they appear.
- pandas cannot return through the rendering path, because Plotly reaches dataframes through `narwhals`.
- Data processing stays off the public request path, so a slow or failing transformation affects an editor's save rather than a visitor's page load.
- Each dependency now has a written justification that a future reader can check against the code, and re-examine when the justification changes.

**Negative, and known gaps**

- **The Excel path is untested.** The repository contains no `.xlsx` fixture. Every RECOVAC test supplies `.csv` zip members, so neither the non-CSV validation branch in `_member_is_readable_table` nor the `read_excel` call in `_read_member_dataframe` executes in CI. The single call site justifying `fastexcel` is therefore not covered: a Polars behaviour change or a bad version bump would leave CI green and fail in production. An xlsx-zip fixture and test should be added.
- **Redundant conversions in `get_qual_plots`.** `.to_numpy()` is called four times per loop iteration on two frames that are built once before the loop and never mutated, producing twelve full frame-to-array conversions across the three categories where two would do. Output is correct; the work is wasted. Hoisting both conversions above the loop is the whole fix.
- **Stale comments** referring to "legacy pandas scripts" survived the `cc7158e` migration in `dashboard_visualisation/recovac.py`, `dashboard_visualisation/slu_wastewater/quantitative_plot.py` and `dashboard_visualisation/tests/test_recovac.py`. They describe code that no longer exists.
- NumPy remains a direct dependency of roughly 60 MB installed, resting on one figure. If that figure were ever dropped, the remaining two call sites are expressible in Polars and the dependency could be reconsidered.

**Open questions**

These are recorded so they are not lost. None is scheduled work.

1. **Revisit `fastexcel` and the `calamine` engine** after the production release. Any switch to `openpyxl` needs the xlsx-zip test above in place first, since the current suite would not detect an engine regression.
2. **Whether `.xlsx` should be accepted as an input format at all.** It is proprietary and not FAIR-compliant, and CSV would remove the question along with the dependency. Whether the data provider can supply CSV is being followed up separately.
3. **Revisit the `liver_resource` DE parse, classify and export path** once the research group accepts the current outputs. At that point the contract becomes the golden tests and signed-off CSVs rather than comparison against R, and the DE file itself is tabular. Such a change would be a consistency refactor, not a scientific one, and must keep every existing test matching — including null and NA genes, top-N ties on `t`, and tab-separated against comma-separated files. If parity cannot be preserved, the standard library stays on the compute path. The graph and layout code remains non-frame either way.
