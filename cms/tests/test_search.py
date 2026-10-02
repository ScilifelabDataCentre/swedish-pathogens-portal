"""Tests for site-wide search (indexing, results view, autocomplete)."""

from io import StringIO

from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from wagtail.models import Page, Site
from wagtail.rich_text import RichText
from wagtail.test.utils import WagtailPageTestCase

from cms.pages import (
    BasicPage,
    DashboardIndexPage,
    HomePage,
    NewsIndexPage,
    NewsPage,
    PublicationsPage,
    SLUDashboardPage,
    SLUDashboardSubPage,
)
from cms.tests.utils import create_test_image
from cms.views.search import MAX_QUERY_LENGTH, page_type_label


class SearchTestCase(WagtailPageTestCase):
    """Base setup: a site with a home page, a news index, and searchable pages."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Build a minimal live site and index it for search."""
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
        cls.news_index = NewsIndexPage(title="News", slug="news")
        cls.home.add_child(instance=cls.news_index)
        cls.news_index.save_revision().publish()

        cls.article = NewsPage(
            title="Influenza surveillance update",
            slug="influenza-surveillance-update",
            description="Weekly zuluwidget report on national influenza monitoring.",
            image=create_test_image(),
        )
        cls.news_index.add_child(instance=cls.article)
        cls.article.save_revision().publish()

        # A page type with no `image` field, to exercise the imageless result path.
        cls.basic = BasicPage(title="Preparedness overview", slug="preparedness-overview")
        cls.home.add_child(instance=cls.basic)
        cls.basic.save_revision().publish()

        cls.dashboard_index = DashboardIndexPage(title="Dashboards", slug="dashboards")
        cls.home.add_child(instance=cls.dashboard_index)
        cls.dashboard_index.save_revision().publish()

        # A DashboardPage subclass. Multi-table inheritance returns these as their
        # own class, which is what used to leave the type badge blank.
        cls.slu = SLUDashboardPage(
            title="Wastewater monitoring",
            slug="wastewater-monitoring",
            description="Quixotrap wastewater surveillance overview.",
            image=create_test_image(),
            data_status="active",
        )
        cls.dashboard_index.add_child(instance=cls.slu)
        cls.slu.save_revision().publish()

        cls.slu_subpage = SLUDashboardSubPage(title="Methodology", slug="methodology")
        cls.slu.add_child(instance=cls.slu_subpage)
        cls.slu_subpage.save_revision().publish()

        # Shares the dashboard's title, so the listing has to show something
        # beyond the name to tell the two apart.
        cls.namesake = BasicPage(
            title="Wastewater monitoring",
            slug="wastewater-monitoring-basic",
        )
        cls.home.add_child(instance=cls.namesake)
        cls.namesake.save_revision().publish()

        cls.publications = PublicationsPage(
            title="Publications",
            slug="publications",
            content=[("text", RichText("<p>Quixotrap publication listing.</p>"))],
        )
        cls.home.add_child(instance=cls.publications)
        cls.publications.save_revision().publish()

        call_command("update_index", stdout=StringIO())

    def test_page_description_is_searchable(self) -> None:
        """A distinctive term in a page's description field is findable."""
        results = Page.objects.live().public().search("zuluwidget")
        self.assertTrue(any(r.pk == self.article.pk for r in results))

    def test_search_page_returns_matches(self) -> None:
        """The results page lists a matching page under its type label."""
        resp = self.client.get("/search/", {"q": "zuluwidget"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Influenza surveillance update")
        self.assertContains(resp, "News")

    def test_blank_query_renders_prompt(self) -> None:
        """No query renders the empty prompt, not a zero-results message."""
        resp = self.client.get("/search/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Enter a search term")

    def test_no_results_message(self) -> None:
        """A non-matching query renders a friendly empty state."""
        resp = self.client.get("/search/", {"q": "notarealtermxyz"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "No results")

    def test_draft_pages_excluded(self) -> None:
        """Unpublished pages never appear in results."""
        draft = NewsPage(
            title="Zuluwidget draft",
            slug="zuluwidget-draft",
            description="zuluwidget secret draft",
            image=create_test_image(),
            live=False,
        )
        self.news_index.add_child(instance=draft)
        call_command("update_index", stdout=StringIO())
        resp = self.client.get("/search/", {"q": "zuluwidget"})
        self.assertNotContains(resp, "Zuluwidget draft")

    def test_facet_filter_narrows_to_type(self) -> None:
        """Selecting a type facet restricts results to that page type."""
        resp = self.client.get("/search/", {"q": "influenza", "type": "news"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Influenza surveillance update")

    def test_headline_count_follows_the_selected_facet(self) -> None:
        """The count above the list describes the list, not every matching type."""
        unfiltered = self.client.get("/search/", {"q": "wastewater monitoring"})
        self.assertEqual(unfiltered.context["shown"], unfiltered.context["total"])

        filtered = self.client.get("/search/", {"q": "wastewater monitoring", "type": "pages"})
        self.assertEqual(filtered.context["shown"], 1)
        self.assertEqual(filtered.context["total"], unfiltered.context["total"])
        self.assertGreater(filtered.context["total"], filtered.context["shown"])

    def test_autocomplete_returns_title_matches(self) -> None:
        """Autocomplete returns a partial listing pages whose title prefix matches."""
        resp = self.client.get("/search/autocomplete/", {"q": "influenza"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Influenza surveillance update")
        self.assertContains(resp, self.article.url)

    def test_autocomplete_blank_query_is_empty(self) -> None:
        """A blank query yields no suggestions."""
        resp = self.client.get("/search/autocomplete/", {"q": ""})
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Influenza surveillance update")

    def test_autocomplete_offers_full_search_when_no_title_match(self) -> None:
        """A term matching no page title still offers a link to the full search."""
        resp = self.client.get("/search/autocomplete/", {"q": "zuluwidget"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Search for")
        self.assertContains(resp, "q=zuluwidget")
        self.assertNotContains(resp, "Influenza surveillance update")

    def test_header_has_search_form(self) -> None:
        """Every page's header exposes a no-JS search form posting to /search/."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'action="/search/"')
        self.assertContains(resp, 'name="q"')

    def test_page_without_image_renders(self) -> None:
        """A matching page whose model has no image field renders without error."""
        resp = self.client.get("/search/", {"q": "preparedness"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Preparedness overview")

    def test_dashboard_subclass_is_labelled(self) -> None:
        """A DashboardPage subclass is labelled, not left with a blank badge."""
        self.assertEqual(page_type_label(self.slu), "Dashboards")

    def test_slu_subpage_groups_with_dashboards(self) -> None:
        """SLU subpages share the dashboards facet rather than getting their own."""
        self.assertEqual(page_type_label(self.slu_subpage), "Dashboards")

    def test_singleton_pages_group_under_pages(self) -> None:
        """Singleton pages share the generic "Pages" facet."""
        self.assertEqual(page_type_label(self.publications), "Pages")

    def test_same_title_different_types_are_distinguishable(self) -> None:
        """Two pages sharing a title are told apart by their type label."""
        resp = self.client.get("/search/", {"q": "wastewater monitoring"})
        self.assertEqual(resp.status_code, 200)
        titles = [item["title"] for item in resp.context["items"]]
        self.assertEqual(titles.count("Wastewater monitoring"), 2)
        self.assertEqual(
            {item["label"] for item in resp.context["items"]},
            {"Dashboards", "Pages"},
        )

    def test_newly_added_page_types_are_searchable(self) -> None:
        """Page types added after the initial indexing pass are indexed too."""
        resp = self.client.get("/search/", {"q": "quixotrap"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Publications")
        self.assertContains(resp, "Wastewater monitoring")

    def test_result_shows_page_location(self) -> None:
        """A nested page's result carries its ancestors, excluding the site home."""
        resp = self.client.get("/search/", {"q": "methodology"})
        self.assertEqual(resp.status_code, 200)
        trails = {
            item["title"]: [a["title"] for a in item["ancestors"]] for item in resp.context["items"]
        }
        self.assertEqual(trails["Methodology"], ["Wastewater monitoring"])
        self.assertContains(resp, "Wastewater monitoring")

    def test_listing_pages_are_left_out_of_the_location(self) -> None:
        """Index pages are containers the badge already implies, so they are dropped."""
        resp = self.client.get("/search/", {"q": "quixotrap"})
        items = {item["title"]: item for item in resp.context["items"]}
        dashboard = items["Wastewater monitoring"]
        self.assertEqual(dashboard["label"], "Dashboards")
        self.assertEqual(dashboard["ancestors"], [])

    def test_location_keeps_searchable_ancestors(self) -> None:
        """An ancestor that is itself a content page is named, not dropped."""
        child = BasicPage(title="Funding sources", slug="funding-sources")
        self.basic.add_child(instance=child)
        child.save_revision().publish()
        call_command("update_index", stdout=StringIO())

        resp = self.client.get("/search/", {"q": "funding sources"})
        items = {item["title"]: item for item in resp.context["items"]}
        self.assertEqual(
            [a["title"] for a in items["Funding sources"]["ancestors"]],
            ["Preparedness overview"],
        )

    def test_top_level_page_has_no_location_trail(self) -> None:
        """A page directly under the home page has nothing to disambiguate with."""
        resp = self.client.get("/search/", {"q": "preparedness"})
        items = {item["title"]: item for item in resp.context["items"]}
        self.assertEqual(items["Preparedness overview"]["ancestors"], [])

    def test_autocomplete_labels_suggestions_with_their_type(self) -> None:
        """Dropdown suggestions say what kind of page they are, not just the title."""
        resp = self.client.get("/search/autocomplete/", {"q": "influenza"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Influenza surveillance update")
        self.assertContains(resp, "News")

    def test_oversized_query_does_not_crash_search(self) -> None:
        """A query far longer than the input allows is capped, not a 500."""
        resp = self.client.get("/search/", {"q": " ".join(["a"] * 500)})
        self.assertEqual(resp.status_code, 200)

    def test_oversized_query_does_not_crash_autocomplete(self) -> None:
        """The autocomplete endpoint caps the query too; it is just as reachable."""
        resp = self.client.get("/search/autocomplete/", {"q": " ".join(["a"] * 500)})
        self.assertEqual(resp.status_code, 200)

    def test_query_is_capped_at_the_input_maxlength(self) -> None:
        """The cap matches the maxlength the search inputs advertise."""
        resp = self.client.get("/search/", {"q": "z" * 250})
        self.assertEqual(len(resp.context["query"]), MAX_QUERY_LENGTH)

    def test_result_rendering_does_not_scale_queries_with_results(self) -> None:
        """Ancestors and specific pages are batched, so more hits cost no more queries."""
        for index in range(12):
            page = BasicPage(title=f"Preparedness note {index}", slug=f"preparedness-note-{index}")
            self.home.add_child(instance=page)
            page.save_revision().publish()
        call_command("update_index", stdout=StringIO())

        with CaptureQueriesContext(connection) as few:
            self.client.get("/search/", {"q": "preparedness note 1"})
        with CaptureQueriesContext(connection) as many:
            resp = self.client.get("/search/", {"q": "preparedness note"})

        self.assertGreater(len(resp.context["items"]), 5)
        self.assertEqual(len(many.captured_queries), len(few.captured_queries))

    def test_autocomplete_distinguishes_same_titled_pages(self) -> None:
        """Two same-titled pages are separated by their type in the dropdown."""
        resp = self.client.get("/search/autocomplete/", {"q": "wastewater"})
        self.assertEqual(resp.status_code, 200)
        labels = [result["label"] for result in resp.context["results"]]
        self.assertEqual(sorted(labels), ["Dashboards", "Pages"])
