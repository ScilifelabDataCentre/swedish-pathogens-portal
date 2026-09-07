"""Tests for the ``SiteAnnouncement`` snippet, template tag, filter, and render.

The cases below mirror the Representative Scenarios in the plan / spec:
happy path, empty state, single-type render, toggle-off, the external-link
``rel`` merge and its edge cases, the malicious-payload non-escape,
``AlertBlock`` non-regression, and the template-tag DB-error fallback.
"""

import re

from bs4 import BeautifulSoup
from django.test import TestCase
from wagtail.admin.rich_text.converters.contentstate import ContentstateConverter
from wagtail.models import Page, Site

from cms.pages import BasicPage
from cms.snippets import SiteAnnouncement

#######################################################################
#################### Helpers for render scenarios #####################
#######################################################################


_REL_RE: re.Pattern[str] = re.compile(r'rel=[\'"]([^\'"]+)[\'"]')


def _rel_tokens_from_string(html: str) -> set[str]:
    """Return the ``rel`` tokens of the first ``<a>`` element in ``html``.

    The filter emits ``rel="token token"``; this tokeniser is used by the
    unit-level filter tests where we are only concerned with membership
    and duplication, not document order.
    """
    match = _REL_RE.search(html)
    if match is None:
        return set()
    return set(match.group(1).split())


def _editor_sanitised(raw_html: str) -> str:
    """Simulate the Wagtail admin's Draftail sanitisation round-trip.

    When an editor saves a ``RichTextField`` via the admin, the submitted
    HTML is converted to Draftail's ContentState and back, which drops
    elements outside the configured feature set. Tests creating rows via
    ``SiteAnnouncement.objects.create`` bypass the widget, so this helper
    applies the same transformation programmatically.

    Args:
        raw_html (str): HTML a malicious editor might try to paste.

    Returns:
        str: HTML after the ``bold`` / ``italic`` / ``link`` round-trip.
    """
    converter = ContentstateConverter(["bold", "italic", "link"])
    return converter.to_database_format(converter.from_database_format(raw_html))


class _SiteAnnouncementRenderTestCase(TestCase):
    """Base class that sets up a Wagtail site with a renderable page tree.

    The default Wagtail migration tree already installs a root (id=1)
    and a ``home`` page (id=2) bound to the default ``Site``. We reuse
    that home page as the parent so the site's ``root_page`` resolves
    without recreating a fixture, and add ``BasicPage`` children for
    the actual render assertions.
    """

    def setUp(self) -> None:
        """Reuse the default Wagtail home page and add a blank ``BasicPage`` child."""
        self.site = Site.objects.get(is_default_site=True)
        self.home = self.site.root_page
        self.basic_page = self.home.add_child(
            instance=BasicPage(title="Basic", slug="basic", content=[]),
        )

    def _render(self, page: Page | None = None) -> str:
        """Request ``page`` (defaults to ``self.basic_page``) and return the body."""
        target = page or self.basic_page
        response = self.client.get(target.url)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()


#######################################################################
######################### Model-level sanity ##########################
#######################################################################


class SiteAnnouncementModelTests(TestCase):
    """Basic model guarantees: verbose name, ``__str__``, default ordering."""

    def test_verbose_name_is_site_announcement(self):
        """The Meta ``verbose_name`` drives the Wagtail admin sidebar label."""
        self.assertEqual(SiteAnnouncement._meta.verbose_name, "Site announcement")

    def test_str_returns_title(self):
        """``__str__`` returns the title for admin list views."""
        announcement = SiteAnnouncement.objects.create(
            title="Down for maintenance",
            message="<p>hello</p>",
            announcement_type="maintenance",
        )
        self.assertEqual(str(announcement), "Down for maintenance")

    def test_default_queryset_ordering_by_sort_order(self):
        """``Meta.ordering = ['sort_order', '-pk']`` gives deterministic order."""
        SiteAnnouncement.objects.create(
            title="B",
            message="<p>x</p>",
            announcement_type="survey",
            sort_order=2,
        )
        SiteAnnouncement.objects.create(
            title="A",
            message="<p>x</p>",
            announcement_type="survey",
            sort_order=1,
        )
        titles = list(SiteAnnouncement.objects.values_list("title", flat=True))
        self.assertEqual(titles, ["A", "B"])


#######################################################################
##################### End-to-end render behaviour #####################
#######################################################################


class SiteAnnouncementRenderTests(_SiteAnnouncementRenderTestCase):
    """Full render tests: the announcement region surfaces in public pages."""

    def test_happy_path_two_banners_sorted_with_correct_class_map(self):
        """Two enabled banners render in ``sort_order`` with the correct class map.

        Also: one single outer ``<section aria-label="Site announcements">``,
        no ``role="alert"`` on any descendant, no ``aria-live`` attribute,
        a ``<ul role="list">`` wrapper with one ``<li>`` per banner, and a
        leading SVG icon plus ``sr-only`` type label inside each banner.
        """
        SiteAnnouncement.objects.create(
            title="Maintenance one",
            message="<p>Maintenance banner copy</p>",
            announcement_type="maintenance",
            is_enabled=True,
            sort_order=1,
        )
        SiteAnnouncement.objects.create(
            title="Survey one",
            message="<p>Survey banner copy</p>",
            announcement_type="survey",
            is_enabled=True,
            sort_order=2,
        )

        html = self._render()
        soup = BeautifulSoup(html, "html.parser")

        sections = soup.find_all("section", attrs={"aria-label": "Site announcements"})
        self.assertEqual(len(sections), 1)
        section = sections[0]
        self.assertIsNone(section.get("role"))
        self.assertIsNone(section.get("aria-live"))
        self.assertIsNone(section.find(attrs={"role": "alert"}))
        self.assertIsNone(section.find(attrs={"aria-live": True}))

        lists = section.find_all("ul", attrs={"role": "list"})
        self.assertEqual(len(lists), 1)
        items = lists[0].find_all("li", recursive=False)
        self.assertEqual(len(items), 2)

        banners = section.find_all("div", class_="alert")
        self.assertEqual(len(banners), 2)
        self.assertIn("alert-warning", banners[0]["class"])
        self.assertIn("alert-info", banners[1]["class"])

        for banner, expected_label in zip(banners, ["Maintenance:", "Announcement:"], strict=True):
            self.assertIsNotNone(banner.find("svg", attrs={"aria-hidden": "true"}))
            sr_label = banner.find("span", class_="sr-only")
            self.assertIsNotNone(sr_label)
            self.assertEqual(sr_label.get_text(strip=True), expected_label)

    def test_empty_state_renders_no_announcement_section(self):
        """Zero enabled rows → ``<section aria-label>`` absent from the response."""
        SiteAnnouncement.objects.create(
            title="hidden",
            message="<p>hidden body</p>",
            announcement_type="maintenance",
            is_enabled=False,
        )

        html = self._render()

        self.assertNotIn("Site announcements", html)

    def test_single_type_render_shows_only_alert_info(self):
        """Only a survey is enabled → ``alert-info`` present, ``alert-warning`` absent."""
        SiteAnnouncement.objects.create(
            title="just a survey",
            message="<p>Please respond</p>",
            announcement_type="survey",
            is_enabled=True,
        )

        soup = BeautifulSoup(self._render(), "html.parser")

        banners = soup.find_all("div", class_="alert")
        self.assertEqual(len(banners), 1)
        self.assertIn("alert-info", banners[0]["class"])
        self.assertNotIn("alert-warning", banners[0]["class"])

    def test_toggle_off_removes_banner_from_subsequent_response(self):
        """Setting ``is_enabled=False`` makes the banner disappear from public pages."""
        banner = SiteAnnouncement.objects.create(
            title="toggle me",
            message="<p>toggle-banner-marker</p>",
            announcement_type="maintenance",
            is_enabled=True,
        )
        self.assertIn("toggle-banner-marker", self._render())

        banner.is_enabled = False
        banner.save()

        html = self._render()
        self.assertNotIn("toggle-banner-marker", html)
        self.assertNotIn("Site announcements", html)

    def test_external_anchor_in_announcement_gets_rel_tokens(self):
        """An announcement's external anchor renders with ``noopener`` + ``noreferrer``."""
        SiteAnnouncement.objects.create(
            title="ext",
            message='<p>See <a href="https://status.example/page">status</a></p>',
            announcement_type="maintenance",
            is_enabled=True,
        )

        soup = BeautifulSoup(self._render(), "html.parser")

        anchor = soup.find("a", href="https://status.example/page")
        self.assertIsNotNone(anchor)
        self.assertTrue(
            {"noopener", "noreferrer"}.issubset(set(anchor.get("rel") or [])),
        )

    def test_external_anchor_in_announcement_opens_in_new_tab(self):
        """An announcement's external anchor renders with ``target="_blank"``."""
        SiteAnnouncement.objects.create(
            title="ext",
            message='<p>See <a href="https://status.example/">status</a></p>',
            announcement_type="maintenance",
            is_enabled=True,
        )

        soup = BeautifulSoup(self._render(), "html.parser")

        anchor = soup.find("a", href="https://status.example/")
        self.assertIsNotNone(anchor)
        self.assertEqual(anchor.get("target"), "_blank")

    def test_editor_rel_nofollow_preserved_in_response(self):
        """Editor ``rel="nofollow"`` survives the merge in the rendered response."""
        SiteAnnouncement.objects.create(
            title="partner",
            message=('<p><a href="https://partner.example" rel="nofollow">partner link</a></p>'),
            announcement_type="maintenance",
            is_enabled=True,
        )

        soup = BeautifulSoup(self._render(), "html.parser")

        anchor = soup.find("a", href="https://partner.example")
        self.assertIsNotNone(anchor)
        self.assertEqual(
            set(anchor.get("rel") or []),
            {"nofollow", "noopener", "noreferrer"},
        )

    def test_malicious_payload_is_absent_from_rendered_response(self):
        """Attacker payloads survive neither save nor render.

        Wagtail's Draftail round-trip (``features=[bold, italic, link]``)
        strips ``<script>`` elements and disallowed anchor schemes on
        save; the ``announcement_rich_text`` filter leaves the cleaned
        output alone rather than re-introducing them. We assert that
        ``javascript:``, ``data:text/html``, and ``<script>alert`` are
        all absent from the rendered response.
        """
        dirty = (
            '<p><a href="javascript:alert(1)">x</a>'
            '<a href="data:text/html,x">y</a>'
            "<script>alert(1)</script></p>"
        )
        clean_message = _editor_sanitised(dirty)
        self.assertNotIn("javascript:", clean_message)
        self.assertNotIn("data:text/html", clean_message)
        self.assertNotIn("<script>", clean_message)

        SiteAnnouncement.objects.create(
            title="evil",
            message=clean_message,
            announcement_type="maintenance",
            is_enabled=True,
        )

        html = self._render()

        self.assertNotIn("javascript:", html)
        self.assertNotIn("data:text/html", html)
        self.assertNotIn("<script>alert", html)
