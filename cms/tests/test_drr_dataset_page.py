"""Tests for DrrDatasetPage and the DrrDatasetData snippet (FREYA-2555, FREYA-2559)."""

import tempfile
from datetime import date, datetime
from pathlib import Path

import polars as pl
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from django.test import RequestFactory, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from wagtail.models import Page, Site
from wagtail.test.utils import WagtailPageTestCase

from cms.pages.dashboard import DashboardPage, DashboardTopic
from cms.pages.dashboard_index import DashboardIndexPage
from cms.pages.drr_dataset import DrrDatasetPage
from cms.pages.home import HomePage
from cms.pages.topics import TopicPage
from cms.pages.topics_index import TopicsIndexPage
from cms.snippets.dashboard_data import DashboardData
from cms.snippets.drr_dataset_data import DrrDatasetData
from cms.tests.test_drr_precompute import FEATURE_CSV, METADATA_TSV
from cms.tests.utils import create_test_image, use_temp_media_root

# A representative, fully-populated summary payload mirroring spec section 7 plus
# the FREYA-2557 reconciliation block. Counts use comma-grouped values so the
# ``intcomma`` render path is asserted unambiguously (Plotly div ids never carry
# commas), and the reconciliation ids are distinctive tokens.
FULL_SUMMARY = {
    "n_compounds": 821,
    "n_plates": 22,
    "n_wells": 7500,
    "n_profiles": 8298,
    "n_features": 1467,
    "pert_type_counts": {"trt": 6800, "negcon": 900, "poscon": 598},
    "compartments": ["nuclei", "cells", "cytoplasm"],
    "channels": ["CONC", "HOECHST", "MITO", "PHAandWGA", "SYTO"],
    "compound_reconciliation": {
        "n_compound_ids": 816,
        "n_control_ids": 5,
        "n_annotated": 651,
        "n_recovered": 34,
        "n_unannotated": 165,
        "unmatched_cbkids": ["CBK000900", "CBK000901"],
    },
    "source": {
        "filename": "datasetForPLS-DA.csv",
        "sha256": "0f1e2d3c4b5a6978",
        "generated_at": "2026-07-11T10:00:00+00:00",
    },
}

# The raw-image 302 target (FREYA-2581). It is an editorial field, so what the
# tests pin is the round trip — the page redirects to whatever is stored — not
# this particular study page.
UPSTREAM_BIA_URL = "https://www.ebi.ac.uk/biostudies/bioimages/studies/S-BIAD2580"


class DrrDatasetPageTestCase(WagtailPageTestCase):
    """Base test case that builds the page tree for DRR dataset tests."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a site with a home page and the Dashboards index page."""
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

        cls.index = DashboardIndexPage(title="Dashboards", slug="dashboards")
        cls.home.add_child(instance=cls.index)
        cls.index.save_revision().publish()


class TestDrrDatasetPageModel(DrrDatasetPageTestCase):
    """Tests for the DrrDatasetPage model fields and placement rules."""

    def test_only_creatable_under_dashboard_index(self) -> None:
        """DrrDatasetPage is allowed under the Dashboards index, not the home page."""
        self.assertCanCreateAt(DashboardIndexPage, DrrDatasetPage)
        self.assertCanNotCreateAt(HomePage, DrrDatasetPage)

    def test_dashboard_index_allows_drr_dataset_page(self) -> None:
        """The Dashboards index registers DrrDatasetPage as an allowed child."""
        self.assertIn("cms.DrrDatasetPage", DashboardIndexPage.subpage_types)

    def test_subpage_types_empty(self) -> None:
        """DrrDatasetPage is a leaf page and cannot have children."""
        self.assertEqual(DrrDatasetPage.subpage_types, [])

    def test_organism_defaults_to_sars_cov_2(self) -> None:
        """The organism field defaults to SARS-CoV-2 for the first dataset."""
        field = DrrDatasetPage._meta.get_field("organism")
        self.assertEqual(field.default, "SARS-CoV-2")


class TestDrrDatasetData(DrrDatasetPageTestCase):
    """Tests for the DrrDatasetData snippet lookup contract."""

    def test_get_data_returns_none_when_absent(self) -> None:
        """get_data returns None when no row matches the slug."""
        self.assertIsNone(DrrDatasetData.get_data("missing-slug"))

    def test_get_data_round_trip(self) -> None:
        """get_data returns the row whose dataset_slug matches."""
        row = DrrDatasetData.objects.create(dataset_slug="sars-cov2-a549-ace2-validation")
        self.assertEqual(DrrDatasetData.get_data("sars-cov2-a549-ace2-validation").pk, row.pk)


class TestDrrDatasetPageContext(DrrDatasetPageTestCase):
    """Tests that DrrDatasetPage sources figures and summary from DrrDatasetData."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Add a DRR dataset page under the Dashboards index."""
        super().setUpTestData()
        cls.image = create_test_image(title="DRR Image", file_name="drr.jpg")
        cls.page = DrrDatasetPage(
            title="SARS-CoV-2 A549-ACE2 Validation Cell Painting",
            slug="sars-cov2-a549-ace2-validation",
            description="Validation Cell Painting antiviral screen.",
            image=cls.image,
            data_status="active",
            cell_line="A549-ACE2",
        )
        cls.index.add_child(instance=cls.page)
        cls.page.save_revision().publish()

    def test_context_pulls_figures_and_summary_from_drr_dataset_data(self) -> None:
        """get_context exposes DrrDatasetData figures and the summary payload."""
        DrrDatasetData.objects.create(
            dataset_slug="sars-cov2-a549-ace2-validation",
            data={"pca": {"data": [], "layout": {}}},
            summary={"n_compounds": 42},
        )

        request = RequestFactory().get(self.page.url)
        context = self.page.get_context(request)

        self.assertIn("pca", context["figures"])
        self.assertEqual(context["summary"], {"n_compounds": 42})

    def test_context_handles_missing_drr_dataset_data(self) -> None:
        """get_context degrades gracefully when no DrrDatasetData row exists."""
        request = RequestFactory().get(self.page.url)
        context = self.page.get_context(request)

        self.assertEqual(context["figures"], {})
        self.assertEqual(context["summary"], {})

    def test_page_serves_via_template(self) -> None:
        """A published DrrDatasetPage renders (HTTP 200) via the inherited dashboard template."""
        response = self.client.get(self.page.url)
        self.assertEqual(response.status_code, 200)


class TestDrrDatasetPageRender(DrrDatasetPageTestCase):
    """Rendered-HTML tests for the DRR dataset template (spec section 9 / 10)."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Add a published DRR dataset page carrying a single PCA figure block."""
        super().setUpTestData()
        cls.image = create_test_image(title="DRR Render", file_name="drr-render.jpg")
        cls.page = DrrDatasetPage(
            title="SARS-CoV-2 A549-ACE2 Validation Cell Painting",
            slug="sars-cov2-a549-ace2-validation",
            description="Validation Cell Painting antiviral screen.",
            image=cls.image,
            data_status="active",
            cell_line="A549-ACE2",
            screen_type="Validation Cell Painting",
            upstream_accession="S-BIAD2580",
            content=[
                ("plotly_figure", {"figure_id": "pca", "alt_text": "PCA plot", "height": 500}),
            ],
        )
        cls.index.add_child(instance=cls.page)
        cls.page.save_revision().publish()

    def setUp(self) -> None:
        """Clear the per-figure HTML cache so figure assertions are hermetic."""
        super().setUp()
        cache.clear()

    def test_populated_page_renders_metadata_summary_and_figure(self) -> None:
        """A populated DrrDatasetData renders metadata, the summary panel, and the figure."""
        DrrDatasetData.objects.create(
            dataset_slug="sars-cov2-a549-ace2-validation",
            data={"pca": {"data": [], "layout": {}}},
            summary=FULL_SUMMARY,
            source_file_hash="deadbeefcafe0000",
            data_updated_at=date(2026, 7, 10),
        )

        response = self.client.get(self.page.url)
        self.assertEqual(response.status_code, 200)

        # Header and dataset metadata.
        self.assertContains(response, "SARS-CoV-2")
        self.assertContains(response, "A549-ACE2")
        self.assertContains(response, "Validation Cell Painting")
        self.assertContains(response, "S-BIAD2580")
        self.assertContains(response, "Data last updated")
        self.assertContains(response, "July 10, 2026")

        # Summary counts (intcomma-formatted; commas never appear in Plotly div ids).
        self.assertContains(response, "Summary statistics")
        self.assertContains(response, "8,298")  # n_profiles
        self.assertContains(response, "1,467")  # n_features
        self.assertContains(response, "7,500")  # n_wells

        # Perturbation types plus compartments / channels.
        self.assertContains(response, "Perturbation types")
        self.assertContains(response, "6,800")  # trt count
        self.assertContains(response, "nuclei, cells, cytoplasm")
        self.assertContains(response, "CONC, HOECHST, MITO, PHAandWGA, SYTO")

        # Compound-metadata reconciliation block (FREYA-2557).
        self.assertContains(response, "Compound metadata reconciliation")
        self.assertContains(response, "651")  # n_annotated
        self.assertContains(response, "165")  # n_unannotated
        self.assertContains(response, "Unannotated compound IDs (2)")
        self.assertContains(response, "CBK000900, CBK000901")

        # Source provenance.
        self.assertContains(response, "datasetForPLS-DA.csv")
        self.assertContains(response, "0f1e2d3c4b5a6978")

        # Figure rendered server-side through the inherited PlotlyFigureBlock path.
        self.assertContains(response, 'class="plotly-figure"')
        self.assertContains(response, 'aria-label="PCA plot"')

    def test_figure_falls_back_when_figure_json_missing(self) -> None:
        """With no precomputed figure JSON the block shows its unavailable-data fallback."""
        response = self.client.get(self.page.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Chart data is not available for this figure.")
        self.assertNotContains(response, 'class="plotly-figure"')

    def test_summary_panel_hidden_without_data(self) -> None:
        """The summary panel is omitted entirely when no DrrDatasetData exists."""
        response = self.client.get(self.page.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Summary statistics")


class TestDrrDatasetDownloadsWired(DrrDatasetPageTestCase):
    """Inverts the transitional contract now that FREYA-2580 wires ``download_urls``.

    Route behaviour is covered by ``test_drr_downloads.py`` and
    ``test_drr_raw_images.py``; what this asserts is the page-context payload
    spec section 10 requires of this file. The fixture names no upstream study,
    so the raw-image link-out (FREYA-2581) is advertised only where a test sets
    one.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Add a published DRR dataset page for the downloads-context checks."""
        super().setUpTestData()
        cls.image = create_test_image(title="DRR Wired", file_name="drr-wired.jpg")
        cls.page = DrrDatasetPage(
            title="DRR Downloads Wired",
            slug="drr-downloads-wired",
            description="Downloads are served from precomputed artefacts.",
            image=cls.image,
            data_status="active",
        )
        cls.index.add_child(instance=cls.page)
        cls.page.save_revision().publish()

    def setUp(self) -> None:
        """Redirect ``MEDIA_ROOT`` and stand in for a precompute run."""
        super().setUp()
        artefacts = use_temp_media_root(self) / "drr" / self.page.slug
        artefacts.mkdir(parents=True)
        (artefacts / "features.csv").write_text("cbkid\nCBK1\n", encoding="utf-8")
        (artefacts / "features.parquet").write_bytes(b"PAR1")

    def test_download_urls_present_in_context(self) -> None:
        """get_context advertises the feature downloads and the raw-image link-out."""
        self.page.upstream_bia_url = UPSTREAM_BIA_URL
        request = RequestFactory().get(self.page.url)
        context = self.page.get_context(request)
        self.assertEqual(
            sorted(context["download_urls"]), ["compound_base", "csv", "parquet", "raw_images"]
        )
        self.assertIn("raw-images/", context["download_urls"]["raw_images"])

    def test_downloads_section_rendered_with_data(self) -> None:
        """The downloads markup goes live; no upstream study, no raw-image button."""
        DrrDatasetData.objects.create(
            dataset_slug="drr-downloads-wired",
            summary={"n_compounds": 1},
            data={},
        )
        response = self.client.get(self.page.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="drr-downloads-heading"')
        self.assertContains(response, "Download features (CSV)")
        self.assertNotContains(response, "Download raw images")


class TestDrrCompoundPicker(DrrDatasetPageTestCase):
    """The on-page compound picker (FREYA-2583, spec section 9).

    Options are read from ``compounds.parquet`` and submitted to the
    per-compound slice, so the pair these assert is: every option the page
    offers is an id the route can serve, and every id it can serve is offered.
    That each one downloads is ``test_drr_compound_download.py``'s.

    The fixture mirrors the real index's shape rather than only the three
    columns the picker reads — including ``pert_iname``, which FREYA-2628 put
    there and which this control deliberately does not label from.
    """

    COMPOUND_INDEX_ROWS = {
        "cbkid": ["CBK1", "CBK2", "CBK3", "[stau]"],
        "cbkid_normalized": ["CBK1", "CBK2", "CBK3", None],
        "kind": ["compound", "compound", "compound", "control"],
        "n_profiles": [2, 1, 1, 1],
        "name": ["Remdesivir", "aloxistatin", None, None],
        "broad_moa": ["antiviral", "cathepsin inhibitor", None, None],
        "pert_iname": ["gs-5734", "e-64d", None, "staurosporine"],
    }

    # Compounds first, then by label case-insensitively: an ASCII sort would put
    # both capitalised labels ahead of "aloxistatin", so this pins the rule
    # rather than the accident of the fixture's spelling.
    EXPECTED_LABELS = [
        "aloxistatin (CBK2)",
        "CBK3",
        "Remdesivir (CBK1)",
        "[stau] (control)",
    ]

    @classmethod
    def setUpTestData(cls) -> None:
        """Publish a DRR dataset page to hang the picker off."""
        super().setUpTestData()
        cls.image = create_test_image(title="DRR Picker", file_name="drr-picker.jpg")
        cls.page = DrrDatasetPage(
            title="DRR Compound Picker",
            slug="drr-compound-picker",
            description="Per-compound downloads are chosen on the page.",
            image=cls.image,
            data_status="active",
        )
        cls.index.add_child(instance=cls.page)
        cls.page.save_revision().publish()

    def setUp(self) -> None:
        """Redirect ``MEDIA_ROOT`` to a temp dir and create the artefact directory."""
        super().setUp()
        self.artefacts = use_temp_media_root(self) / "drr" / self.page.slug
        self.artefacts.mkdir(parents=True)

    def write_feature_table(self) -> None:
        """Write the ``features.parquet`` the per-compound slice reads."""
        pl.DataFrame(
            {
                "cbkid": ["CBK1", "CBK1", "CBK2", "CBK3", "[stau]"],
                "Metadata_Barcode": ["P1", "P1", "P2", "P2", "P2"],
                "AreaShape_Area_nuclei": [1.0, 1.2, 0.9, 1.1, 1.5],
            }
        ).write_parquet(self.artefacts / "features.parquet")

    def write_compound_index(self, rows: dict[str, list] | None = None) -> None:
        """Write ``compounds.parquet``.

        Args:
            rows: Column-oriented index rows; the class fixture when omitted.
        """
        pl.DataFrame(rows or self.COMPOUND_INDEX_ROWS).write_parquet(
            self.artefacts / "compounds.parquet"
        )

    def compounds(self) -> list[dict[str, str]]:
        """Return the picker options this page currently offers."""
        request = RequestFactory().get(self.page.url)
        return self.page.get_context(request).get("compounds", [])

    def test_options_carry_the_label_rule_and_a_deterministic_order(self) -> None:
        """Annotated, unannotated and control ids each get their own label form."""
        self.write_feature_table()
        self.write_compound_index()

        self.assertEqual([option["label"] for option in self.compounds()], self.EXPECTED_LABELS)

    def test_every_downloadable_compound_is_offered_exactly_once(self) -> None:
        """The option set is the feature table's ``cbkid`` set: nothing hidden, nothing spurious."""
        self.write_feature_table()
        self.write_compound_index()

        offered = [option["cbkid"] for option in self.compounds()]

        self.assertEqual(len(offered), len(set(offered)))
        self.assertEqual(
            set(offered),
            set(pl.read_parquet(self.artefacts / "features.parquet")["cbkid"].to_list()),
        )

    def test_order_does_not_depend_on_the_artefact_row_order(self) -> None:
        """A re-ordered index renders the same options in the same order."""
        self.write_feature_table()
        self.write_compound_index()
        expected = self.compounds()

        reversed_rows = {
            column: list(reversed(values)) for column, values in self.COMPOUND_INDEX_ROWS.items()
        }
        self.write_compound_index(reversed_rows)

        self.assertEqual(self.compounds(), expected)

    def test_labels_ignore_the_authors_compound_name(self) -> None:
        """``pert_iname`` belongs to FREYA-2628's Table S8 join, not to this label."""
        self.write_feature_table()
        self.write_compound_index()

        labels = " ".join(option["label"] for option in self.compounds())

        self.assertNotIn("gs-5734", labels)
        self.assertNotIn("staurosporine", labels)

    def test_no_options_without_a_compound_index(self) -> None:
        """Downloads can be live while the index is missing; the picker then stays away."""
        self.write_feature_table()

        response = self.client.get(self.page.url)

        self.assertEqual(self.compounds(), [])
        self.assertContains(response, "Download features (Parquet)")
        self.assertNotContains(response, 'name="cbkid"')

    def test_no_options_without_the_feature_table(self) -> None:
        """With nothing to slice there is no per-compound route, so no picker either."""
        self.write_compound_index()

        request = RequestFactory().get(self.page.url)
        context = self.page.get_context(request)

        self.assertNotIn("compounds", context)
        self.assertNotIn("compound_base", context.get("download_urls", {}))

    def test_rendered_picker_submits_the_selection_to_the_slice(self) -> None:
        """A plain GET form posts ``cbkid`` to the per-compound download URL."""
        self.write_feature_table()
        self.write_compound_index()

        response = self.client.get(self.page.url)
        body = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'action="{self.page.url}download/compound/"')
        self.assertContains(response, '<select id="drr-compound" name="cbkid"')
        self.assertEqual(body.count("<option "), len(self.EXPECTED_LABELS))
        for label in self.EXPECTED_LABELS:
            self.assertContains(response, label)
        self.assertContains(response, '<option value="[stau]">')


class TestDashboardIndexDrrCards(DrrDatasetPageTestCase):
    """The Dashboards index must resolve DRR children to their specific class (FREYA-2584).

    ``DashboardIndexPage.get_context`` listed its cards from
    ``DashboardPage.objects``, which instantiates base ``DashboardPage`` rows, so
    a ``DrrDatasetPage`` child lost its ``dashboard_data`` override and resolved
    to ``DashboardData`` — the wrong snippet model. Both consumers of that value
    were wrong for DRR cards: the card date and the index sort key.
    """

    # The DRR page is published long before either data date, so a card reading
    # its publish date — the defect's symptom — sorts last instead of first. The
    # publish date is still the fallback when nothing is precomputed.
    DRR_PUBLISHED_ON = date(2024, 1, 15)
    PLAIN_DATA_DATE = date(2026, 6, 1)
    DRR_DATA_DATE = date(2026, 7, 11)

    @classmethod
    def setUpTestData(cls) -> None:
        """Add one DRR dataset card and one plain dashboard card to the index."""
        super().setUpTestData()
        cls.drr_page = cls._add_drr_page("drr-index-card", "DRR Index Card")
        DrrDatasetPage.objects.filter(pk=cls.drr_page.pk).update(
            first_published_at=timezone.make_aware(
                datetime(
                    cls.DRR_PUBLISHED_ON.year,
                    cls.DRR_PUBLISHED_ON.month,
                    cls.DRR_PUBLISHED_ON.day,
                    12,
                )
            )
        )
        cls.plain_page = cls._add_plain_page("plain-index-card", "Plain Index Card")

        cls.topics_index = TopicsIndexPage(title="Topics", slug="topics")
        cls.home.add_child(instance=cls.topics_index)
        cls.topic = TopicPage(
            title="Cell Painting",
            slug="cell-painting",
            description="Image-based morphological profiling.",
            image=create_test_image(title="Topic", file_name="topic.jpg"),
        )
        cls.topics_index.add_child(instance=cls.topic)
        cls.topic.save_revision().publish()
        DashboardTopic.objects.create(page=cls.drr_page, topic=cls.topic)

    @classmethod
    def _add_drr_page(cls, slug: str, title: str) -> DrrDatasetPage:
        """Publish a DRR dataset page under the Dashboards index."""
        page = DrrDatasetPage(
            title=title,
            slug=slug,
            description="A DRR dataset card in the Dashboards index.",
            image=create_test_image(title=title, file_name=f"{slug}.jpg"),
            data_status="active",
            cell_line="A549-ACE2",
        )
        cls.index.add_child(instance=page)
        page.save_revision().publish()
        return page

    @classmethod
    def _add_plain_page(cls, slug: str, title: str) -> DashboardPage:
        """Publish a plain dashboard page under the Dashboards index."""
        page = DashboardPage(
            title=title,
            slug=slug,
            description="A plain dashboard card in the Dashboards index.",
            image=create_test_image(title=title, file_name=f"{slug}.jpg"),
            data_status="active",
        )
        cls.index.add_child(instance=page)
        page.save_revision().publish()
        return page

    def _cards(self, query: str = "") -> list[DashboardPage]:
        """Return the index's card list, in the order the index renders it."""
        request = RequestFactory().get(f"/dashboards/{query}")
        return self.index.get_context(request)["dashboards_list"]

    def _card(self, slug: str) -> DashboardPage:
        """Return a single card by slug, failing the test when it is absent."""
        cards = {page.slug: page for page in self._cards()}
        self.assertIn(slug, cards)
        return cards[slug]

    def test_index_card_uses_drr_data_date(self) -> None:
        """A DRR card carries ``DrrDatasetData.data_updated_at`` as its date."""
        DrrDatasetData.objects.create(
            dataset_slug=self.drr_page.slug,
            data_updated_at=self.DRR_DATA_DATE,
        )

        card = self._card(self.drr_page.slug)

        self.assertIsInstance(card, DrrDatasetPage)
        self.assertEqual(card.dashboard_data_updated_at, self.DRR_DATA_DATE)

    def test_index_sorts_drr_card_by_its_own_date(self) -> None:
        """The sort key reads the DRR date too, not just the rendered card date."""
        DashboardData.objects.create(
            dashboard_slug=self.plain_page.slug,
            data_updated_at=self.PLAIN_DATA_DATE,
        )
        DrrDatasetData.objects.create(
            dataset_slug=self.drr_page.slug,
            data_updated_at=self.DRR_DATA_DATE,
        )

        self.assertEqual(
            [page.slug for page in self._cards()],
            [self.drr_page.slug, self.plain_page.slug],
        )

    def test_index_breaks_a_date_tie_on_title(self) -> None:
        """Newest first, then title — the tie-break holds across both card types.

        Two plain cards share the DRR card's date, so this pins the DRR card's
        position *within* a tie rather than merely ahead of an older card, and
        pins plain-to-plain order at the same time.
        """
        alpha = self._add_plain_page("alpha-tie-card", "Alpha Tie Card")
        zulu = self._add_plain_page("zulu-tie-card", "Zulu Tie Card")
        for page in (alpha, zulu):
            DashboardData.objects.create(
                dashboard_slug=page.slug,
                data_updated_at=self.DRR_DATA_DATE,
            )
        DashboardData.objects.create(
            dashboard_slug=self.plain_page.slug,
            data_updated_at=self.PLAIN_DATA_DATE,
        )
        DrrDatasetData.objects.create(
            dataset_slug=self.drr_page.slug,
            data_updated_at=self.DRR_DATA_DATE,
        )

        self.assertEqual(
            [page.slug for page in self._cards()],
            [alpha.slug, self.drr_page.slug, zulu.slug, self.plain_page.slug],
        )

    def test_index_card_without_precompute_uses_the_publication_date(self) -> None:
        """No ``DrrDatasetData`` row: the card falls back to ``first_published_at``.

        A DRR card reaches the portal-wide fallback that ``4a8d9df`` ("Add
        fallback date if dashboard don't have data entry", PR 83) added, through
        its own snippet lookup returning nothing. It is the publish date pinned
        by this class, not a plain dashboard's, so the fallback is reached via
        the DRR ``dashboard_data`` override rather than around it.
        """
        card = self._card(self.drr_page.slug)

        self.assertIsNone(card.dashboard_data)
        self.assertEqual(card.dashboard_data_updated_at, self.DRR_PUBLISHED_ON)

    def test_precompute_less_page_still_shows_a_data_date_line(self) -> None:
        """The same rule on the page itself: no row, but the publish date stands in."""
        response = self.client.get(self.drr_page.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Data last updated")

    def test_plain_dashboard_keeps_the_publication_date_fallback(self) -> None:
        """The shared fallback is unchanged: a plain card falls back to its publish date."""
        card = self._card(self.plain_page.slug)

        self.assertIsNone(card.dashboard_data)
        self.assertEqual(
            card.dashboard_data_updated_at, timezone.localdate(card.first_published_at)
        )

    def test_plain_dashboard_card_date_is_unchanged(self) -> None:
        """The shared-code guard: a plain dashboard card still reads ``DashboardData``."""
        DashboardData.objects.create(
            dashboard_slug=self.plain_page.slug,
            data_updated_at=self.PLAIN_DATA_DATE,
        )

        card = self._card(self.plain_page.slug)

        self.assertNotIsInstance(card, DrrDatasetPage)
        self.assertEqual(card.dashboard_data_updated_at, self.PLAIN_DATA_DATE)

    def test_index_filters_still_narrow_the_card_list(self) -> None:
        """Search, status and topic filters are untouched: they query base-model fields."""
        self.assertEqual(
            [page.slug for page in self._cards("?search=plain")],
            [self.plain_page.slug],
        )
        self.assertEqual(
            [page.slug for page in self._cards(f"?topic={self.topic.slug}")],
            [self.drr_page.slug],
        )
        self.assertEqual(self._cards("?type=historic"), [])

    def test_index_query_count_does_not_grow_per_card(self) -> None:
        """``.specific()`` costs a fixed number of queries, not one per card.

        Each card already costs one snippet lookup, through
        ``dashboard_data_updated_at`` in the sort key — that predates this
        change. What is pinned here is that resolving cards to their specific
        class adds nothing per card on top of it.
        """
        with CaptureQueriesContext(connection) as captured:
            self._cards()
        baseline = len(captured.captured_queries)

        self._add_drr_page("drr-index-card-2", "DRR Index Card 2")
        self._add_plain_page("plain-index-card-2", "Plain Index Card 2")

        with self.assertNumQueries(baseline + 2):
            self.assertEqual(len(self._cards()), 4)


class TestDrrDatasetSliceAcceptance(DrrDatasetPageTestCase):
    """End-to-end: precompute artefacts drive a live DRR page render (spec section 10)."""

    def setUp(self) -> None:
        """Clear the per-figure HTML cache before the end-to-end render."""
        super().setUp()
        cache.clear()

    def test_precompute_output_renders_on_the_page(self) -> None:
        """drr_precompute output reaches the page: summary, reconciliation, and figure."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        input_path = base / "features.csv"
        input_path.write_text(FEATURE_CSV, encoding="utf-8")
        metadata_path = base / "metadata.tsv"
        metadata_path.write_text(METADATA_TSV, encoding="utf-8")
        media = base / "media"

        slug = "drr-acceptance-slice"
        with override_settings(MEDIA_ROOT=str(media)):
            call_command(
                "drr_precompute",
                slug=slug,
                input=str(input_path),
                metadata=str(metadata_path),
                title="Acceptance DRR",
            )

            image = create_test_image(title="DRR Acceptance", file_name="drr-acc.jpg")
            page = DrrDatasetPage(
                title="Acceptance DRR",
                slug=slug,
                description="End-to-end acceptance slice.",
                image=image,
                data_status="active",
                cell_line="A549-ACE2",
                content=[
                    ("plotly_figure", {"figure_id": "pca", "alt_text": "PCA plot", "height": 500}),
                ],
            )
            self.index.add_child(instance=page)
            page.save_revision().publish()

            response = self.client.get(page.url)

        self.assertEqual(response.status_code, 200)

        # The precompute upserted a data row the page reads by slug.
        row = DrrDatasetData.get_data(slug)
        self.assertIsNotNone(row)
        self.assertEqual(row.summary["n_compounds"], 3)
        self.assertEqual(row.summary["n_plates"], 2)
        self.assertIn("pca", row.data)

        # The precomputed summary, reconciliation, and figure all reach the page.
        self.assertContains(response, "Summary statistics")
        self.assertContains(response, "Compound metadata reconciliation")
        self.assertContains(response, "CBK3")  # the fixture's unmatched compound id
        self.assertContains(response, "Unannotated compound IDs (1)")
        self.assertContains(response, 'class="plotly-figure"')
