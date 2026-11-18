"""Render tests for the Portal Data page (cms/pages/portal_data/index.html)."""

from __future__ import annotations

import tempfile
from html.parser import HTMLParser

from django.core.cache import cache
from django.test import override_settings
from wagtail.models import Page, Site
from wagtail.test.utils import WagtailPageTestCase

from cms.pages import HomePage, PortalDataPage


class _FormControls(HTMLParser):
    """Collect every <form> and <button> start tag's attributes, by id where present."""

    def __init__(self) -> None:
        """Start with nothing collected."""
        super().__init__()
        self.forms: dict[str, dict[str, str | None]] = {}
        self.buttons: list[dict[str, str | None]] = []
        self._open_forms: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Record forms and buttons, noting which form each button sits inside."""
        attributes = dict(attrs)
        if tag == "form":
            form_id = attributes.get("id") or ""
            self.forms[form_id] = attributes
            self._open_forms.append(form_id)
        elif tag == "button":
            attributes["_inside_form"] = self._open_forms[-1] if self._open_forms else None
            self.buttons.append(attributes)

    def handle_endtag(self, tag: str) -> None:
        """Close the innermost open form."""
        if tag == "form" and self._open_forms:
            self._open_forms.pop()


class TestPortalDataBulkDownloadForm(WagtailPageTestCase):
    """The bulk download form must have a real submit button (WCAG 3.2.2, H32)."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a home page with a published metabolomics Portal Data page."""
        root = Page.get_first_root_node()
        for child in root.get_children():
            child.delete()
        root = Page.get_first_root_node()
        cls.home = HomePage(title="Home", slug="home")
        root.add_child(instance=cls.home)
        Site.objects.update_or_create(
            is_default_site=True, defaults={"hostname": "testserver", "root_page": cls.home}
        )
        cls.page = PortalDataPage(title="Metabolomics data", slug="metabolomics-data")
        cls.home.add_child(instance=cls.page)
        cls.page.save_revision().publish()

    def setUp(self) -> None:
        """Render against an empty datasets root, with a fresh listing cache."""
        cache.clear()
        datasets_root = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(override_settings(DATASETS_ROOT=datasets_root))

    def _controls(self) -> _FormControls:
        """Fetch the page and parse its forms and buttons."""
        response = self.client.get(self.page.url)
        self.assertEqual(response.status_code, 200)
        parser = _FormControls()
        parser.feed(response.content.decode())
        return parser

    def test_bulk_download_form_has_a_submit_button(self) -> None:
        """The download button submits #bulkDownloadForm, which posts the selection."""
        controls = self._controls()

        self.assertEqual(controls.forms["bulkDownloadForm"].get("method"), "post")
        submitters = [
            button
            for button in controls.buttons
            if button.get("form") == "bulkDownloadForm"
            or button["_inside_form"] == "bulkDownloadForm"
        ]
        self.assertEqual(len(submitters), 1)
        self.assertEqual(submitters[0].get("type"), "submit")
        self.assertEqual(submitters[0].get("id"), "bulkDownloadSubmit")

    def test_search_form_keeps_its_own_submit_button(self) -> None:
        """Pointing the download button elsewhere leaves the search form's submit intact."""
        controls = self._controls()

        search_submitters = [
            button
            for button in controls.buttons
            if button["_inside_form"] == "searchForm"
            and button.get("type") == "submit"
            and not button.get("form")
        ]
        self.assertEqual(len(search_submitters), 1)
