"""Tests for EBI index envelope settings and catalogue builder."""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from wagtail.models import Page, Site
from wagtail.test.utils import WagtailPageTestCase

from cms.pages.dashboard import DashboardEbiPathogen, DashboardPage
from cms.pages.dashboard_index import DashboardIndexPage
from cms.pages.home import HomePage
from cms.services.ebi_index import build_index
from cms.settings.ebi_index import (
    DEFAULT_CATALOGUE_NAME,
    DEFAULT_RELEASE,
    DEFAULT_RELEASE_DATE,
    EbiIndexSettings,
)
from cms.tests.utils import create_test_image


class EbiIndexSettingsTestCase(TestCase):
    """Envelope form on Wagtail Settings; no computed JSON fields."""

    def test_defaults(self) -> None:
        """Name, release, and date are prefilled; GitHub URL is empty."""
        settings = EbiIndexSettings.load()
        self.assertEqual(settings.name, DEFAULT_CATALOGUE_NAME)
        self.assertEqual(settings.release, DEFAULT_RELEASE)
        self.assertEqual(settings.release_date, DEFAULT_RELEASE_DATE)
        self.assertEqual(settings.github_releases_latest_url, "")

    def test_github_url_is_optional(self) -> None:
        """Editors may leave the GitHub latest-release URL blank."""
        field = EbiIndexSettings._meta.get_field("github_releases_latest_url")
        self.assertTrue(field.blank)

    def test_does_not_store_entry_count_or_entries(self) -> None:
        """entry_count and entries are computed later, not settings fields."""
        field_names = {field.name for field in EbiIndexSettings._meta.get_fields()}
        self.assertNotIn("entry_count", field_names)
        self.assertNotIn("entries", field_names)

    def test_admin_heading_is_ebi_index(self) -> None:
        """Settings form uses the EBI index heading."""
        self.assertEqual(EbiIndexSettings._meta.verbose_name, "EBI index")
        headings = [getattr(panel, "heading", None) for panel in EbiIndexSettings.panels]
        self.assertIn("EBI index", headings)


def _entry_fields(entry: dict[str, object]) -> list[dict[str, str]]:
    """Return the `fields` list from one catalogue entry."""
    fields = entry["fields"]
    if not isinstance(fields, list):
        return []
    return fields


def _field_values(entry: dict[str, object], name: str) -> list[str]:
    """Return all `value`s for a field name in one catalogue entry."""
    return [item["value"] for item in _entry_fields(entry) if item["name"] == name]


def _field_names(entry: dict[str, object]) -> list[str]:
    """Return field names in order for one catalogue entry."""
    return [item["name"] for item in _entry_fields(entry)]


class EbiIndexBuilderTestCase(WagtailPageTestCase):
    """`build_index()` from settings plus live dashboards with EBI fields."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a site tree for catalogue builder tests."""
        root = Page.get_first_root_node()
        for child in root.get_children():
            child.delete()
        root = Page.get_first_root_node()

        cls.home = HomePage(title="Home", slug="home")
        root.add_child(instance=cls.home)
        Site.objects.update_or_create(
            is_default_site=True,
            defaults={"hostname": "testserver", "root_page": cls.home},
        )

        cls.index = DashboardIndexPage(title="Dashboards", slug="dashboards")
        cls.home.add_child(instance=cls.index)
        cls.index.save_revision().publish()
        cls.image = create_test_image(title="EBI builder image", file_name="ebi-builder.jpg")

    def _add_dashboard(
        self,
        *,
        title: str,
        slug: str,
        description: str = "Card blurb",
        publish: bool = True,
        **kwargs: object,
    ) -> DashboardPage:
        """Create a dashboard under the index."""
        page = DashboardPage(
            title=title,
            slug=slug,
            description=description,
            image=self.image,
            data_status="active",
            **kwargs,
        )
        self.index.add_child(instance=page)
        if publish:
            page.save_revision().publish()
        else:
            page.unpublish()
        return page

    def test_two_pages_get_sequential_ids_newest_first(self) -> None:
        """Filled EBI panels are included; blank panels are not; ids follow date order."""
        older = self._add_dashboard(
            title="Older",
            slug="older",
            ebi_data_type="Serology",
            ebi_data_source="Facility A",
        )
        newer = self._add_dashboard(
            title="Newer",
            slug="newer",
            ebi_data_type="Wastewater",
            ebi_data_source="Facility B",
        )
        self._add_dashboard(title="Blank EBI", slug="blank-ebi")

        now = timezone.now()
        older.first_published_at = now - timedelta(days=5)
        older.save()
        newer.first_published_at = now - timedelta(days=1)
        newer.save()

        DashboardEbiPathogen.objects.create(page=newer, ebi_type_of_pathogen="SARS-CoV-2")

        payload = build_index()
        self.assertEqual(payload["name"], DEFAULT_CATALOGUE_NAME)
        self.assertEqual(payload["release"], DEFAULT_RELEASE)
        self.assertEqual(payload["release_date"], DEFAULT_RELEASE_DATE)
        self.assertEqual(payload["entry_count"], 2)

        first, second = payload["entries"]
        self.assertEqual(_field_values(first, "id"), ["dataset1"])
        self.assertEqual(_field_values(first, "name"), ["Newer"])
        self.assertEqual(_field_values(first, "data_type"), ["Wastewater"])
        self.assertEqual(_field_values(first, "type_of_pathogen"), ["SARS-CoV-2"])
        self.assertEqual(_field_values(first, "description"), ["Card blurb"])
        self.assertEqual(_field_values(first, "country"), ["Sweden"])
        self.assertEqual(_field_values(second, "id"), ["dataset2"])
        self.assertEqual(_field_values(second, "name"), ["Older"])
        self.assertIn("updated_date", _field_names(first))
        self.assertIn("/dashboards/newer/", _field_values(first, "source_page")[0])

    def test_unpublished_page_is_omitted(self) -> None:
        """Draft dashboards are not in the catalogue."""
        self._add_dashboard(
            title="Draft",
            slug="draft-ebi",
            publish=False,
            ebi_data_type="Serology",
        )
        payload = build_index()
        self.assertEqual(payload["entry_count"], 0)
        self.assertEqual(payload["entries"], [])

    def test_github_success_overrides_text_fields(self) -> None:
        """A successful GitHub latest-release fetch replaces release and date."""
        settings = EbiIndexSettings.load()
        settings.github_releases_latest_url = (
            "https://api.github.com/repos/example/portal/releases/latest"
        )
        settings.save()

        with patch(
            "cms.services.ebi_index.fetch_github_latest_release",
            return_value={"tag_name": "v9.9.9", "published_at": "2026-01-15T12:00:00Z"},
        ) as fetch:
            payload = build_index()

        fetch.assert_called_once()
        self.assertEqual(payload["release"], "v9.9.9")
        self.assertEqual(payload["release_date"], "2026-01-15")

    def test_github_failure_keeps_text_fields(self) -> None:
        """If GitHub fetch fails, envelope text fields are unchanged."""
        settings = EbiIndexSettings.load()
        settings.github_releases_latest_url = (
            "https://api.github.com/repos/example/portal/releases/latest"
        )
        settings.save()

        with patch(
            "cms.services.ebi_index.fetch_github_latest_release",
            return_value=None,
        ):
            payload = build_index()

        self.assertEqual(payload["release"], DEFAULT_RELEASE)
        self.assertEqual(payload["release_date"], DEFAULT_RELEASE_DATE)

    def test_empty_github_url_does_not_fetch(self) -> None:
        """No HTTP call when the GitHub URL is blank."""
        with patch("cms.services.ebi_index.fetch_github_latest_release") as fetch:
            build_index()
        fetch.assert_not_called()

    def test_payload_omits_private_and_methods_keys(self) -> None:
        """Catalogue JSON must not include methods or admin-only fields."""
        self._add_dashboard(
            title="Serology",
            slug="serology-for-keys",
            ebi_data_type="Serology",
        )
        payload = build_index()
        blob = str(payload)
        self.assertNotIn("methods", blob)
        self.assertNotIn("uploaded_by", blob)
        self.assertNotIn("research_group", blob)
        self.assertNotIn("methods", _field_names(payload["entries"][0]))


class EbiIndexEndpointTestCase(EbiIndexBuilderTestCase):
    """Anonymous GET `/ebi-index.json` next to `/healthz/`."""

    def test_anonymous_get_returns_catalogue_json(self) -> None:
        """Unauthenticated GET is 200 JSON matching `build_index()`."""
        self._add_dashboard(
            title="Serology",
            slug="serology-endpoint",
            ebi_data_type="Serology",
        )
        response = self.client.get("/ebi-index.json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"].split(";")[0], "application/json")
        self.assertEqual(response["Cache-Control"], "public, max-age=3600")
        self.assertEqual(response.json(), build_index())

    def test_head_is_allowed(self) -> None:
        """HEAD is allowed (crawlers)."""
        response = self.client.head("/ebi-index.json")
        self.assertEqual(response.status_code, 200)

    def test_unsafe_methods_return_405(self) -> None:
        """POST, PUT, PATCH, and DELETE are rejected."""
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)("/ebi-index.json")
                self.assertEqual(response.status_code, 405)
