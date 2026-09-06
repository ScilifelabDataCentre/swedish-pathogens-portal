"""Tests for site announcements template tags."""

from unittest import mock

from django.test import TestCase

from cms.snippets import SiteAnnouncement
from cms.templatetags.site_announcements import get_site_announcements


class GetSiteAnnouncementsTemplateTagTests(TestCase):
    """Tests for the ``get_site_announcements`` simple_tag."""

    def test_returns_only_enabled_rows_in_sort_order(self):
        """Disabled rows are filtered out; enabled rows are ordered by ``sort_order``."""
        SiteAnnouncement.objects.create(
            title="hidden",
            message="<p>x</p>",
            announcement_type="maintenance",
            is_enabled=False,
            sort_order=0,
        )
        SiteAnnouncement.objects.create(
            title="second",
            message="<p>x</p>",
            announcement_type="survey",
            is_enabled=True,
            sort_order=2,
        )
        SiteAnnouncement.objects.create(
            title="first",
            message="<p>x</p>",
            announcement_type="maintenance",
            is_enabled=True,
            sort_order=1,
        )

        titles = [a.title for a in get_site_announcements()]

        self.assertEqual(titles, ["first", "second"])

    def test_returns_empty_iterable_on_database_exception(self):
        """Broad DB/ORM exception path returns ``SiteAnnouncement.objects.none()``."""
        with mock.patch("cms.templatetags.site_announcements.SiteAnnouncement") as mocked:
            mocked.objects.filter.side_effect = Exception("db exploded")
            mocked.objects.none.return_value = []

            result = get_site_announcements()

        self.assertEqual(list(result), [])
        mocked.objects.none.assert_called_once()
