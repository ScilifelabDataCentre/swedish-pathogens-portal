"""Tests for the DRR compound table built from the paper's Table S8 (FREYA-3011)."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import polars as pl
from django.test import SimpleTestCase
from openpyxl import Workbook

from cms.tests.drr.test_drr_downloads import DrrDownloadRouteTestCase
from dashboard_visualisation.drr.table import (
    HIT_THRESHOLD,
    NOT_REPORTED,
    TABLE_HEADERS,
    build_compound_table,
    load_table_s8,
    reduce_to_compounds,
    select_rows,
    table_rows,
    treated_ids,
)

# Table S8's own header row. The last two columns are its legend block, which the
# loader must ignore.
S8_HEADER = [
    "Compound_name",
    "Concentration (uM)",
    "morphology_score",
    "Cell count (%)",
    "Infection rate (%)",
    None,
    "Cell Painting (morphology score)",
]


def write_s8(path: Path, rows: list[tuple]) -> Path:
    """Write a Table S8-shaped workbook; doses are stored as text, as the sheet does."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(S8_HEADER)
    for name, dose, morphology, cell_count, infection in rows:
        sheet.append([name, str(dose), morphology, cell_count, infection, None, None])
    sheet["F2"] = "Threshold "
    sheet["G2"] = ">0.5 morphology score"
    workbook.save(path)
    return path


def compound_index(rows: list[dict]) -> pl.DataFrame:
    """Build a compound index with the columns precompute writes."""
    columns = ["cbkid", "kind", "name", "broad_moa", "broad_target", "pert_iname"]
    return pl.DataFrame(
        {column: [row.get(column) for row in rows] for column in columns},
        schema=dict.fromkeys(columns, pl.String),
    )


class TableS8Case(SimpleTestCase):
    """Shared temporary directory for workbook fixtures."""

    def setUp(self) -> None:
        """Create a temporary directory for the workbook."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)


class LoadTableS8Tests(TableS8Case):
    """The loader keeps the five measured columns and refuses a malformed sheet."""

    def test_text_doses_parse_as_numbers_and_the_legend_is_dropped(self) -> None:
        """Doses stored as text become floats; only the five measured columns remain."""
        path = write_s8(self.base / "s8.xlsx", [("aspirin", "0.3", 0.4, 100, 80)])

        frame = load_table_s8(path)

        self.assertEqual(
            frame.columns,
            [
                "compound_name",
                "dose_um",
                "morphology_score",
                "cell_count_pct",
                "infection_rate_pct",
            ],
        )
        self.assertEqual(frame["dose_um"].to_list(), [0.3])
        self.assertEqual(frame.schema["dose_um"], pl.Float64)

    def test_a_non_numeric_score_fails_naming_the_column(self) -> None:
        """A score that is not a number stops the run rather than becoming a null."""
        path = write_s8(self.base / "s8.xlsx", [("aspirin", "0.3", "n/a", 100, 80)])

        with self.assertRaisesMessage(ValueError, "morphology_score"):
            load_table_s8(path)

    def test_a_missing_column_fails_naming_it(self) -> None:
        """A workbook without the infection column is not Table S8."""
        workbook = Workbook()
        workbook.active.append(["Compound_name", "Concentration (uM)", "morphology_score"])
        workbook.active.append(["aspirin", "0.3", 0.4])
        path = self.base / "short.xlsx"
        workbook.save(path)

        with self.assertRaisesMessage(ValueError, "Infection rate (%)"):
            load_table_s8(path)


class ReduceToCompoundsTests(TableS8Case):
    """One row per compound: the dose with the highest morphology score."""

    def _reduced(self, rows: list[tuple]) -> pl.DataFrame:
        return reduce_to_compounds(load_table_s8(write_s8(self.base / "s8.xlsx", rows)))

    def test_four_doses_reduce_to_the_best_morphology_dose_with_its_own_readouts(self) -> None:
        """The infection rate and cell count come from the same dose as the score."""
        reduced = self._reduced(
            [
                ("aspirin", "0.1", -0.05, 107, 109),
                ("aspirin", "0.3", 0.39, 103, 87),
                ("aspirin", "1", 0.55, 107, 76),
                ("aspirin", "3", 0.9, 127, 55),
            ]
        )

        self.assertEqual(reduced.height, 1)
        row = reduced.row(0, named=True)
        self.assertEqual(row["dose_um"], 3.0)
        self.assertEqual(row["morphology_score"], 0.9)
        self.assertEqual(row["infection_rate_pct"], 55)
        self.assertEqual(row["cell_count_pct"], 127)

    def test_a_tie_takes_the_lower_dose(self) -> None:
        """Equal best scores resolve to the lower dose, deterministically."""
        reduced = self._reduced([("aspirin", "10", 0.6, 90, 40), ("aspirin", "1", 0.6, 100, 50)])

        self.assertEqual(reduced["dose_um"].to_list(), [1.0])

    def test_a_duplicated_name_and_dose_gives_one_row(self) -> None:
        """Duplicated (name, dose) rows take part in the max and never add rows."""
        reduced = self._reduced(
            [("crizotinib-(S)", "1", 0.2, 100, 90), ("crizotinib-(S)", "1", 0.7, 98, 30)]
        )

        self.assertEqual(reduced.height, 1)
        self.assertEqual(reduced["morphology_score"].to_list(), [0.7])


class TreatedIdsTests(SimpleTestCase):
    """Treatment is read from pert_type, never from the shape of the id."""

    def test_treated_ids_follow_pert_type_not_the_cbcs_prefix(self) -> None:
        """A prefixless treated id is in; a CBCS-shaped id with only controls is out."""
        features = pl.DataFrame(
            {
                "cbkid": ["DO8167002", "DO8167002", "CBK281357", "CBK281357", "CBK100"],
                "pert_type": ["trt", "trt", "negcon", "non-inf", "trt"],
            }
        )

        self.assertEqual(sorted(treated_ids(features)), ["CBK100", "DO8167002"])


class BuildCompoundTableTests(TableS8Case):
    """Rows are the treated compounds; scores join by name, in a stated order."""

    def setUp(self) -> None:
        """Build a small S8 and index covering every join path."""
        super().setUp()
        self.reduced = reduce_to_compounds(
            load_table_s8(
                write_s8(
                    self.base / "s8.xlsx",
                    [
                        ("aspirin", "1", 0.8, 100, 20),
                        ("fluphenazine", "1", 0.4, 90, 70),
                        ("Triparanol", "1", 0.6, 95, 45),
                        ("toremifene", "1", 0.7, 99, 35),
                        ("DMSO", "1", 0.0, 100, 100),
                    ],
                )
            )
        )
        self.index = compound_index(
            [
                {"cbkid": "CBK1", "kind": "compound", "name": "Aspirin", "pert_iname": "aspirin"},
                {"cbkid": "CBK2", "kind": "compound", "pert_iname": "Fluphenazine"},
                {"cbkid": "CBK3", "kind": "compound", "name": "triparanol"},
                {"cbkid": "CBK4", "kind": "compound", "pert_iname": "toremifene"},
                {"cbkid": "CBK5", "kind": "compound", "pert_iname": "toremifene"},
                {"cbkid": "CBK6", "kind": "compound", "name": "unscreened"},
                {"cbkid": "DO8167002", "kind": "control", "pert_iname": "Nirmatrelvir"},
                {"cbkid": "CBK281357", "kind": "compound"},
            ]
        )
        treated = ["CBK1", "CBK2", "CBK3", "CBK4", "CBK5", "CBK6", "DO8167002"]
        self.table, self.report = build_compound_table(self.index, treated, self.reduced)

    def _row(self, cbkid: str) -> dict:
        return self.table.filter(pl.col("cbkid") == cbkid).row(0, named=True)

    def test_rows_are_exactly_the_treated_ids(self) -> None:
        """The control-only id is absent and the prefixless treated id is present."""
        cbkids = self.table["cbkid"].to_list()

        self.assertIn("DO8167002", cbkids)
        self.assertNotIn("CBK281357", cbkids)
        self.assertEqual(self.report["n_rows"], 7)

    def test_names_join_exact_then_case_folded_then_on_the_index_name(self) -> None:
        """Each fallback recovers its own compound."""
        self.assertEqual(self._row("CBK1")["morphology_score"], 0.8)
        self.assertEqual(self._row("CBK2")["morphology_score"], 0.4)
        self.assertEqual(self._row("CBK3")["morphology_score"], 0.6)

    def test_an_unscored_compound_keeps_its_row_with_null_scores(self) -> None:
        """A compound outside Table S8 is kept, with every score null."""
        row = self._row("CBK6")

        self.assertIsNone(row["morphology_score"])
        self.assertIsNone(row["infection_rate_pct"])
        self.assertIsNone(row["cell_count_pct"])
        self.assertIsNone(row["dose_um"])

    def test_the_report_counts_scores_and_names_unmatched_and_shared_names(self) -> None:
        """Unmatched S8 names and names used by two rows are reported, not raised."""
        self.assertEqual(self.report["n_scored"], 5)
        self.assertEqual(self.report["unmatched_names"], ["DMSO"])
        self.assertEqual(self.report["shared_names"], ["toremifene"])
        self.assertEqual(self._row("CBK5")["morphology_score"], 0.7)


class SelectRowsTests(SimpleTestCase):
    """One selection serves the view and the export."""

    def setUp(self) -> None:
        """Build a four-row table with one unscored compound."""
        self.frame = pl.DataFrame(
            {
                "cbkid": ["CBK1", "CBK2", "CBK3", "CBK4"],
                "name": ["alpha", "beta", "gamma", "delta"],
                "broad_moa": ["kinase inhibitor", None, "kinase inhibitor", None],
                "broad_target": [None, None, None, None],
                "morphology_score": [0.9, 0.5, 0.2, None],
                "infection_rate_pct": [20.0, 50.0, 90.0, None],
                "cell_count_pct": [100.0, 95.0, 30.0, None],
                "dose_um": [1.0, 3.0, 10.0, None],
            },
            schema_overrides={"broad_moa": pl.String, "broad_target": pl.String},
        )

    def _cbkids(self, params: dict) -> list[str]:
        return select_rows(self.frame, params)["cbkid"].to_list()

    def test_each_range_filter_narrows_and_the_two_compose(self) -> None:
        """Morphology and infection ranges each narrow; together they intersect."""
        self.assertEqual(sorted(self._cbkids({"morph_min": "0.4"})), ["CBK1", "CBK2"])
        self.assertEqual(sorted(self._cbkids({"inf_max": "60"})), ["CBK1", "CBK2"])
        self.assertEqual(self._cbkids({"morph_min": "0.4", "inf_max": "30"}), ["CBK1"])

    def test_the_preset_is_morphology_above_the_threshold_exclusive(self) -> None:
        """0.5 itself is not a hit: Table S8 prints '>0.5'."""
        self.assertEqual(HIT_THRESHOLD, 0.5)
        self.assertEqual(self._cbkids({"hits": "1"}), ["CBK1"])

    def test_a_non_numeric_bound_is_ignored(self) -> None:
        """A malformed bound filters nothing rather than failing the page."""
        self.assertEqual(len(self._cbkids({"morph_min": "abc"})), 4)

    def test_unscored_rows_sort_last_in_both_directions(self) -> None:
        """Sorting never puts a 'not reported' row first."""
        self.assertEqual(self._cbkids({"sort": "-morphology_score"})[-1], "CBK4")
        self.assertEqual(self._cbkids({"sort": "morphology_score"})[-1], "CBK4")
        self.assertEqual(self._cbkids({"sort": "morphology_score"})[0], "CBK3")

    def test_search_uses_the_shared_tables_semantics_on_the_display_cells(self) -> None:
        """A case-insensitive substring over rendered cells, composed with the ranges."""
        self.assertEqual(sorted(self._cbkids({"search": "KINASE"})), ["CBK1", "CBK3"])
        self.assertEqual(self._cbkids({"search": "kinase", "morph_min": "0.4"}), ["CBK1"])
        self.assertEqual(self._cbkids({"search": "not reported"}), ["CBK4"])


class TableRowsTests(SimpleTestCase):
    """Display cells: a missing score reads 'not reported', never zero."""

    def test_missing_scores_render_not_reported_and_never_zero(self) -> None:
        """Every score cell of an unscored row says so in words."""
        frame = pl.DataFrame(
            {
                "cbkid": ["CBK4"],
                "name": [None],
                "broad_moa": [None],
                "broad_target": [None],
                "morphology_score": [None],
                "infection_rate_pct": [None],
                "cell_count_pct": [None],
                "dose_um": [None],
            },
            schema=dict.fromkeys(["cbkid", "name", "broad_moa", "broad_target"], pl.String)
            | dict.fromkeys(
                ["morphology_score", "infection_rate_pct", "cell_count_pct", "dose_um"],
                pl.Float64,
            ),
        )

        row = table_rows(frame)[0]

        self.assertEqual(len(row), len(TABLE_HEADERS))
        self.assertEqual(row[-4:], [NOT_REPORTED] * 4)
        self.assertNotIn("0", row)


def page_table(n_rows: int = 30) -> pl.DataFrame:
    """Build a compound table as precompute writes it: scores descend, the last row unscored."""
    scores = [round(1 - index / n_rows, 3) for index in range(n_rows - 1)] + [None]
    return pl.DataFrame(
        {
            "cbkid": [f"CBK{index:03d}" for index in range(n_rows)],
            "name": [f"compound {index}" for index in range(n_rows)],
            "broad_moa": ["kinase inhibitor" if index % 2 else "other" for index in range(n_rows)],
            "broad_target": [None] * n_rows,
            "morphology_score": scores,
            "infection_rate_pct": [None if s is None else 100 * (1 - s) for s in scores],
            "cell_count_pct": [None if s is None else 100.0 for s in scores],
            "dose_um": [None if s is None else 1.0 for s in scores],
        },
        schema_overrides={"broad_target": pl.String},
    )


class TestDrrCompoundTablePage(DrrDownloadRouteTestCase):
    """The table on the page, its htmx route and its filtered export."""

    def write_table(self) -> pl.DataFrame:
        """Write the table artefact and return it."""
        frame = page_table()
        frame.write_parquet(self.artefacts / "table.parquet")
        return frame

    def htmx(self, query: str) -> object:
        """GET the table route as htmx does."""
        return self.client.get(self.page.url + "table/?" + query, HTTP_HX_REQUEST="true")

    @staticmethod
    def total(response: object) -> int:
        """Read the shared partial's 'of N entries' count."""
        return int(re.search(r"of (\d+) entries", response.content.decode()).group(1))

    def test_no_artefact_means_no_section_and_a_404_route(self) -> None:
        """Without table.parquet the page shows no table and the routes do not serve."""
        page = self.client.get(self.page.url)

        self.assertNotContains(page, "drr-compound-table-heading")
        self.assertEqual(self.client.get(self.page.url + "table/").status_code, 404)
        self.assertEqual(self.download("download/filtered/csv/").status_code, 404)

    def test_the_page_states_what_is_missing_and_why(self) -> None:
        """Criterion 3: the absent scores are explained in words, with the source."""
        self.write_table()

        page = self.client.get(self.page.url)

        self.assertContains(page, "was not run on this cell line")
        self.assertContains(page, "phospholipidosis is deferred")
        self.assertContains(page, "iScience")
        self.assertContains(page, "Vero E6")

    def test_the_swap_targets_exist_and_no_control_targets_the_form(self) -> None:
        """Pagination and controls swap into the content container, never the form."""
        self.write_table()

        html = self.client.get(self.page.url).content.decode()

        self.assertIn('id="data-table-drr-compounds-content"', html)
        self.assertIn('id="data-table-drr-compounds-loading"', html)
        self.assertIn('id="data-table-drr-compounds-controls"', html)
        self.assertNotIn('hx-target="#data-table-drr-compounds-controls"', html)

    def test_an_unscored_compound_reads_not_reported(self) -> None:
        """The unscored row renders the words, not a zero."""
        self.write_table()

        response = self.htmx("search=CBK029")

        self.assertContains(response, NOT_REPORTED)
        self.assertEqual(self.total(response), 1)

    def test_htmx_gets_the_content_partial_and_a_plain_get_the_page(self) -> None:
        """The route answers each kind of request with the right template."""
        self.write_table()

        partial = self.htmx("")
        full = self.client.get(self.page.url + "table/")

        self.assertNotContains(partial, "<html")
        self.assertContains(partial, "<table")
        self.assertContains(full, "<html")
        self.assertContains(full, "drr-compound-table-heading")

    def test_pagination_and_sort_survive_an_active_filter(self) -> None:
        """Page two of a filtered, sorted selection is still filtered and sorted."""
        self.write_table()

        first = self.htmx("morph_min=0.02&sort=morphology_score&per_page=25")
        second = self.htmx("morph_min=0.02&sort=morphology_score&per_page=25&page=2")

        self.assertEqual(self.total(first), self.total(second))
        self.assertContains(first, "CBK028")
        self.assertNotContains(second, "CBK028")
        self.assertNotContains(second, NOT_REPORTED)

    def test_the_export_carries_exactly_the_rows_the_table_counts(self) -> None:
        """Search plus a range filter: the CSV row count equals the table's total."""
        self.write_table()
        query = "search=kinase&morph_min=0.5"

        total = self.total(self.htmx(query))
        csv = self.download("download/filtered/csv/?" + query)

        self.assertEqual(
            csv["Content-Disposition"], 'attachment; filename="compounds-filtered.csv"'
        )
        exported = pl.read_csv(csv.content)
        self.assertEqual(exported.height, total)
        self.assertTrue(exported["broad_moa"].str.contains("kinase").all())

    def test_search_alone_narrows_the_export_too(self) -> None:
        """A search that removes a row removes it from the file as well."""
        self.write_table()

        exported = pl.read_csv(self.download("download/filtered/csv/?search=compound 1").content)

        self.assertEqual(exported.height, self.total(self.htmx("search=compound 1")))
        self.assertLess(exported.height, page_table().height)
