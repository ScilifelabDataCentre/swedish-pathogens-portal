"""Tests for the page section block."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from django.core.exceptions import ValidationError
from django.test import RequestFactory
from django.utils import timezone
from django.utils.text import slugify
from wagtail.models import Page, PageViewRestriction, Site
from wagtail.test.utils import WagtailPageTestCase

from cms.blocks import PageSectionBlock
from cms.pages import HomePage


class TestPageSectionBlock(WagtailPageTestCase):
    """Tests for the PageSectionBlock."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a site setup with a home page and a dashboard index page."""

        root = Page.get_first_root_node()
        for child in root.get_children():
            child.delete()
        root = Page.get_first_root_node()
        cls.home_page = HomePage(title="Home", slug="home")
        root.add_child(instance=cls.home_page)
        Site.objects.update_or_create(
            is_default_site=True, defaults={"hostname": "testserver", "root_page": cls.home_page}
        )
        cls.parent_page = cls.home_page.add_child(instance=Page(title="Parent", slug="parent"))
        cls.parent_page.save_revision().publish()
        cls.request = RequestFactory().get("/")
        cls.block = PageSectionBlock()

    # -------------------------------------------------------------------------------------------
    # Helper methods for setting up test data and context
    # -------------------------------------------------------------------------------------------

    def get_block_value(self, **overrides: dict) -> dict:
        """Return a dict representing the value of the PageSectionBlock with optional overrides."""
        value = {
            "page": self.parent_page,
            "title": "",
            "description": "",
            "order_by": "title",
            "show_badge_in_child_pages": False,
            "show_date_in_child_pages": False,
            "show_topics_in_child_pages": False,
        }
        value.update(overrides)
        return value

    def add_child(self, title: str, slug: str = None) -> Page:
        """Add a child page to the parent page and return it."""
        slug = slug or slugify(title)

        child = self.parent_page.add_child(instance=Page(title=title, slug=slug))
        child.save_revision().publish()

        return child

    def make_mock_child(self, **kwargs: dict) -> SimpleNamespace:
        """Create a mock child page with common PageSectionBlock attributes."""
        defaults = {
            "title": "Child page",
            "description": "Child description",
            "url": "/child-page/",
            "image": None,
        }
        defaults.update(kwargs)

        return SimpleNamespace(**defaults)

    def make_mock_page(
        self, url: str = "/page-url/", live: bool = True, private: bool = False
    ) -> MagicMock:
        """Create a mock page with provisioned attributes."""
        page = MagicMock()
        page.url = url
        page.live = live
        page.get_view_restrictions.return_value.exists.return_value = private

        return page

    def get_context(self, **overrides: dict) -> dict:
        """Return the context for the PageSectionBlock with optional overrides."""
        value = self.get_block_value(**overrides)

        return self.block.get_context(value, {"request": self.request})

    # -------------------------------------------------------------------------------------------
    # Tests for the PageSectionBlock clean() method
    # -------------------------------------------------------------------------------------------

    def test_clean_rejects_draft_page(self):
        """Test that draft pages cannot be selected."""
        draft_page = self.parent_page.add_child(instance=Page(title="Draft", slug="draft"))
        draft_page.unpublish()

        with self.assertRaisesMessage(ValidationError, "Draft pages cannot be selected."):
            self.block.clean({"page": draft_page})

    def test_clean_rejects_private_page(self):
        """Test that private pages cannot be selected."""
        private_page = self.parent_page.add_child(instance=Page(title="Private", slug="private"))
        private_page.save_revision().publish()
        PageViewRestriction.objects.create(page=private_page, restriction_type="password")

        with self.assertRaisesMessage(ValidationError, "Private pages cannot be selected."):
            self.block.clean({"page": private_page})

    def test_clean_accepts_live_public_page(self):
        """Test that live public pages can be selected."""
        public_page = self.parent_page.add_child(instance=Page(title="Public", slug="public"))
        public_page.save_revision().publish()

        value = {"page": public_page}
        cleaned_value = self.block.clean(value)

        self.assertEqual(cleaned_value["page"], public_page)

    # -------------------------------------------------------------------------------------------
    # Tests for the PageSectionBlock get_context() method
    # -------------------------------------------------------------------------------------------

    def test_sets_invalid_page_flag_when_page_is_deleted(self):
        """Test that the block sets the invalid_page flag when the selected page no longer exist."""
        context = self.get_context(page=None)

        self.assertTrue(context.get("invalid_page"))

    def test_sets_invalid_page_flag_when_page_is_not_live(self):
        """Test that the block sets the invalid_page flag when the selected page is not live."""
        draft_page = self.parent_page.add_child(instance=Page(title="Draft", slug="draft"))
        draft_page.unpublish()  # Ensure this page is in draft state

        context = self.get_context(page=draft_page)

        self.assertTrue(context.get("invalid_page"))

    def test_sets_invalid_page_flag_when_page_is_private(self):
        """Test that the block sets the invalid_page flag when the selected page is private."""
        private_page = self.parent_page.add_child(instance=Page(title="Private", slug="private"))
        private_page.save_revision().publish()
        PageViewRestriction.objects.create(page=private_page, restriction_type="password")

        context = self.get_context(page=private_page)

        self.assertTrue(context.get("invalid_page"))

    def test_returns_child_page_details(self):
        """Test that the block returns the expected child page details in the context."""
        child = self.add_child("Child page")

        context = self.get_context()

        self.assertEqual(
            context["section_children"],
            [{"title": child.title, "description": "", "url": child.url, "image": None}],
        )

    def test_only_includes_live_and_public_children(self):
        """Test that the block only includes live and public child pages in the context."""
        live_child = self.add_child("Live page")

        draft_child = self.parent_page.add_child(instance=Page(title="Draft", slug="draft"))
        draft_child.unpublish()  # Ensure this child is in draft state

        private_child = self.parent_page.add_child(instance=Page(title="Private", slug="private"))
        private_child.save_revision().publish()
        PageViewRestriction.objects.create(page=private_child, restriction_type="password")

        context = self.get_context()

        self.assertEqual(
            [child["title"] for child in context["section_children"]], [live_child.title]
        )
        self.assertNotIn(
            draft_child.title, [child["title"] for child in context["section_children"]]
        )
        self.assertNotIn(
            private_child.title, [child["title"] for child in context["section_children"]]
        )

    def test_returns_at_most_three_children(self):
        """Test that the block returns at most three child pages in the context."""
        for index in range(4):
            self.add_child(f"Page {index}")

        context = self.get_context()

        self.assertEqual(len(context["section_children"]), 3)

    def test_orders_children_by_title(self):
        """Test that the block orders child pages by title when specified."""
        self.add_child("Charlie")
        self.add_child("Alpha")
        self.add_child("Bravo")

        context = self.get_context(order_by="title")

        self.assertEqual(
            [child["title"] for child in context["section_children"]], ["Alpha", "Bravo", "Charlie"]
        )

    def test_orders_children_by_created_date(self):
        """Test that the block orders child pages by created date when specified."""
        children = [
            self.add_child("Oldest"),
            self.add_child("Middle"),
            self.add_child("Newest"),
        ]

        base_time = timezone.now()

        for index, child in enumerate(children):
            child.first_published_at = base_time + timedelta(days=index)
            child.save(update_fields=["first_published_at"])

        context = self.get_context(order_by="created")

        self.assertEqual(
            [child["title"] for child in context["section_children"]],
            ["Newest", "Middle", "Oldest"],
        )

    def test_orders_children_by_updated_date(self):
        """Test that the block orders child pages by updated date when specified."""
        children = [
            self.add_child("Oldest"),
            self.add_child("Middle"),
            self.add_child("Newest"),
        ]

        base_time = timezone.now()

        for index, child in enumerate(children):
            child.last_published_at = base_time + timedelta(days=index)
            child.save(update_fields=["last_published_at"])

        context = self.get_context(order_by="updated")

        self.assertEqual(
            [child["title"] for child in context["section_children"]],
            ["Newest", "Middle", "Oldest"],
        )

    def test_orders_children_by_data_updated_date(self):
        """Test that the block orders child pages by data updated date when specified."""
        dashboard_page = self.make_mock_page(url="/dashboard/")

        dashboard_children = []
        page_titles = ["Oldest", "Middle", "Newest"]
        base_time = timezone.now()

        for index, child in enumerate(page_titles):
            dashboard_children.append(
                self.make_mock_child(
                    title=child, dashboard_data_updated_at=base_time + timedelta(days=index)
                )
            )

        qs = dashboard_page.get_children.return_value.live.return_value.public.return_value.specific
        qs.return_value = dashboard_children

        context = self.get_context(page=dashboard_page, order_by="data_updated")

        self.assertEqual(
            [child["title"] for child in context["section_children"]], list(reversed(page_titles))
        )

    def test_unknown_order_by_defaults_to_title(self):
        """Test that an unknown order_by value defaults to ordering by title."""
        self.add_child("Charlie")
        self.add_child("Alpha")
        self.add_child("Bravo")

        context = self.get_context(order_by="does-not-exist")

        self.assertEqual(
            [child["title"] for child in context["section_children"]],
            ["Alpha", "Bravo", "Charlie"],
        )

    def test_includes_data_status_as_badge_for_dashboard(self):
        """Test that dashboard child data status is used as the badge."""
        dashboard_page = self.make_mock_page(url="/dashboard/")

        child = self.make_mock_child(get_data_status_display="Active")

        qs = dashboard_page.get_children.return_value.live.return_value.public.return_value.specific
        qs.return_value = [child]

        context = self.get_context(page=dashboard_page, show_badge_in_child_pages=True)

        self.assertEqual(context["section_children"][0]["badge"], "Active")

    def test_includes_data_status_as_badge_for_highlights(self):
        """Test that highlights child data status is used as the badge."""
        highlights_page = self.make_mock_page(url="/highlights/")

        child = self.make_mock_child(get_article_type_display="Highlights")

        qs = (
            highlights_page.get_children.return_value.live.return_value.public.return_value.specific
        )
        qs.return_value = [child]

        context = self.get_context(page=highlights_page, show_badge_in_child_pages=True)

        self.assertEqual(context["section_children"][0]["badge"], "Highlights")

    def test_does_not_include_badge_for_regular_page_without_type(self):
        """Test that the block does not include a badge in the context when the page has no type."""
        self.add_child("Child page")

        context = self.get_context(show_badge_in_child_pages=True)

        self.assertIsNone(context["section_children"][0]["badge"])

    def test_includes_date_when_enabled(self):
        """Test that the block includes the date in the context when enabled."""
        child = self.add_child("Child page")

        published_at = timezone.now()
        child.first_published_at = published_at
        child.save(update_fields=["first_published_at"])

        context = self.get_context(show_date_in_child_pages=True)

        self.assertEqual(context["section_children"][0]["date"], published_at)

    def test_includes_date_when_enabled_for_dashboard(self):
        """Test that the block includes the date in the context when enabled."""
        dashboard_page = self.make_mock_page(url="/dashboard/")

        published_at = timezone.now()
        child = self.make_mock_child(dashboard_data_updated_at=published_at)

        qs = dashboard_page.get_children.return_value.live.return_value.public.return_value.specific
        qs.return_value = [child]

        context = self.get_context(page=dashboard_page, show_date_in_child_pages=True)

        self.assertEqual(context["section_children"][0]["date"], published_at)

    def test_includes_topics_when_enabled(self):
        """Test that the block includes the topics in the context when enabled."""
        page_w_topics = self.make_mock_page()
        child = self.make_mock_child(topics=["Topic 1", "Topic 2"])

        qs = page_w_topics.get_children.return_value.live.return_value.public.return_value.specific
        qs.return_value = [child]

        context = self.get_context(page=page_w_topics, show_topics_in_child_pages=True)

        self.assertEqual(context["section_children"][0]["topics"], ["Topic 1", "Topic 2"])

    def test_does_not_include_optional_fields_when_disabled(self):
        """Test that the block does not include optional fields in the context when disabled."""
        self.add_child("Child page")

        context = self.get_context()
        child = context["section_children"][0]

        self.assertNotIn("badge", child)
        self.assertNotIn("date", child)
        self.assertNotIn("topics", child)

    def test_handles_missing_optional_child_attributes(self):
        """Test that the block handles missing optional child attributes gracefully."""
        self.add_child("Child page")

        context = self.get_context(show_badge_in_child_pages=True, show_topics_in_child_pages=True)
        child_context = context["section_children"][0]

        self.assertIsNone(child_context["badge"])
        self.assertEqual(child_context["topics"], [])
