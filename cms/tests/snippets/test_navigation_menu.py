"""Tests for the navigation menu."""

from django.db import IntegrityError
from django.test import TestCase
from wagtail.models import Page, Site

from cms.snippets import NavigationMainMenu, NavigationMenu, NavigationSubMenu

#######################################################################
############# Helper classes and functions for testing ################
#######################################################################


class TestCaseWithSite(TestCase):
    """A base test case that sets up a Wagtail site for testing."""

    def setUp(self) -> None:
        """Set up test data for tests."""
        self.root = Page.objects.get(id=1)

        Site.objects.update_or_create(
            id=1,
            defaults={
                "hostname": "localhost",
                "root_page": self.root,
                "is_default_site": True,
            },
        )


######################################################################
############### Test suite for NavigationMenu model ##################
######################################################################


class NavigationMenuModelTests(TestCase):
    """Tests for the NavigationMenu model."""

    def test_slug_auto_generated(self):
        """Test that the slug is auto-generated from the title."""
        menu = NavigationMenu.objects.create(title="Main Header", slug="")
        self.assertEqual(menu.slug, "main-header")

    def test_slug_must_be_unique(self):
        """Test that the slug must be unique."""
        NavigationMenu.objects.create(title="Header1", slug="header")

        with self.assertRaises(IntegrityError):
            NavigationMenu.objects.create(title="Header2", slug="header")


#######################################################################
################ Test suite for Menu items validation #################
#######################################################################


class NavigationMenuItemTests(TestCaseWithSite):
    """Tests for the NavigationMainMenu and NavigationSubMenu models."""

    def test_full_menu_structure(self):
        """Test creating a full menu structure with main and sub-menu items."""
        page = self.root.add_child(instance=Page(title="Test Page", slug="test-page"))

        menu = NavigationMenu.objects.create(title="Menu", slug="menu")
        main = NavigationMainMenu.objects.create(parent=menu, title="Main", has_submenu=True)
        sub = NavigationSubMenu.objects.create(parent_menu=main, title="Sub", page=page)

        self.assertEqual(menu.main_menu_items.count(), 1)
        self.assertEqual(main.sub_menu_items.count(), 1)
        self.assertEqual(main.sub_menu_items.first(), sub)
        self.assertEqual(sub.page, page)

    def test_link_with_page(self):
        """Test that the link property returns the correct URL when a page is associated."""
        page = self.root.add_child(instance=Page(title="Test", slug="test"))
        item = NavigationMainMenu(title="Item", page=page)
        self.assertEqual(item.link, "/test/")

    def test_link_without_page(self):
        """Test that the link property returns '#' when no page is associated."""
        item = NavigationMainMenu(title="Item", page=None)
        self.assertEqual(item.link, "#")

    def test_ordering(self):
        """Test that menu items are ordered by sort_order."""
        menu = NavigationMenu.objects.create(title="Menu", slug="menu")

        NavigationMainMenu.objects.create(parent=menu, title="B", sort_order=2)
        NavigationMainMenu.objects.create(parent=menu, title="A", sort_order=1)

        items = menu.main_menu_items.all()

        self.assertEqual(items[0].title, "A")

        for i, k in enumerate(["B", "A"], start=1):
            item = NavigationMainMenu.objects.get(parent=menu, title=k)
            item.sort_order = i
            item.save()

        items = menu.main_menu_items.all()
        self.assertEqual(items[0].title, "B")
