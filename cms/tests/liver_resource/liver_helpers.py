"""Shared helpers for liver resource dashboard tests."""

from __future__ import annotations

from django.core.files.uploadedfile import SimpleUploadedFile
from wagtail.documents import get_document_model
from wagtail.models import Page, Site

from cms.pages.dashboard_index import DashboardIndexPage
from cms.pages.home import HomePage
from cms.pages.liver_resource import LiverResourceDashboardPage
from cms.tests.utils import create_test_image
from dashboard_visualisation.liver_resource.supplementary import (
    SUPPLEMENTARY_DOCUMENT_TITLE,
)


def create_supplementary_document(
    *,
    title: str = SUPPLEMENTARY_DOCUMENT_TITLE,
    file_name: str = "HepaGeNIE_supplementary.xlsx",
    content: bytes = b"PK\x03\x04fake-xlsx",
):
    """Create a Wagtail Document used as the HepaGeNIE supplementary workbook."""
    Document = get_document_model()
    return Document.objects.create(
        title=title,
        file=SimpleUploadedFile(file_name, content, content_type="application/vnd.ms-excel"),
    )


def create_published_liver_resource_page(
    *,
    title: str = "Liver Resource",
    slug: str = "liver-resource",
    description: str = "HepaGeNIE dashboard",
) -> LiverResourceDashboardPage:
    """Create home → dashboards → liver-resource page tree and publish it.

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
        content=[("text", "<p>Upload a limma-style DE file to colour the TLN.</p>")],
    )
    index.add_child(instance=page)
    page.save_revision().publish()
    return page


def liver_route_url(page: LiverResourceDashboardPage, name: str, *args, **kwargs) -> str:
    """Build absolute path for a liver RoutablePageMixin sub-route."""
    return page.url + page.reverse_subpage(name, args=args or None, kwargs=kwargs or None)
