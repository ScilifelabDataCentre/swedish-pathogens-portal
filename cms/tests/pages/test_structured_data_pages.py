"""End-to-end tests for the JSON-LD emitted into every page's head.

Every assertion runs against the JSON parsed out of a real rendered response,
rather than against substrings, so a payload that renders but does not parse
fails here. The dispatch logic itself is unit tested in
``cms/tests/templatetags/test_structured_data.py``.
"""

from __future__ import annotations

import json
import re
import tempfile
from unittest.mock import patch
from urllib.parse import urlsplit

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import override_settings
from wagtail.models import Page, Site
from wagtail.test.utils import WagtailPageTestCase

from cms.pages import (
    BasicPage,
    DashboardIndexPage,
    HighlightsAndEditorialsIndexPage,
    HighlightsAndEditorialsPage,
    HomePage,
    NewsIndexPage,
    NewsPage,
    SLUDashboardPage,
    SLUDashboardSubPage,
)
from cms.pages.dashboard import DashboardPage
from cms.snippets.dashboard_data import DashboardData
from cms.templatetags.structured_data import SLU_DATASET_DOI_URL
from cms.tests.utils import create_test_image

_SCRIPT_PATTERN = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL)

# An offset-bearing ISO 8601 instant, e.g. 2026-10-06T12:00:00+00:00.
_ISO_WITH_OFFSET = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+(?:[+-]\d{2}:\d{2}|Z)$")

_XSS_TITLE = "</script><script>alert(1)</script>"


class StructuredDataPageTestCase(WagtailPageTestCase):
    """Publishes one page of every type that gets its own ``@type``.

    ``MEDIA_ROOT`` is redirected for the whole class because the image
    renditions and the uploaded dashboard file are both written on first render,
    and ``setUpTestData`` creates the originals before any test method runs.
    """

    @classmethod
    def setUpClass(cls) -> None:
        """Redirect ``MEDIA_ROOT`` before the class fixtures create any file."""
        media_root = tempfile.TemporaryDirectory()
        cls.addClassCleanup(media_root.cleanup)
        media_override = override_settings(MEDIA_ROOT=media_root.name)
        media_override.enable()
        cls.addClassCleanup(media_override.disable)

        super().setUpClass()

    @classmethod
    def setUpTestData(cls) -> None:
        """Build the full page tree used by every test in this module."""
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

        cls.image = create_test_image(title="Card image", file_name="card.jpg")

        cls.dashboard_index = DashboardIndexPage(title="Dashboards", slug="dashboards")
        cls.home.add_child(instance=cls.dashboard_index)
        cls.dashboard_index.save_revision().publish()

        cls.dashboard = DashboardPage(
            title="Serology statistics",
            slug="serology-statistics",
            description="Aggregated serology test results from Swedish laboratories.",
            image=cls.image,
            data_status="active",
            keywords="serology, sars-cov-2",
        )
        cls.dashboard_index.add_child(instance=cls.dashboard)
        cls.dashboard.save_revision().publish()

        cls.dashboard_without_data = DashboardPage(
            title="Retired dashboard",
            slug="retired-dashboard",
            description="A dashboard whose data has never been uploaded.",
            image=cls.image,
            data_status="historic",
        )
        cls.dashboard_index.add_child(instance=cls.dashboard_without_data)
        cls.dashboard_without_data.save_revision().publish()

        cls.slu = SLUDashboardPage(
            title="SLU wastewater",
            slug="slu-wastewater",
            description="Respiratory viruses measured in Swedish wastewater.",
            image=cls.image,
            data_status="active",
        )
        cls.dashboard_index.add_child(instance=cls.slu)
        cls.slu.save_revision().publish()

        # Uploading a file triggers the slug's registered figure generator, which
        # rejects a stand-in CSV. These tests describe the file, not the figures,
        # so generation is stubbed rather than fed real dashboard data.
        with patch("dashboard_visualisation.generate_figures", return_value={}):
            for slug in ("serology-statistics", "slu-wastewater"):
                DashboardData.objects.create(
                    dashboard_slug=slug,
                    source_file=SimpleUploadedFile(f"{slug}.csv", b"a,b\n1,2\n", "text/csv"),
                )

        cls.slu_subpage = SLUDashboardSubPage(title="Influenza A", slug="influenza-a")
        cls.slu.add_child(instance=cls.slu_subpage)
        cls.slu_subpage.save_revision().publish()

        cls.highlights_index = HighlightsAndEditorialsIndexPage(
            title="Highlights and editorials", slug="highlights"
        )
        cls.home.add_child(instance=cls.highlights_index)
        cls.highlights_index.save_revision().publish()

        cls.editorial = HighlightsAndEditorialsPage(
            title="Preparing for the next pandemic",
            slug="next-pandemic",
            description="An editorial on Swedish pandemic preparedness.",
            image=cls.image,
            article_type="editorial",
            author="Anna Andersson",
            keywords="preparedness, policy",
        )
        cls.highlights_index.add_child(instance=cls.editorial)
        cls.editorial.save_revision().publish()

        cls.data_highlight = HighlightsAndEditorialsPage(
            title="New sequencing dataset released",
            slug="sequencing-dataset",
            description="A data highlight describing a dataset held at NCBI.",
            image=cls.image,
            article_type="data-highlight",
            author="Bertil Bergman",
        )
        cls.highlights_index.add_child(instance=cls.data_highlight)
        cls.data_highlight.save_revision().publish()

        cls.news_index = NewsIndexPage(title="News", slug="news")
        cls.home.add_child(instance=cls.news_index)
        cls.news_index.save_revision().publish()

        cls.news = NewsPage(
            title="Portal adds a new dashboard",
            slug="new-dashboard",
            description="The portal has published a new wastewater dashboard.",
            image=cls.image,
            image_caption="Caption for the new dashboard article.",
        )
        cls.news_index.add_child(instance=cls.news)
        cls.news.save_revision().publish()

        cls.basic = BasicPage(title="About the portal", slug="about")
        cls.home.add_child(instance=cls.basic)
        cls.basic.save_revision().publish()

        cls.xss_page = BasicPage(title=_XSS_TITLE, slug="escaping")
        cls.home.add_child(instance=cls.xss_page)
        cls.xss_page.save_revision().publish()

    def scripts(self, response: HttpResponse) -> list[str]:
        """Return the raw contents of every JSON-LD script element in a response."""
        return _SCRIPT_PATTERN.findall(response.content.decode())

    def payload(self, page: Page) -> dict:
        """Fetch a page and return its sole JSON-LD payload, parsed.

        Args:
            page: The page to request.

        Returns:
            dict: The parsed payload.
        """
        response = self.client.get(page.url)
        self.assertEqual(response.status_code, 200)

        scripts = self.scripts(response)
        self.assertEqual(len(scripts), 1, "expected exactly one JSON-LD script element")

        return json.loads(scripts[0])


class EveryPageCarriesOnePayloadTest(StructuredDataPageTestCase):
    """Criterion 1: one parseable, correctly contextualised payload per page."""

    def test_every_page_type_emits_exactly_one_contextualised_payload(self):
        """Each page type renders one script whose JSON declares the schema.org context."""
        for page in (
            self.home,
            self.dashboard_index,
            self.dashboard,
            self.dashboard_without_data,
            self.slu,
            self.slu_subpage,
            self.highlights_index,
            self.editorial,
            self.data_highlight,
            self.news_index,
            self.news,
            self.basic,
        ):
            with self.subTest(page=page.title):
                payload = self.payload(page)
                self.assertEqual(payload["@context"], "https://schema.org")
                self.assertIn("@type", payload)


class HomePagePayloadTest(StructuredDataPageTestCase):
    """Criterion 2: the homepage describes the site and its organisation."""

    def test_home_page_emits_website_with_names_and_url(self):
        """The homepage is the ``WebSite``, named after ``WAGTAIL_SITE_NAME``."""
        payload = self.payload(self.home)

        self.assertEqual(payload["@type"], "WebSite")
        self.assertEqual(payload["name"], settings.WAGTAIL_SITE_NAME)
        self.assertEqual(payload["alternateName"], f"The {settings.WAGTAIL_SITE_NAME}")
        self.assertEqual(payload["url"], "http://testserver")

    def test_home_page_website_name_follows_the_site_record(self):
        """An editor-set site name is used in place of the fallback, in both names."""
        Site.objects.filter(is_default_site=True).update(site_name="Pathogens Portal")

        payload = self.payload(self.home)

        self.assertEqual(payload["name"], "Pathogens Portal")
        self.assertEqual(payload["alternateName"], "The Pathogens Portal")

    def test_home_page_names_the_organization(self):
        """The Organization carries its name, URL and social profiles."""
        organization = self.payload(self.home)["publisher"]

        self.assertEqual(organization["@type"], "Organization")
        self.assertEqual(organization["name"], "SciLifeLab Data Centre")
        self.assertEqual(organization["url"], "https://www.scilifelab.se/")
        self.assertEqual(
            organization["sameAs"],
            [
                "https://x.com/scilifelab_DC",
                "https://www.linkedin.com/company/scilifelab-data-centre/",
                "https://github.com/ScilifelabDataCentre",
            ],
        )


class ArticlePayloadTest(StructuredDataPageTestCase):
    """Criterion 3: highlights and editorials are Articles."""

    def test_editorial_emits_article_with_dates_keywords_and_publisher(self):
        """An editorial carries the full Article shape."""
        payload = self.payload(self.editorial)

        self.assertEqual(payload["@type"], "Article")
        self.assertEqual(payload["headline"], "Preparing for the next pandemic")
        self.assertEqual(payload["description"], "An editorial on Swedish pandemic preparedness.")
        self.assertEqual(payload["keywords"], ["preparedness", "policy"])
        self.assertEqual(payload["publisher"]["name"], "SciLifeLab Data Centre")
        self.assertTrue(payload["image"].startswith("http://testserver/"))

    def test_article_dates_are_iso_8601_with_an_offset(self):
        """``datePublished`` and ``dateModified`` are unambiguous instants."""
        payload = self.payload(self.editorial)

        self.assertRegex(payload["datePublished"], _ISO_WITH_OFFSET)
        self.assertRegex(payload["dateModified"], _ISO_WITH_OFFSET)

    def test_editorial_names_its_author_as_a_person(self):
        """An editorial with an author claims that person."""
        self.assertEqual(
            self.payload(self.editorial)["author"],
            {"@type": "Person", "name": "Anna Andersson"},
        )

    def test_data_highlight_claims_no_author(self):
        """A data highlight describes work published elsewhere, so it names no author."""
        payload = self.payload(self.data_highlight)

        self.assertEqual(payload["@type"], "Article")
        self.assertNotIn("author", payload)

    def test_article_without_keywords_omits_the_key(self):
        """An empty keyword field produces no ``keywords`` key rather than an empty list."""
        self.assertNotIn("keywords", self.payload(self.data_highlight))

    def test_image_url_shares_the_page_url_host(self):
        """Media URLs resolve against the page's site, not ``WAGTAILADMIN_BASE_URL``.

        A rendition's ``full_url`` uses the admin base URL, which need not be the
        public host, so a payload built from it would mix two hosts.
        """
        payload = self.payload(self.editorial)

        self.assertEqual(urlsplit(payload["image"]).netloc, urlsplit(payload["url"]).netloc)


class NewsArticlePayloadTest(StructuredDataPageTestCase):
    """Criterion 4: news pages are NewsArticles and never carry keywords."""

    def test_news_page_emits_news_article_attributed_to_the_organization(self):
        """The portal writes its own news, so the Organization is author and publisher."""
        payload = self.payload(self.news)

        self.assertEqual(payload["@type"], "NewsArticle")
        self.assertEqual(payload["headline"], "Portal adds a new dashboard")
        self.assertEqual(payload["author"]["name"], "SciLifeLab Data Centre")
        self.assertEqual(payload["publisher"]["name"], "SciLifeLab Data Centre")
        self.assertRegex(payload["datePublished"], _ISO_WITH_OFFSET)
        self.assertRegex(payload["dateModified"], _ISO_WITH_OFFSET)
        self.assertTrue(payload["image"].startswith("http://testserver/"))

    def test_news_page_has_no_keywords_key(self):
        """``NewsPage`` has no keyword field, so the Article lookup must not leak in."""
        self.assertNotIn("keywords", self.payload(self.news))


class DatasetPayloadTest(StructuredDataPageTestCase):
    """Criterion 5: dashboards backed by an uploaded file are Datasets."""

    def test_dashboard_with_data_emits_dataset(self):
        """The dashboard describes itself as the dataset it publishes."""
        payload = self.payload(self.dashboard)

        self.assertEqual(payload["@type"], "Dataset")
        self.assertEqual(payload["name"], "Serology statistics")
        self.assertEqual(
            payload["description"],
            "Aggregated serology test results from Swedish laboratories.",
        )
        self.assertEqual(payload["url"], "http://testserver/dashboards/serology-statistics/")
        self.assertEqual(payload["keywords"], ["serology", "sars-cov-2"])
        self.assertEqual(payload["creator"]["name"], "SciLifeLab Data Centre")

    def test_dataset_names_the_dashboards_index_as_its_catalog(self):
        """``includedInDataCatalog`` is resolved from the page's ancestry."""
        catalog = self.payload(self.dashboard)["includedInDataCatalog"]

        self.assertEqual(catalog["@type"], "DataCatalog")
        self.assertEqual(catalog["name"], "Dashboards")
        self.assertEqual(catalog["url"], "http://testserver/dashboards/")

    def test_dataset_advertises_the_source_file_absolutely(self):
        """``distribution`` points at a fetchable absolute URL with its media type."""
        distribution = self.payload(self.dashboard)["distribution"]

        self.assertEqual(len(distribution), 1)
        self.assertEqual(distribution[0]["@type"], "DataDownload")
        self.assertEqual(distribution[0]["encodingFormat"], "text/csv")
        self.assertTrue(
            distribution[0]["contentUrl"].startswith("http://testserver/"),
            distribution[0]["contentUrl"],
        )
        self.assertIn("serology", distribution[0]["contentUrl"])

    def test_dataset_carries_a_modification_date(self):
        """``dateModified`` reports the data freshness the dashboard shows."""
        self.assertRegex(self.payload(self.dashboard)["dateModified"], r"^\d{4}-\d{2}-\d{2}")

    def test_dashboard_without_data_falls_back_to_web_page(self):
        """With nothing uploaded there is no dataset to claim."""
        payload = self.payload(self.dashboard_without_data)

        self.assertEqual(payload["@type"], "WebPage")
        self.assertNotIn("distribution", payload)


class SluDatasetDoiTest(StructuredDataPageTestCase):
    """Criterion 5: only the SLU overview carries the dataset DOI."""

    def test_slu_dashboard_identifies_itself_by_doi(self):
        """The SLU overview ties itself to the DOI its citation already shows."""
        payload = self.payload(self.slu)

        self.assertEqual(payload["@type"], "Dataset")
        self.assertEqual(payload["identifier"], SLU_DATASET_DOI_URL)
        self.assertEqual(payload["sameAs"], SLU_DATASET_DOI_URL)

    def test_doi_matches_the_visible_citation(self):
        """The constant and the page's rendered citation are the same DOI."""
        response = self.client.get(self.slu.url)

        self.assertEqual(SLU_DATASET_DOI_URL, "https://doi.org/10.17044/scilifelab.14256317")
        self.assertContains(response, "10.17044/scilifelab.14256317")

    def test_other_dashboards_carry_no_doi(self):
        """The DOI belongs to the SLU dataset alone."""
        payload = self.payload(self.dashboard)

        self.assertNotIn("identifier", payload)
        self.assertNotIn("sameAs", payload)


class WebPageFallbackTest(StructuredDataPageTestCase):
    """Criterion 6: everything else is a WebPage belonging to the site."""

    def test_basic_page_emits_web_page_part_of_the_website(self):
        """A generic page names itself and the site it belongs to."""
        payload = self.payload(self.basic)

        self.assertEqual(payload["@type"], "WebPage")
        self.assertEqual(payload["name"], "About the portal")
        self.assertEqual(payload["url"], "http://testserver/about/")
        self.assertEqual(payload["isPartOf"]["@type"], "WebSite")
        self.assertEqual(payload["isPartOf"]["name"], settings.WAGTAIL_SITE_NAME)

    def test_slu_subpage_emits_web_page(self):
        """Virus subpages share the overview's file, so they are not separate Datasets."""
        payload = self.payload(self.slu_subpage)

        self.assertEqual(payload["@type"], "WebPage")
        self.assertNotIn("distribution", payload)

    def test_index_pages_emit_web_page(self):
        """Listing pages are plain web pages, not catalogues."""
        for page in (self.dashboard_index, self.news_index, self.highlights_index):
            with self.subTest(page=page.title):
                self.assertEqual(self.payload(page)["@type"], "WebPage")

    def test_page_without_a_description_omits_the_key(self):
        """No description source means no empty ``description`` in the payload."""
        self.assertNotIn("description", self.payload(self.basic))


class MissingPageTest(StructuredDataPageTestCase):
    """Criterion 6: the 404 template renders with no page, and so no payload."""

    def test_404_response_carries_no_structured_data(self):
        """``404.html`` extends the base template but has no page to describe."""
        response = self.client.get("/no-such-page/")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.scripts(response), [])

    def test_404_template_renders_without_a_context(self):
        """The template is safe to render with nothing in context at all."""
        self.assertIn("cannot be found", render_to_string("404.html", {}))


class EscapingTest(StructuredDataPageTestCase):
    """Criterion 7: a hostile title cannot break out of the script element."""

    def test_script_breaking_title_is_escaped_in_place(self):
        """The payload keeps one script element and escapes the dangerous characters."""
        response = self.client.get(self.xss_page.url)
        self.assertEqual(response.status_code, 200)

        scripts = self.scripts(response)
        self.assertEqual(len(scripts), 1)
        self.assertNotIn("<", scripts[0])
        self.assertNotIn(">", scripts[0])
        self.assertIn("\\u003c", scripts[0])
        self.assertIn("\\u003e", scripts[0])

    def test_escaped_title_still_decodes_to_the_original(self):
        """Escaping is a transport concern: the parsed name is the real title."""
        self.assertEqual(self.payload(self.xss_page)["name"], _XSS_TITLE)
