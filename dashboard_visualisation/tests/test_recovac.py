"""Tests for RECOVAC zip source validation and subplot builders."""

from __future__ import annotations

import io
import zipfile
from typing import Any

import polars as pl
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from wagtail.admin.panels import ObjectList

from cms.snippets.dashboard_data import DashboardData, DashboardDataForm
from dashboard_visualisation.recovac import (
    REQUIRED_ZIP_STEMS,
    _group_visibility,
    _prep_coverage,
    _prep_week_dates,
    generate_figures,
    validate_source_file,
)
from dashboard_visualisation.registry import (
    generate_figures as registry_generate_figures,
)
from dashboard_visualisation.registry import (
    validate_source_file as registry_validate_source_file,
)

_MINIMAL_TABLE_CSV = "wk,vacc1,vacc2,vacc3,vacc4,vacc5,vacc6\n2021w03,0.1,0.05,0,0,0,0\n"
_COVERAGE_CSV = (
    "wk,vacc1,vacc2,vacc3,vacc4,vacc5,vacc6\n"
    "2019w52,0.01,0,0,0,0,0\n"
    "2021w03,0.8,0.5,0.2,0.1,0.05,0.01\n"
    "2021w04,0.85,0.55,0.25,0.12,0.06,0.02\n"
)
_ICU_CSV = (
    "wk,vacc0,vacc1,vacc2,vacc3,vacc4,vacc5,vacc6,c19_i1\n"
    "2019w52,1,0,0,0,0,0,0,1\n"
    "2021w03,10,5,3,2,1,0,0,21\n"
    "2021w04,8,4,3,2,1,1,0,19\n"
)
_CASES_CSV = (
    "wk,vacc0,vacc1,vacc2,vacc3,vacc4,vacc5,vacc6,c19_d2\n"
    "2019w52,1,0,0,0,0,0,0,1\n"
    "2021w03,10,5,3,2,1,0,0,21\n"
    "2021w04,8,4,3,2,1,1,0,19\n"
)


def _csv_for_stem(stem: str) -> str:
    """Return a synthetic table matching the workbook type for ``stem``."""
    if stem.startswith("iva_vacc_"):
        return _ICU_CSV
    if "_covid_vacc_" in stem:
        return _CASES_CSV
    return _COVERAGE_CSV


def build_recovac_zip(
    stems: tuple[str, ...] | None = None,
    *,
    extra: dict[str, str] | None = None,
    extension: str = ".csv",
) -> bytes:
    """Return a zip of synthetic RECOVAC tables (not real register data)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for stem in stems if stems is not None else REQUIRED_ZIP_STEMS:
            archive.writestr(f"{stem}{extension}", _csv_for_stem(stem))
        if extra:
            for name, content in extra.items():
                archive.writestr(name, content)
    return buffer.getvalue()


def _dashboard_data_form(
    *,
    slug: str,
    upload: SimpleUploadedFile,
    instance: DashboardData | None = None,
) -> DashboardDataForm:
    """Build a bound DashboardData admin form for upload validation tests."""
    form_class = ObjectList(DashboardData.panels).bind_to_model(DashboardData).get_form_class()
    data = {
        "dashboard_title": "RECOVAC",
        "dashboard_slug": slug,
        "data": "{}",
        "data_updated_at": "",
    }
    if instance is not None:
        data["dashboard_title"] = instance.dashboard_title
        data["dashboard_slug"] = instance.dashboard_slug
    return form_class(data, {"source_file": upload}, instance=instance)


class TestsValidateSourceFile(SimpleTestCase):
    """Tests for recovac.validate_source_file."""

    def test_valid_zip_of_csv_members_passes(self) -> None:
        """Accept a zip that contains all 14 required stems as CSV."""
        source = io.BytesIO(build_recovac_zip())
        source.name = "recovac-source.zip"
        self.assertIsNone(validate_source_file(source, filename="recovac-source.zip"))

    def test_rejects_non_zip_extension(self) -> None:
        """Reject a CSV upload for this dashboard."""
        source = io.BytesIO(_MINIMAL_TABLE_CSV.encode("utf-8"))
        error = validate_source_file(source, filename="data.csv")
        self.assertIsNotNone(error)
        self.assertIn(".zip", error)

    def test_rejects_invalid_zip_bytes(self) -> None:
        """Reject a .zip name that is not an archive."""
        source = io.BytesIO(b"not-a-zip")
        error = validate_source_file(source, filename="recovac-source.zip")
        self.assertIsNotNone(error)
        self.assertIn("not a valid zip", error)

    def test_missing_member_names_the_file(self) -> None:
        """Name the missing workbook when a required stem is absent."""
        stems = tuple(stem for stem in REQUIRED_ZIP_STEMS if stem != "iva_vacc_60plus")
        source = io.BytesIO(build_recovac_zip(stems))
        error = validate_source_file(source, filename="recovac-source.zip")
        self.assertIsNotNone(error)
        self.assertIn("iva_vacc_60plus.xlsx", error)
        self.assertIn("Missing required files", error)

    def test_empty_member_is_rejected(self) -> None:
        """Reject a required member that has no table content."""
        stems = tuple(stem for stem in REQUIRED_ZIP_STEMS if stem != "vacc_pop_18plus")
        payload = build_recovac_zip(
            stems,
            extra={"vacc_pop_18plus.csv": ""},
        )
        error = validate_source_file(io.BytesIO(payload), filename="recovac-source.zip")
        self.assertIsNotNone(error)
        self.assertIn("vacc_pop_18plus.csv", error)
        self.assertIn("empty", error)

    def test_header_only_csv_member_is_rejected(self) -> None:
        """Reject a CSV member that has no data rows."""
        stems = tuple(stem for stem in REQUIRED_ZIP_STEMS if stem != "vacc_pop_18plus")
        payload = build_recovac_zip(
            stems,
            extra={"vacc_pop_18plus.csv": "wk,vacc1\n"},
        )
        error = validate_source_file(io.BytesIO(payload), filename="recovac-source.zip")
        self.assertIsNotNone(error)
        self.assertIn("header", error)

    def test_accepts_members_in_data_subdirectory(self) -> None:
        """Accept the legacy data/ prefix used by the pandas scripts."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for stem in REQUIRED_ZIP_STEMS:
                archive.writestr(f"data/{stem}.csv", _MINIMAL_TABLE_CSV)
        error = validate_source_file(io.BytesIO(buffer.getvalue()), filename="recovac.zip")
        self.assertIsNone(error)

    def test_empty_zip_size_is_rejected(self) -> None:
        """Reject a zero-byte upload when size is provided."""
        error = validate_source_file(
            io.BytesIO(b""),
            filename="recovac-source.zip",
            size_bytes=0,
        )
        self.assertIsNotNone(error)
        self.assertIn("empty", error)


class TestsRegistryDispatch(SimpleTestCase):
    """Tests for registry.validate_source_file dispatch."""

    def test_recovac_slug_uses_custom_validator(self) -> None:
        """Handle recovac with the zip validator instead of CSV."""
        source = io.BytesIO(build_recovac_zip())
        handled, error = registry_validate_source_file(
            "recovac",
            source,
            filename="recovac-source.zip",
        )
        self.assertTrue(handled)
        self.assertIsNone(error)

    def test_serology_slug_falls_back_to_csv(self) -> None:
        """Leave CSV-only dashboards on the generic path."""
        handled, error = registry_validate_source_file(
            "serology-statistics",
            io.BytesIO(b"week,class,count\n2024-01-01,positive,1\n"),
            filename="data.csv",
        )
        self.assertFalse(handled)
        self.assertIsNone(error)

    def test_unregistered_slug_falls_back_to_csv(self) -> None:
        """Leave unknown slugs on the generic CSV path."""
        handled, error = registry_validate_source_file(
            "not-a-dashboard",
            io.BytesIO(b"a,b\n1,2\n"),
            filename="data.csv",
        )
        self.assertFalse(handled)
        self.assertIsNone(error)


def _group_button_visible(fig_json: dict[str, Any], button_index: int) -> list[bool]:
    """Return the ``visible`` mask on a group-filter button."""
    buttons = fig_json["layout"]["updatemenus"][0]["buttons"]
    return list(buttons[button_index]["args"][0]["visible"])


class TestsPrepHelpers(SimpleTestCase):
    """Tests for week parsing and coverage de-cumulation."""

    def test_iso_week_becomes_monday_and_drops_2019(self) -> None:
        """Map ``2021w03`` to Monday 2021-01-18 and drop 2019 rows."""
        frame = _prep_week_dates(pl.DataFrame({"wk": ["2019w52", "2021w03"]}))
        self.assertEqual(frame.get_column("date").to_list(), ["2021-01-18"])

    def test_decumulate_coverage_shares(self) -> None:
        """Turn cumulative 0–1 shares into exclusive dose-level percents."""
        frame = _prep_coverage(
            pl.DataFrame(
                {
                    "wk": ["2021w03"],
                    "vacc1": [0.8],
                    "vacc2": [0.5],
                    "vacc3": [0.2],
                    "vacc4": [0.1],
                    "vacc5": [0.05],
                    "vacc6": [0.01],
                }
            )
        )
        row = frame.row(0, named=True)
        self.assertAlmostEqual(row["no_dose"], 20.0)
        self.assertAlmostEqual(row["one_dose"], 30.0)
        self.assertAlmostEqual(row["two_dose"], 30.0)
        self.assertAlmostEqual(row["six_dose"], 1.0)


class TestsGroupVisibility(SimpleTestCase):
    """Tests for full-length subplot visibility masks."""

    def test_mask_length_covers_both_panels(self) -> None:
        """Swedish-pop mask is 42 flags (3 groups × 7 traces × 2 panels)."""
        mask = _group_visibility(3, 0)
        self.assertEqual(len(mask), 42)
        self.assertEqual(mask[:7], [True] * 7)
        self.assertEqual(mask[21:28], [True] * 7)

    def test_second_group_enables_both_panels(self) -> None:
        """Age/comorbidity index 1 turns on top and bottom traces together."""
        mask = _group_visibility(3, 1)
        self.assertEqual(mask[7:14], [True] * 7)
        self.assertEqual(mask[28:35], [True] * 7)
        self.assertFalse(any(mask[:7]))
        self.assertFalse(any(mask[21:28]))


class TestsGenerateFigures(SimpleTestCase):
    """Tests for RECOVAC subplot builders from the fixture zip."""

    def test_returns_both_figure_ids(self) -> None:
        """Build swedishpop and comorbidity figures from the synthetic zip."""
        figures = generate_figures(io.BytesIO(build_recovac_zip()))
        self.assertEqual(set(figures), {"swedishpop_subplot", "comorbidity_subplot"})
        for figure_id, payload in figures.items():
            with self.subTest(figure_id=figure_id):
                self.assertIn("data", payload)
                self.assertIn("layout", payload)

    def test_swedishpop_buttons_match_trace_count(self) -> None:
        """Age buttons include a visible flag for every trace (both panels)."""
        figures = generate_figures(io.BytesIO(build_recovac_zip()))
        swedish = figures["swedishpop_subplot"]
        n_traces = len(swedish["data"])
        self.assertEqual(n_traces, 42)
        for index in range(3):
            visible = _group_button_visible(swedish, index)
            self.assertEqual(len(visible), n_traces)

    def test_comorbidity_buttons_match_trace_count(self) -> None:
        """Comorbidity buttons include a visible flag for every trace."""
        figures = generate_figures(io.BytesIO(build_recovac_zip()))
        comorbidity = figures["comorbidity_subplot"]
        n_traces = len(comorbidity["data"])
        self.assertEqual(n_traces, 56)
        for index in range(4):
            visible = _group_button_visible(comorbidity, index)
            self.assertEqual(len(visible), n_traces)

    def test_diabetes_button_shows_both_panels(self) -> None:
        """Diabetes (index 1) unhides coverage and case traces together."""
        figures = generate_figures(io.BytesIO(build_recovac_zip()))
        visible = _group_button_visible(figures["comorbidity_subplot"], 1)
        self.assertTrue(all(visible[7:14]))
        self.assertTrue(all(visible[35:42]))
        self.assertFalse(any(visible[:7]))
        self.assertFalse(any(visible[28:35]))

    def test_registry_dispatches_recovac_figures(self) -> None:
        """Registry generate_figures returns the same two figure ids."""
        source = io.BytesIO(build_recovac_zip())
        figures = registry_generate_figures("recovac", source)
        self.assertEqual(set(figures), {"swedishpop_subplot", "comorbidity_subplot"})

    def test_accessibility_layout(self) -> None:
        """Subplots are taller, titled, with legend, spike hover, and units."""
        figures = generate_figures(io.BytesIO(build_recovac_zip()))
        swedish = figures["swedishpop_subplot"]
        layout = swedish["layout"]
        self.assertEqual(layout["height"], 1100)
        self.assertTrue(layout["showlegend"])
        self.assertEqual(layout["hovermode"], "x unified")
        self.assertEqual(layout["spikedistance"], -1)
        titles = [ann.get("text") for ann in layout.get("annotations", [])]
        self.assertIn("Vaccine coverage (%)", titles)
        self.assertIn("ICU admissions (count)", titles)
        self.assertIn("%", layout["yaxis"]["title"]["text"])
        self.assertIn("number of people", layout["yaxis2"]["title"]["text"])
        timeframe = [btn["label"] for btn in layout["updatemenus"][1]["buttons"]]
        self.assertEqual(timeframe, ["Select full timeline", "Align both plots"])

    def test_coverage_and_count_hover_templates(self) -> None:
        """Coverage hover uses percent; every count bar includes the week total."""
        swedish = generate_figures(io.BytesIO(build_recovac_zip()))["swedishpop_subplot"]
        area = swedish["data"][0]
        self.assertIn("%", area["hovertemplate"])
        self.assertIn(".1f", area["hovertemplate"])
        for trace in swedish["data"][21:]:
            with self.subTest(name=trace["name"]):
                self.assertIn("customdata", trace)
                self.assertIn("week total", trace["hovertemplate"])

    def test_comorbidity_buttons_use_full_names(self) -> None:
        """Comorbidity filters spell out the condition, not CVD/RD."""
        comorbidity = generate_figures(io.BytesIO(build_recovac_zip()))["comorbidity_subplot"]
        labels = [btn["label"] for btn in comorbidity["layout"]["updatemenus"][0]["buttons"]]
        self.assertEqual(
            labels,
            [
                "Cardiovascular disease",
                "Diabetes",
                "Respiratory disease",
                "Cancer",
            ],
        )

    def test_two_dose_colour_is_not_legacy_yellow(self) -> None:
        """Replace the low-contrast yellow used for two-dose traces."""
        swedish = generate_figures(io.BytesIO(build_recovac_zip()))["swedishpop_subplot"]
        two_dose = next(trace for trace in swedish["data"] if trace["name"] == "Two Doses")
        color = two_dose["line"]["color"]
        self.assertNotIn("235,235,0", color.replace(" ", ""))
        self.assertNotEqual(color, "rgb(235, 235, 0)")


class TestsDashboardDataSaveRecovac(TestCase):
    """Saving a recovac DashboardData row populates both figure ids."""

    def test_save_stores_both_figure_ids(self) -> None:
        """Generate both subplot JSON blobs when the zip is first saved."""
        row = DashboardData.objects.create(
            dashboard_title="RECOVAC",
            dashboard_slug="recovac",
            source_file=SimpleUploadedFile(
                "recovac-source.zip",
                build_recovac_zip(),
                "application/zip",
            ),
        )
        self.assertEqual(set(row.data), {"swedishpop_subplot", "comorbidity_subplot"})


class TestsDashboardDataFormRecovac(TestCase):
    """Admin form tests for RECOVAC zip vs CSV-only dashboards."""

    def test_accepts_recovac_zip_upload(self) -> None:
        """Accept a valid recovac zip through DashboardDataForm."""
        upload = SimpleUploadedFile(
            "recovac-source.zip",
            build_recovac_zip(),
            "application/zip",
        )
        form = _dashboard_data_form(slug="recovac", upload=upload)
        self.assertTrue(form.is_valid(), form.errors)

    def test_rejects_recovac_zip_missing_member(self) -> None:
        """Surface the missing filename on the source_file field."""
        upload = SimpleUploadedFile(
            "recovac-source.zip",
            build_recovac_zip(
                tuple(stem for stem in REQUIRED_ZIP_STEMS if stem != "iva_vacc_60plus")
            ),
            "application/zip",
        )
        form = _dashboard_data_form(slug="recovac", upload=upload)
        self.assertFalse(form.is_valid())
        self.assertIn("iva_vacc_60plus.xlsx", str(form.errors["source_file"]))

    def test_rejects_xlsx_on_recovac_slug(self) -> None:
        """Keep the shared spreadsheet blocklist even for recovac."""
        upload = SimpleUploadedFile(
            "vacc_pop_18plus.xlsx",
            b"not-a-real-xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        form = _dashboard_data_form(slug="recovac", upload=upload)
        self.assertFalse(form.is_valid())
        self.assertIn("Export", str(form.errors["source_file"]))

    def test_rejects_zip_on_serology_slug(self) -> None:
        """CSV-only dashboards still reject a zip via generic CSV validation."""
        upload = SimpleUploadedFile(
            "recovac-source.zip",
            build_recovac_zip(),
            "application/zip",
        )
        form = _dashboard_data_form(slug="serology-statistics", upload=upload)
        self.assertFalse(form.is_valid())
        self.assertIn("source_file", form.errors)
