"""Shared helpers for liver resource dashboard tests."""

from __future__ import annotations

from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from wagtail.models import Page, Site

from cms.pages.dashboard_index import DashboardIndexPage
from cms.pages.home import HomePage
from cms.pages.liver_resource import LiverResourceDashboardPage
from cms.snippets.dashboard_data import DashboardData
from cms.tests.utils import create_test_image
from dashboard_visualisation.liver_resource.reference_data import get_data_root


def create_liver_dashboard_data(
    *,
    fixture_name: str = "HCC-Control.txt",
    upload_name: str | None = None,
    data_updated_at: date | None = None,
) -> DashboardData:
    """Create liver DashboardData from a bundled DE fixture (test helper)."""
    fixture_path = get_data_root() / "examples" / fixture_name
    name = upload_name or fixture_name
    upload = SimpleUploadedFile(
        name=name,
        content=fixture_path.read_bytes(),
        content_type="text/plain",
    )
    return DashboardData.objects.create(
        dashboard_title="HepaGeNIE",
        dashboard_slug="hepagenie-tln",
        source_file=upload,
        data_updated_at=data_updated_at or date(2026, 4, 20),
    )


def create_published_liver_resource_page(
    *,
    title: str = "Liver Resource",
    slug: str = "hepagenie-tln",
    description: str = "HepaGeNIE dashboard",
) -> LiverResourceDashboardPage:
    """Create home → dashboards → hepagenie-tln page tree and publish it.

    Also configures the default Site so ``page.url`` / ``reverse_subpage`` work.
    """
    root = Page.get_first_root_node()
    for child in root.get_children():
        child.delete()
    root = Page.get_first_root_node()

    home = HomePage(title="Home", slug="home")
    root.add_child(instance=home)
    Site.objects.update_or_create(
        is_default_site=True,
        defaults={"hostname": "testserver", "root_page": home},
    )

    index = DashboardIndexPage(title="Dashboards", slug="dashboards")
    home.add_child(instance=index)
    index.save_revision().publish()

    image = create_test_image(title="Liver Image", file_name="liver.jpg")
    page = LiverResourceDashboardPage(
        title=title,
        slug=slug,
        description=description,
        image=image,
        data_status="active",
        liver_content=[
            ("text", "<p>Upload a limma-style DE file to colour the TLN.</p>"),
            ("hepagene_panel", None),
        ],
    )
    index.add_child(instance=page)
    page.save_revision().publish()
    return page


def liver_route_url(page: LiverResourceDashboardPage, name: str, *args, **kwargs) -> str:
    """Build absolute path for a liver RoutablePageMixin sub-route."""
    return page.url + page.reverse_subpage(name, args=args or None, kwargs=kwargs or None)
