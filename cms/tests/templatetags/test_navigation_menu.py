"""Test suite for the NavigationMenu templatetags."""

from django.template import Context, Template
from django.test import TestCase
from wagtail.models import Page, Site

from cms.snippets import NavigationMainMenu, NavigationMenu, NavigationSubMenu


class GetMenuTemplateTagTest(TestCase):
    """Tests for the get_menu template tag."""

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

    def test_get_menu_renders(self):
        """Test that the get_menu template tag renders the correct menu."""
        page = self.root.add_child(instance=Page(title="Test", slug="test"))
        menu = NavigationMenu.objects.create(title="Header", slug="header")
        main = NavigationMainMenu.objects.create(parent=menu, title="Main", has_submenu=True)
        sub = NavigationSubMenu.objects.create(parent_menu=main, title="Sub", page=page)  # noqa: F841

        template = Template("""
            {% load navigation_menu %}
            {% get_menu "header" as items %}
            {% for item in items %}
                {{ item.title }}
                {% for sub in item.sub_menu_items.all %}
                    {{ sub.title }}
                {% endfor %}
            {% endfor %}
        """)
        rendered = template.render(Context({}))

        self.assertIn("Main", rendered)
        self.assertIn("Sub", rendered)

    def test_get_menu_missing_slug(self):
        """Test that the get_menu template tag returns an empty list for a missing slug."""
        template = Template("""
            {% load navigation_menu %}
            {% get_menu "missing" as items %}
            {{ items|length }}
        """)

        rendered = template.render(Context({}))
        self.assertIn("0", rendered)
