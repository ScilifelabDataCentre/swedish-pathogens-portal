"""Tests for RECOVAC zip source validation."""

from __future__ import annotations

import io
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from wagtail.admin.panels import ObjectList

from cms.snippets.dashboard_data import DashboardData, DashboardDataForm
from dashboard_visualisation.recovac import (
    REQUIRED_ZIP_STEMS,
    generate_figures,
    validate_source_file,
)
from dashboard_visualisation.registry import (
    validate_source_file as registry_validate_source_file,
)

_MINIMAL_TABLE_CSV = "wk,vacc1,vacc2,vacc3,vacc4,vacc5,vacc6\n2021w03,0.1,0.05,0,0,0,0\n"


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
            archive.writestr(f"{stem}{extension}", _MINIMAL_TABLE_CSV)
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


class TestsGenerateFiguresStub(SimpleTestCase):
    """Tests for the commit-1 generate_figures placeholder."""

    def test_returns_empty_dict(self) -> None:
        """Return no figures until plot builders land."""
        source = io.BytesIO(build_recovac_zip())
        self.assertEqual(generate_figures(source), {})


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
