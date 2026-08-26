"""Tests for the DRR downloads reuse-terms + citation statement (FREYA-2588).

The MVP spec (sections 8-9) requires the licence and citation statement to
cover every download surface — bulk features, the per-compound slice, and the
raw-image link-out — and to render whenever the Downloads section does, even
on a page offering only the raw-image link-out with nothing precomputed.

The imagery clause is the one part scoped to a single surface: it excludes
imagery from these terms, so it appears only where imagery is offered.
"""

from django.test import RequestFactory

from cms.pages.drr_dataset import DrrDatasetPage
from cms.tests.test_drr_dataset_page import UPSTREAM_BIA_URL, DrrDatasetPageTestCase
from cms.tests.test_drr_downloads import DrrDownloadRouteTestCase
from cms.tests.utils import create_test_image, use_temp_media_root

CITATION_DOI = "10.1016/j.isci.2026.116673"
CITATION_AUTHOR = "Asp et al."


class TestDrrReuseTermsWithBulkAndCompoundDownloads(DrrDownloadRouteTestCase):
    """The statement renders alongside the bulk CSV/Parquet and compound-slice surfaces."""

    def test_statement_renders_with_bulk_downloads(self) -> None:
        """The citation, DOI, and licence position all render with the bulk links."""
        self.write_artefacts()

        response = self.client.get(self.page.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Download features (CSV)")
        self.assertContains(response, "Download features (Parquet)")
        self.assertContains(response, "Reuse and citation")
        self.assertContains(response, CITATION_AUTHOR)
        self.assertContains(response, CITATION_DOI)
        self.assertContains(response, "CC BY 4.0")

    def test_statement_does_not_invent_a_licence_for_the_underlying_data(self) -> None:
        """The interim position is stated, not a licence name the portal cannot back."""
        self.write_artefacts()

        response = self.client.get(self.page.url)

        self.assertContains(response, "openly reusable")
        self.assertContains(response, "portal-wide data licence policy")

    def test_imagery_clause_is_withheld_without_a_link_out(self) -> None:
        """No imagery is offered here, so the statement disclaims none."""
        self.write_artefacts()

        response = self.client.get(self.page.url)

        self.assertContains(response, "Reuse and citation")
        self.assertNotContains(response, "EMBL-EBI BioImage Archive")

    def test_statement_renders_when_the_compound_slice_is_also_available(self) -> None:
        """Parquet presence also unlocks the compound-slice route; the statement still covers it."""
        self.write_artefacts()
        self.page.upstream_bia_url = UPSTREAM_BIA_URL
        context = self.page.get_context(RequestFactory().get(self.page.url))
        self.assertIn("compound_base", context["download_urls"])

        response = self.client.get(self.page.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reuse and citation")
        self.assertContains(response, CITATION_DOI)


class TestDrrReuseTermsWithRawImagesOnly(DrrDatasetPageTestCase):
    """The statement must render even when the only surface is the raw-image link-out."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Publish a DRR page with an upstream study but no precomputed artefacts."""
        super().setUpTestData()
        cls.image = create_test_image(title="DRR Reuse Terms", file_name="drr-reuse-terms.jpg")
        cls.page = DrrDatasetPage(
            title="DRR Reuse Terms Raw Only",
            slug="drr-reuse-terms-raw-only",
            description="No precomputed artefacts; only the raw-image link-out.",
            image=cls.image,
            data_status="active",
            upstream_bia_url=UPSTREAM_BIA_URL,
        )
        cls.index.add_child(instance=cls.page)
        cls.page.save_revision().publish()

    def setUp(self) -> None:
        """Redirect ``MEDIA_ROOT`` so no stray artefact directory is picked up."""
        super().setUp()
        self.media_root = use_temp_media_root(self)

    def test_statement_renders_without_any_precomputed_artefact(self) -> None:
        """Only the raw-image button is offered, and the statement still covers it."""
        response = self.client.get(self.page.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="drr-downloads-heading"')
        self.assertContains(response, "Download raw images")
        self.assertNotContains(response, "Download features (CSV)")
        self.assertContains(response, "Reuse and citation")
        self.assertContains(response, CITATION_AUTHOR)
        self.assertContains(response, CITATION_DOI)
        self.assertContains(response, "CC BY 4.0")

    def test_statement_excludes_imagery_from_its_own_terms(self) -> None:
        """Imagery is named as out of scope and pointed at the upstream repository.

        The hosting fact belongs to the FREYA-2581 note further up the section
        and is asserted by ``test_drr_raw_images.py``; what this statement owes
        the reader is whose terms cover the imagery instead of these.
        """
        response = self.client.get(self.page.url)

        self.assertContains(response, "not covered by this statement")
        self.assertContains(response, "EMBL-EBI BioImage Archive study")
        self.assertContains(response, "governed by that repository's own terms")


class TestDrrReuseTermsHiddenWithoutAnyDownloadSurface(DrrDatasetPageTestCase):
    """No download surface at all: neither the section nor the statement renders."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Publish a DRR page with nothing precomputed and no upstream study."""
        super().setUpTestData()
        cls.image = create_test_image(title="DRR No Downloads", file_name="drr-no-downloads.jpg")
        cls.page = DrrDatasetPage(
            title="DRR No Downloads",
            slug="drr-no-downloads",
            description="Nothing precomputed and no upstream study configured.",
            image=cls.image,
            data_status="active",
        )
        cls.index.add_child(instance=cls.page)
        cls.page.save_revision().publish()

    def setUp(self) -> None:
        """Redirect ``MEDIA_ROOT`` so no stray artefact directory is picked up."""
        super().setUp()
        self.media_root = use_temp_media_root(self)

    def test_statement_absent_without_any_download_surface(self) -> None:
        """With no downloads to cover, the statement is withheld along with the section."""
        response = self.client.get(self.page.url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="drr-downloads-heading"')
        self.assertNotContains(response, "Reuse and citation")
        self.assertNotContains(response, CITATION_DOI)
