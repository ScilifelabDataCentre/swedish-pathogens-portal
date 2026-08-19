"""Tests for the DRR raw-image 302 link-out (FREYA-2581, spec section 8).

Raw imagery stays upstream — one plate is a ~228 GiB archive — so ``raw-images/``
redirects to the study the page names and the portal serves no image bytes at
all. The link-out is not a derived artefact, so unlike the feature downloads it
does not wait on ``drr_precompute``; what gates it is the editorial
``upstream_bia_url``, and without one the route 404s and the page advertises
nothing.
"""

import re

from django.test import RequestFactory

from cms.pages.drr_dataset import DrrDatasetPage
from cms.tests.test_drr_dataset_page import UPSTREAM_BIA_URL, DrrDatasetPageTestCase
from cms.tests.utils import create_test_image, use_temp_media_root


class TestDrrRawImageLinkOut(DrrDatasetPageTestCase):
    """The ``raw-images/`` route, and how the page advertises it."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Publish two DRR pages: one naming an upstream study, one without."""
        super().setUpTestData()
        cls.image = create_test_image(title="DRR Raw Images", file_name="drr-raw.jpg")

        cls.page = DrrDatasetPage(
            title="DRR Raw Images",
            slug="drr-raw-images",
            description="Imagery for this screen lives upstream.",
            image=cls.image,
            data_status="active",
            cell_line="A549-ACE2",
            screen_type="Validation Cell Painting",
            upstream_accession="S-BIAD2580",
            upstream_bia_url=UPSTREAM_BIA_URL,
        )
        cls.index.add_child(instance=cls.page)
        cls.page.save_revision().publish()

        cls.unconfigured_page = DrrDatasetPage(
            title="DRR Raw Images Unconfigured",
            slug="drr-raw-images-unconfigured",
            description="No upstream study has been recorded yet.",
            image=cls.image,
            data_status="active",
        )
        cls.index.add_child(instance=cls.unconfigured_page)
        cls.unconfigured_page.save_revision().publish()

    def setUp(self) -> None:
        """Redirect ``MEDIA_ROOT`` so "no imagery lands here" is measurable."""
        super().setUp()
        self.media_root = use_temp_media_root(self)

    def context(self, page: DrrDatasetPage) -> dict:
        """Return one page's context for a plain GET.

        Args:
            page: The page to render the context of.

        Returns:
            dict: The template context.
        """
        return page.get_context(RequestFactory().get(page.url))

    def test_raw_images_redirects_to_the_upstream_study(self) -> None:
        """The route answers 302 with the stored upstream URL, verbatim."""
        response = self.client.get(self.page.url + "raw-images/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], UPSTREAM_BIA_URL)

    def test_no_image_bytes_are_served(self) -> None:
        """The response is a bare redirect: no body, no attachment, no media written."""
        response = self.client.get(self.page.url + "raw-images/")

        self.assertFalse(response.content)
        self.assertFalse(response.has_header("Content-Disposition"))
        self.assertFalse((self.media_root / "drr").exists())

    def test_missing_upstream_url_returns_404(self) -> None:
        """A dataset with no upstream study configured has nothing to redirect to."""
        response = self.client.get(self.unconfigured_page.url + "raw-images/")

        self.assertEqual(response.status_code, 404)

    def test_route_carries_no_dot_and_ends_in_a_slash(self) -> None:
        """The sub-path stays inside Wagtail's page-serving pattern (spec section 2)."""
        self.assertEqual(self.page.reverse_subpage("raw_images"), "raw-images/")

    def test_link_out_is_advertised_before_any_precompute(self) -> None:
        """With no artefacts on disk the link-out is still offered — it is not one."""
        download_urls = self.context(self.page)["download_urls"]

        self.assertEqual(sorted(download_urls), ["raw_images"])
        self.assertEqual(download_urls["raw_images"], self.page.url + "raw-images/")

    def test_link_out_withheld_when_no_upstream_study(self) -> None:
        """Nothing to serve and nothing to link to means no downloads payload."""
        self.assertNotIn("download_urls", self.context(self.unconfigured_page))

    def test_rendered_button_names_the_screen_it_opens(self) -> None:
        """The button links to the route and says whose imagery it opens."""
        response = self.client.get(self.page.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="drr-downloads-heading"')
        self.assertContains(response, "Download raw images")
        self.assertContains(response, f'href="{self.page.url}raw-images/"')
        self.assertContains(response, "stay with the upstream repository")
        self.assertContains(response, "A549-ACE2")
        self.assertContains(response, "Validation Cell Painting")
        self.assertContains(response, "S-BIAD2580")

    def test_button_opens_in_a_new_tab(self) -> None:
        """The link leaves the portal, so it carries the site's new-tab contract.

        ``ExternalLinkNewTabHandler`` applies this to rich text only, and cannot
        see a hardcoded button whose href is an internal route — the outbound hop
        happens in the 302 — so the attributes are set in the template.
        """
        response = self.client.get(self.page.url)

        button = re.search(r'<a href="[^"]*raw-images/"[^>]*>', response.content.decode())
        self.assertIsNotNone(button)
        self.assertIn('target="_blank"', button.group(0))
        self.assertIn("noopener", button.group(0))
        self.assertIn("noreferrer", button.group(0))

    def test_no_template_comment_reaches_the_page(self) -> None:
        """No editorial note leaks into the markup.

        Django's hash-comment form is single-line only: a multi-line one renders
        verbatim, which is how the upstream note's own comment first shipped
        visible text onto the page. Caught in a live render, pinned here.
        """
        response = self.client.get(self.page.url)

        self.assertNotContains(response, "{#")

    def test_nothing_is_rendered_without_an_upstream_study(self) -> None:
        """A precomputed page naming no study shows neither the button nor the note.

        The artefacts are written on purpose. Without them the whole downloads
        section is hidden, both assertions below pass for the wrong reason, and
        the note's own guard goes untested — the note could then appear on a
        precomputed page that has no upstream study to describe.
        """
        artefacts = self.media_root / "drr" / self.unconfigured_page.slug
        artefacts.mkdir(parents=True)
        (artefacts / "features.csv").write_text("cbkid\nCBK1\n", encoding="utf-8")
        (artefacts / "features.parquet").write_bytes(b"PAR1")

        response = self.client.get(self.unconfigured_page.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="drr-downloads-heading"')
        self.assertContains(response, "Download features (CSV)")
        self.assertNotContains(response, "Download raw images")
        self.assertNotContains(response, "stay with the upstream repository")
