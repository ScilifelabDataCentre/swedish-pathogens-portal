"""Tests for the ``structured_data`` template tag.

These cover the parts that need no database: which builder ``build_payload``
dispatches to for each page type, the serialisation and escaping rules, and the
tag's own failure posture. The field-by-field output of each builder is covered
end to end against real pages in ``cms/tests/pages/test_structured_data_pages.py``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.template import Context, Template
from django.test import SimpleTestCase
from wagtail.models import Site

from cms.pages.dashboard import DashboardPage
from cms.pages.drr_dataset import DrrDatasetPage
from cms.pages.highlights_and_editorials import HighlightsAndEditorialsPage
from cms.pages.home import HomePage
from cms.pages.news import NewsPage
from cms.pages.slu_dashboard import SLUDashboardPage
from cms.pages.slu_dashboard_subpage import SLUDashboardSubPage
from cms.snippets.dashboard_data import DashboardData
from cms.snippets.drr_dataset_data import DrrDatasetData
from cms.templatetags.structured_data import (
    SCHEMA_CONTEXT,
    _absolute_media_url,
    _distribution,
    _image_url,
    _set_if,
    _site_name,
    _site_root_url,
    build_payload,
    encode_payload,
    structured_data,
)

_MODULE = "cms.templatetags.structured_data"


def _stub_builders() -> dict[str, MagicMock]:
    """Return one patcher per builder, each returning its own marker payload."""
    return {
        name: patch(f"{_MODULE}.{name}", return_value={"@type": schema_type})
        for name, schema_type in (
            ("_website", "WebSite"),
            ("_article", "Article"),
            ("_news_article", "NewsArticle"),
            ("_dataset", "Dataset"),
            ("_web_page", "WebPage"),
        )
    }


class BuildPayloadDispatchTest(SimpleTestCase):
    """``build_payload`` picks the builder matching the page type."""

    def _dispatch(self, page: MagicMock) -> str:
        """Return the ``@type`` ``build_payload`` produces, with every builder stubbed."""
        patchers = _stub_builders()
        for patcher in patchers.values():
            patcher.start()
            self.addCleanup(patcher.stop)

        payload = build_payload(page)
        self.assertEqual(payload["@context"], SCHEMA_CONTEXT)
        return payload["@type"]

    def test_home_page_builds_website(self):
        """A ``HomePage`` is described as the ``WebSite``."""
        self.assertEqual(self._dispatch(MagicMock(spec=HomePage)), "WebSite")

    def test_home_page_website_names_the_organization_as_publisher(self):
        """The homepage node carries the Organization, not just the bare WebSite."""
        page = MagicMock(spec=HomePage)
        page.get_site.return_value = SimpleNamespace(
            site_name="Swedish Pathogens Portal", root_url="https://example.test"
        )

        payload = build_payload(page)

        self.assertEqual(payload["publisher"]["@type"], "Organization")
        self.assertEqual(payload["publisher"]["name"], "SciLifeLab Data Centre")

    def test_dashboard_with_data_row_builds_dataset(self):
        """A dashboard whose data row is a ``DashboardData`` is a ``Dataset``."""
        page = MagicMock(spec=DashboardPage)
        page.dashboard_data = MagicMock(spec=DashboardData)

        self.assertEqual(self._dispatch(page), "Dataset")

    def test_slu_dashboard_builds_dataset(self):
        """``SLUDashboardPage`` inherits the data row, so it is a ``Dataset`` too."""
        page = MagicMock(spec=SLUDashboardPage)
        page.dashboard_data = MagicMock(spec=DashboardData)

        self.assertEqual(self._dispatch(page), "Dataset")

    def test_dashboard_without_data_row_builds_web_page(self):
        """A dashboard with no uploaded data has no dataset to describe."""
        page = MagicMock(spec=DashboardPage)
        page.dashboard_data = None

        self.assertEqual(self._dispatch(page), "WebPage")

    def test_drr_dataset_page_builds_web_page(self):
        """A DRR page's data row is truthy but the wrong model, so it is a ``WebPage``.

        Guards the regression the spec calls out: dispatching on truthiness would
        send ``DrrDatasetData`` into the ``Dataset`` builder, which reads a
        ``source_file`` it does not have.
        """
        page = MagicMock(spec=DrrDatasetPage)
        page.dashboard_data = MagicMock(spec=DrrDatasetData)

        self.assertTrue(page.dashboard_data)
        self.assertEqual(self._dispatch(page), "WebPage")

    def test_highlights_page_builds_article(self):
        """A highlight or editorial is an ``Article``."""
        self.assertEqual(self._dispatch(MagicMock(spec=HighlightsAndEditorialsPage)), "Article")

    def test_news_page_builds_news_article(self):
        """A news page is a ``NewsArticle``."""
        self.assertEqual(self._dispatch(MagicMock(spec=NewsPage)), "NewsArticle")

    def test_slu_subpage_builds_web_page(self):
        """SLU virus subpages share the overview's file, so they are not Datasets."""
        self.assertEqual(self._dispatch(MagicMock(spec=SLUDashboardSubPage)), "WebPage")


class SetIfTest(SimpleTestCase):
    """``_set_if`` keeps empty values out of the payload entirely."""

    def test_non_empty_value_is_assigned(self):
        """A truthy value lands under its key."""
        payload: dict[str, object] = {}
        _set_if(payload, "name", "Dashboard")

        self.assertEqual(payload, {"name": "Dashboard"})

    def test_empty_values_are_omitted(self):
        """Empty strings, empty lists, empty dicts and ``None`` add no key at all."""
        payload: dict[str, object] = {}
        for key, value in (("a", ""), ("b", []), ("c", {}), ("d", None)):
            _set_if(payload, key, value)

        self.assertEqual(payload, {})


class EncodePayloadTest(SimpleTestCase):
    """``encode_payload`` produces JSON that cannot break out of a script element."""

    def test_round_trips_through_json_loads(self):
        """The encoded payload still parses, and the escapes decode back."""
        encoded = encode_payload({"@context": SCHEMA_CONTEXT, "name": "Nord & Söder"})

        self.assertEqual(json.loads(encoded)["name"], "Nord & Söder")

    def test_script_breaking_characters_are_escaped(self):
        """``<``, ``>`` and ``&`` are replaced by unicode escapes."""
        encoded = encode_payload({"name": "</script><script>x && y"})

        self.assertNotIn("<", encoded)
        self.assertNotIn(">", encoded)
        self.assertNotIn("&", encoded)
        self.assertIn("\\u003c", encoded)
        self.assertIn("\\u003e", encoded)
        self.assertIn("\\u0026", encoded)
        self.assertEqual(json.loads(encoded)["name"], "</script><script>x && y")


class DistributionTest(SimpleTestCase):
    """``_distribution`` advertises an uploaded file and nothing else."""

    def test_missing_file_yields_no_distribution(self):
        """A data row with no file advertises nothing rather than an empty URL."""
        page = MagicMock(spec=DashboardPage)
        data_row = SimpleNamespace(source_file=None)

        self.assertEqual(_distribution(page, data_row), [])

    def test_data_row_without_source_file_attribute_yields_no_distribution(self):
        """A ``DrrDatasetData``-shaped row has no ``source_file`` and must not raise."""
        page = MagicMock(spec=DashboardPage)
        data_row = SimpleNamespace(source_file_hash="abc123")

        self.assertEqual(_distribution(page, data_row), [])

    def test_file_is_advertised_with_its_media_type(self):
        """An uploaded CSV becomes one ``DataDownload`` with an absolute URL."""
        page = MagicMock(spec=DashboardPage)
        page.get_site.return_value = SimpleNamespace(root_url="https://example.test")
        data_row = SimpleNamespace(
            source_file=SimpleNamespace(url="/media/dashboard_data/d.csv", name="d.csv")
        )

        self.assertEqual(
            _distribution(page, data_row),
            [
                {
                    "@type": "DataDownload",
                    "contentUrl": "https://example.test/media/dashboard_data/d.csv",
                    "encodingFormat": "text/csv",
                }
            ],
        )


class AbsoluteMediaUrlTest(SimpleTestCase):
    """``_absolute_media_url`` never emits a relative or hostless URL."""

    def test_relative_url_is_joined_to_the_site_root(self):
        """A media URL is made absolute against the page's site."""
        page = MagicMock(spec=DashboardPage)
        page.get_site.return_value = SimpleNamespace(root_url="https://example.test/")

        url = _absolute_media_url(page, SimpleNamespace(url="/media/d.csv"))

        self.assertEqual(url, "https://example.test/media/d.csv")

    def test_already_absolute_url_is_passed_through(self):
        """A storage backend returning an absolute URL is used as-is."""
        page = MagicMock(spec=DashboardPage)

        url = _absolute_media_url(page, SimpleNamespace(url="https://cdn.test/d.csv"))

        self.assertEqual(url, "https://cdn.test/d.csv")

    def test_no_site_yields_no_url(self):
        """Without a resolvable site there is no honest absolute URL to emit."""
        page = MagicMock(spec=DashboardPage)
        page.get_site.return_value = None

        self.assertEqual(_absolute_media_url(page, SimpleNamespace(url="/media/d.csv")), "")

    def test_field_with_no_file_yields_no_url(self):
        """An empty file field raises ``ValueError`` on ``.url`` and is handled."""
        page = MagicMock(spec=DashboardPage)
        file_field = MagicMock()
        type(file_field).url = property(lambda _: (_ for _ in ()).throw(ValueError))

        self.assertEqual(_absolute_media_url(page, file_field), "")


class UnresolvableSiteTest(SimpleTestCase):
    """A page whose site cannot be loaded still gets a usable payload."""

    def _page_with_broken_site(self) -> MagicMock:
        """Return a page whose ``get_site`` raises, as a stale site cache makes it."""
        page = MagicMock(spec=HomePage, id=5)
        page.get_site.side_effect = Site.DoesNotExist
        return page

    @patch(f"{_MODULE}.LOGGER")
    def test_site_name_falls_back_to_the_configured_name(self, mock_logger: MagicMock):
        """The lookup failure is logged once and ``WAGTAIL_SITE_NAME`` is used."""
        self.assertEqual(_site_name(self._page_with_broken_site()), settings.WAGTAIL_SITE_NAME)
        mock_logger.warning.assert_called_once_with("structured_data.site_unresolved", page_id=5)

    @patch(f"{_MODULE}.LOGGER")
    def test_root_url_is_omitted_rather_than_guessed(self, _mock_logger: MagicMock):
        """No site means no honest absolute URL, so none is emitted."""
        self.assertEqual(_site_root_url(self._page_with_broken_site()), "")

    @patch(f"{_MODULE}.LOGGER")
    def test_payload_is_still_built(self, _mock_logger: MagicMock):
        """Losing the site must not cost the page its structured data entirely."""
        payload = build_payload(self._page_with_broken_site())

        self.assertEqual(payload["@type"], "WebSite")
        self.assertEqual(payload["name"], settings.WAGTAIL_SITE_NAME)
        self.assertNotIn("url", payload)


class ImageUrlTest(SimpleTestCase):
    """``_image_url`` degrades instead of breaking a page over its image."""

    def test_page_without_an_image_field_yields_no_url(self):
        """Pages such as ``HomePage`` have no image, which is not an error."""
        self.assertEqual(_image_url(MagicMock(spec=HomePage)), "")

    @patch(f"{_MODULE}.LOGGER")
    def test_unusable_original_is_logged_and_yields_no_url(self, mock_logger: MagicMock):
        """A missing image file must not take the whole page down with it."""
        page = MagicMock(spec=NewsPage, id=3)
        page.image.get_rendition.side_effect = FileNotFoundError

        self.assertEqual(_image_url(page), "")
        mock_logger.warning.assert_called_once_with(
            "structured_data.image_rendition_failed", page_id=3
        )


class StructuredDataTagTest(SimpleTestCase):
    """The tag wraps the payload, and degrades instead of breaking the page."""

    def test_no_page_in_context_renders_nothing(self):
        """The 404 template extends ``base.html`` with no page, and must stay clean."""
        self.assertEqual(structured_data(Context({})), "")

    def test_payload_is_wrapped_in_a_json_ld_script_element(self):
        """A built payload is emitted as one ``application/ld+json`` script."""
        with patch(f"{_MODULE}.build_payload", return_value={"@type": "WebPage"}):
            rendered = Template("{% load structured_data %}{% structured_data %}").render(
                Context({"page": MagicMock(spec=HomePage)})
            )

        self.assertEqual(rendered.count('<script type="application/ld+json">'), 1)
        self.assertIn('{"@type": "WebPage"}', rendered)

    @patch(f"{_MODULE}.LOGGER")
    def test_build_failure_is_logged_and_renders_nothing(self, mock_logger: MagicMock):
        """The tag runs on every page, so a build error must not propagate."""
        page = MagicMock(spec=HomePage, id=7)

        with patch(f"{_MODULE}.build_payload", side_effect=RuntimeError("boom")):
            rendered = structured_data(Context({"page": page}))

        self.assertEqual(rendered, "")
        mock_logger.exception.assert_called_once_with("structured_data.build_failed", page_id=7)
