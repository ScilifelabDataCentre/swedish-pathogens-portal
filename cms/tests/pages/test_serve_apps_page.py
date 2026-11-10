"""Tests for the ServeAppsPage model and its listing service."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory
from wagtail.models import Page, Site
from wagtail.test.utils import WagtailPageTestCase

from cms.blocks import ServeAppsBlock
from cms.pages import GenomicDataPage, HomePage, ServeAppsPage
from cms.services.serve_apps import DEFAULT_SORT, FACET_VALUES_SHOWN, resolve_state


def serve_item(app_id: int, name: str, description: str, **fields: object) -> dict:
    """Build one public-apps item, as Serve returns it."""
    item = {
        "id": app_id,
        "name": name,
        "url": f"https://app{app_id}.serve.scilifelab.se",
        "description": description,
        "created_on": f"2026-01-{app_id:02d}T10:00:00Z",
        "updated_on": f"2026-03-{30 - app_id:02d}T10:00:00Z",
        "access": "public",
        "k8s_user_app_status": "Running",
        "app_status": "Running",
        "app_type": "Shiny App",
    }
    item.update(fields)
    return item


SERVE_RESPONSE = {
    "data": [
        serve_item(1, "Malaria Traveller Proteomics", "Plasma proteins during acute malaria."),
        serve_item(2, "AMR-KG", "Antimicrobial resistance knowledge graph.", app_type="Custom App"),
        serve_item(3, "Bedaquiline simulator", "Tuberculosis treatment outcomes."),
        serve_item(
            4, "Flower classifier", "Predicts flower types from images.", app_type="Gradio App"
        ),
        serve_item(5, "PlasPredict", "Predicts plasmid host range.", app_type="Custom App"),
        serve_item(6, "Gone app", "A malaria app.", k8s_user_app_status="Deleted"),
    ]
}


class TestServeAppsPage(WagtailPageTestCase):
    """Tests for the ServeAppsPage model and listing."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a home and a models and apps page."""
        cls.factory = RequestFactory()

        root = Page.get_first_root_node()
        for child in root.get_children():
            child.delete()
        root = Page.get_first_root_node()
        cls.home = HomePage(title="Home", slug="home")
        root.add_child(instance=cls.home)
        Site.objects.update_or_create(
            is_default_site=True, defaults={"hostname": "testserver", "root_page": cls.home}
        )

        cls.page = ServeAppsPage(
            title="Models and apps",
            slug="models-and-apps",
            content=[
                ("text", "<p>Some descriptive text.</p>"),
                ("serve_apps", {"include_app_ids": [], "exclude_app_ids": []}),
            ],
        )
        cls.home.add_child(instance=cls.page)
        cls.page.save_revision().publish()

    def setUp(self):
        """Clear the cache so Serve results don't leak between tests."""
        cache.clear()

    def get_htmx(self, params: dict | list | None = None):
        """GET the page as an HTMX request with the given query parameters."""
        return self.client.get(self.page.url, params or {}, HTTP_HX_REQUEST="true")

    def shown_ids(self, response: HttpResponse) -> list[int]:
        """Return the Serve IDs of the app cards in the response, in order."""
        return [app.id for app in response.context["apps"]]

    # --- Page model ---------------------------------------------------------------

    def test_can_be_created_under_home_page_only(self):
        """Can be created under home page only."""
        self.assertAllowedParentPageTypes(ServeAppsPage, {HomePage})
        self.assertAllowedSubpageTypes(ServeAppsPage, {})
        self.assertCanCreateAt(HomePage, ServeAppsPage)
        self.assertCanNotCreateAt(GenomicDataPage, ServeAppsPage)

    @patch("portal_data.serve_apps.fetch_json")
    def test_full_page_renders_search_form_without_calling_serve(self, mock_fetch: MagicMock):
        """Full page renders search form without calling serve."""
        response = self.client.get(self.page.url, {"q": "malaria"})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "cms/pages/serve_apps/index.html")
        self.assertContains(response, '<h1 class="sr-only">Models and apps</h1>', count=1)
        self.assertContains(response, 'id="serve-search-input" name="q" value="malaria"')
        self.assertContains(response, 'hx-get="/models-and-apps/?q=malaria"')
        mock_fetch.assert_not_called()

    @patch("portal_data.serve_apps.fetch_json")
    def test_htmx_history_restore_gets_full_page(self, mock_fetch: MagicMock):
        """Htmx history restore gets full page."""
        response = self.client.get(
            self.page.url, HTTP_HX_REQUEST="true", HTTP_HX_HISTORY_RESTORE_REQUEST="true"
        )
        self.assertTemplateUsed(response, "cms/pages/serve_apps/index.html")
        mock_fetch.assert_not_called()

    # --- Listing ------------------------------------------------------------------

    @patch("portal_data.serve_apps.fetch_json", return_value=SERVE_RESPONSE)
    def test_default_listing_shows_pathogen_related_apps_recently_updated_first(
        self, _mock: MagicMock
    ):
        """Default listing shows pathogen related apps recently updated first."""
        response = self.get_htmx()

        self.assertTemplateUsed(response, "cms/pages/serve_apps/partials/serve_listing.html")
        self.assertEqual(self.shown_ids(response), [1, 2, 3])
        self.assertContains(response, "Showing 3 of 3 pathogen-related apps and models")
        self.assertContains(response, 'href="https://app1.serve.scilifelab.se" target="_blank"')
        self.assertContains(response, "Open app")
        self.assertContains(response, "Serve ID 1")
        self.assertContains(
            response, '<time datetime="2026-03-29T12:00:00+02:00">29 Mar 2026</time>'
        )
        self.assertNotContains(response, "Flower classifier")
        self.assertNotContains(response, "PlasPredict")
        self.assertNotContains(response, "Gone app")

    @patch("portal_data.serve_apps.fetch_json", return_value=SERVE_RESPONSE)
    def test_sort_orders(self, _mock: MagicMock):
        """Sort orders."""
        self.assertEqual(self.shown_ids(self.get_htmx({"sort": "name"})), [2, 3, 1])
        self.assertEqual(self.shown_ids(self.get_htmx({"sort": "created"})), [3, 2, 1])
        response = self.get_htmx({"sort": "created"})
        self.assertContains(response, '<option value="created" selected>Newest</option>')

    @patch("portal_data.serve_apps.fetch_json", return_value=SERVE_RESPONSE)
    def test_search_matches_every_word_in_name_or_description(self, _mock: MagicMock):
        """Search matches every word in name or description."""
        self.assertEqual(self.shown_ids(self.get_htmx({"q": "TUBERCULOSIS"})), [3])
        self.assertEqual(self.shown_ids(self.get_htmx({"q": "malaria proteins"})), [1])
        self.assertEqual(self.shown_ids(self.get_htmx({"q": "malaria graph"})), [])

    @patch("portal_data.serve_apps.fetch_json", return_value=SERVE_RESPONSE)
    def test_facets_filter_and_count(self, _mock: MagicMock):
        """Facets filter and count."""
        response = self.get_htmx({"type": "Custom App"})

        self.assertEqual(self.shown_ids(response), [2])
        content = response.content.decode()
        self.assertRegex(content, r'name="type" value="Custom App"\s+class="[^"]*" checked')
        self.assertRegex(content, r'name="type" value="Shiny App"\s+class="[^"]*"\s*>')
        # the type facet is counted without its own selection, the keyword facet with it
        types = {
            v["value"]["value"]: v["count_display"] for v in response.context["facets"][0]["values"]
        }
        self.assertEqual(types, {"Shiny App": "2", "Custom App": "1"})
        keywords = response.context["facets"][1]
        self.assertEqual(keywords["label"], "Pathogen keyword")
        self.assertIn("Antimicrobial resistance", [v["value"]["label"] for v in keywords["values"]])
        self.assertContains(response, "Clear all filters")

    @patch("portal_data.serve_apps.fetch_json", return_value=SERVE_RESPONSE)
    def test_values_within_a_facet_are_ored(self, _mock: MagicMock):
        """Values within a facet are ored."""
        response = self.get_htmx([("type", "Custom App"), ("type", "Shiny App")])
        self.assertEqual(self.shown_ids(response), [1, 2, 3])

    @patch("portal_data.serve_apps.fetch_json", return_value=SERVE_RESPONSE)
    def test_unknown_selected_facet_value_is_kept_so_it_can_be_unticked(self, _mock: MagicMock):
        """Unknown selected facet value is kept so it can be unticked."""
        response = self.get_htmx({"type": "Nonexistent"})
        self.assertEqual(self.shown_ids(response), [])
        self.assertContains(response, "No apps found")
        self.assertRegex(response.content.decode(), r'value="Nonexistent"\s+class="[^"]*" checked')

    @patch("portal_data.serve_apps.fetch_json")
    def test_long_facets_are_tucked_behind_show_more(self, mock_fetch: MagicMock):
        """Long facets are tucked behind show more."""
        types = [f"Type {n}" for n in range(FACET_VALUES_SHOWN + 2)]
        mock_fetch.return_value = {
            "data": [
                serve_item(n + 1, f"App {n}", "Malaria", app_type=t) for n, t in enumerate(types)
            ]
        }
        content = self.get_htmx().content.decode()
        self.assertRegex(content, r'<ul id="serve-facet-more-type"\s+class="[^"]* hidden"')
        content = self.get_htmx({"type": types[-1]}).content.decode()
        self.assertNotRegex(content, r'<ul id="serve-facet-more-type"\s+class="[^"]* hidden"')

    @patch("portal_data.serve_apps.fetch_json", return_value=SERVE_RESPONSE)
    def test_editors_can_include_and_exclude_apps(self, _mock: MagicMock):
        """Editors can include and exclude apps."""
        self.page.content = [
            ("serve_apps", {"include_app_ids": [5, 6], "exclude_app_ids": [1]}),
        ]
        self.page.save_revision().publish()

        response = self.get_htmx()

        # 6 is deleted on Serve, so can't be shown even when included
        self.assertEqual(self.shown_ids(response), [2, 3, 5])

    def test_include_and_exclude_lists_are_optional(self):
        """The block starts with empty lists, which are valid, and blank entries are allowed."""
        block = ServeAppsBlock()
        default = block.get_default()
        self.assertEqual(list(default["include_app_ids"]), [])
        self.assertEqual(list(default["exclude_app_ids"]), [])
        block.clean(default)
        block.clean(block.to_python({"include_app_ids": [None], "exclude_app_ids": []}))

    @patch("portal_data.serve_apps.fetch_json", return_value=SERVE_RESPONSE)
    def test_blank_and_missing_ids_are_ignored(self, _mock: MagicMock):
        """Blank list entries, or no Serve apps settings at all, leave the default listing."""
        for value in ({"include_app_ids": [None], "exclude_app_ids": [None]}, {}):
            with self.subTest(value=value):
                self.page.content = [("serve_apps", value)]
                self.page.save_revision().publish()
                self.assertEqual(self.shown_ids(self.get_htmx()), [1, 2, 3])

    @patch("portal_data.serve_apps.fetch_json", return_value=None)
    def test_failure_shows_error(self, _mock: MagicMock):
        """Failure shows error."""
        response = self.get_htmx()
        self.assertContains(response, "The apps could not be loaded from SciLifeLab Serve")
        self.assertNotContains(response, "Showing")

    @patch("portal_data.serve_apps.fetch_json", return_value={"data": []})
    def test_no_apps(self, _mock: MagicMock):
        """No apps."""
        response = self.get_htmx()
        self.assertContains(response, "No apps found")
        self.assertContains(response, "Showing 0 of 0")

    def test_resolve_state_validates_input(self):
        """Resolve state validates input."""
        request = self.factory.get(
            "/",
            {
                "q": "  malaria\n ",
                "type": ["Shiny App", "Shiny App", ""],
                "unknown": "x",
                "sort": "bogus",
            },
        )
        state = resolve_state(request)
        self.assertEqual(state.text, "malaria")
        self.assertEqual(state.facets, {"type": ["Shiny App"]})
        self.assertEqual(state.sort, DEFAULT_SORT)
        self.assertEqual(state.url("/p/", facets={}), "/p/?q=malaria")
        self.assertEqual(resolve_state(self.factory.get("/")).url("/p/"), "/p/")
