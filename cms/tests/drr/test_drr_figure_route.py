"""Tests for the figure swap route and the radar picker (FREYA-2636, spec section 8.3).

One route serves both section 9 controls, because both are the same operation:
return one server-rendered figure partial. What these assert is the boundary
around it — an allow-listed ``figure_id`` that never becomes a path, a ``cbkid``
resolved through the compound index rather than assembled from the request, and
a 404 that leaves the figure already on the page standing.
"""

from __future__ import annotations

import json
from typing import Any

import polars as pl
from django.core.cache import cache
from django.http import HttpResponse

from cms.pages.drr_dataset import DrrDatasetPage
from cms.snippets.drr_dataset_data import DrrDatasetData
from cms.tests.drr.test_drr_dataset_page import DrrDatasetPageTestCase
from cms.tests.utils import create_test_image, use_temp_media_root
from dashboard_visualisation.drr import artefact_key

SLUG = "drr-figure-route"

# The control id's key as precompute derives it, so the fixture cannot drift
# from the sanitiser the run actually uses.
STAU_KEY = artefact_key("[stau]")

# Two figures on the snippet and one radar on disk, which is the split spec
# section 4 draws: one figure per figure_id in the snippet, a keyed set on disk.
SNIPPET_FIGURES = {
    "pca": {"data": [{"type": "scatter", "x": [1.0], "y": [2.0]}], "layout": {}},
    "radar_compound": {
        "data": [{"type": "scatterpolar", "r": [1.0], "theta": ["DNA I"]}],
        "layout": {},
    },
}
RADAR_CAVEAT = (
    "Approximation: computed on this portal's figure basis of 1,144 morphology features, "
    "clipped to ±50, not on the published consensus profiles. The downloads carry all "
    "1,467 features, unclipped."
)
RADAR_ON_DISK = {
    "data": [{"type": "scatterpolar", "r": [9.0], "theta": ["DNA I"]}],
    "layout": {
        "title": {"text": "Radar: Remdesivir (CBK1) vs infected DMSO baseline"},
        "meta": {"caveat": RADAR_CAVEAT},
    },
}
CONTROL_RADAR_ON_DISK = {
    "data": [{"type": "scatterpolar", "r": [3.0], "theta": ["DNA I"]}],
    "layout": {"title": {"text": "Radar: [stau] (control) vs infected DMSO baseline"}},
}

COMPOUND_INDEX_ROWS = {
    "cbkid": ["CBK1", "CBK2", "[stau]"],
    "kind": ["compound", "compound", "control"],
    "name": ["Remdesivir", "aloxistatin", None],
    # CBK2 has no treated well, so precompute wrote it no radar and the picker
    # must not offer it — the index says so with a null key.
    "radar_key": ["CBK1", None, STAU_KEY],
}


class DrrFigureRouteTestCase(DrrDatasetPageTestCase):
    """A published DRR page with artefacts on disk and a data row in place."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Publish a DRR dataset page carrying a placed radar block."""
        super().setUpTestData()
        cls.image = create_test_image(title="DRR Route", file_name="drr-route.jpg")
        cls.page = DrrDatasetPage(
            title="DRR Figure Route",
            slug=SLUG,
            description="Figures are swapped in place.",
            image=cls.image,
            data_status="active",
            content=[
                {
                    "type": "plotly_figure",
                    "value": {
                        "figure_id": "radar_compound",
                        "alt_text": "Radar of morphological change",
                        "height": 640,
                        "caption": "Both radars share one axis ring.",
                    },
                }
            ],
        )
        cls.index.add_child(instance=cls.page)
        cls.page.save_revision().publish()

    def setUp(self) -> None:
        """Point MEDIA_ROOT at a temp dir, write the artefacts, and clear the cache."""
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.artefacts = use_temp_media_root(self) / "drr" / SLUG
        (self.artefacts / "figures" / "radar").mkdir(parents=True)
        self.write_compound_index()
        self.write_radar("CBK1", RADAR_ON_DISK)
        self.write_radar(STAU_KEY, CONTROL_RADAR_ON_DISK)
        self.data = DrrDatasetData.objects.create(
            dataset_slug=SLUG,
            dataset_title="DRR Figure Route",
            data=SNIPPET_FIGURES,
            summary={"n_compounds": 3},
            source_file_hash="hash-one",
        )

    def write_compound_index(self, rows: dict[str, list] | None = None) -> None:
        """Write ``compounds.parquet``, the index the route resolves keys through."""
        pl.DataFrame(rows or COMPOUND_INDEX_ROWS).write_parquet(
            self.artefacts / "compounds.parquet"
        )

    def write_radar(self, key: str, payload: dict[str, Any]) -> None:
        """Write one per-compound radar artefact under ``figures/radar/``."""
        (self.artefacts / "figures" / "radar" / f"{key}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def figure(self, **params: str) -> HttpResponse:
        """GET the figure route with the given query parameters."""
        return self.client.get(self.page.url + "figure/", params)


class DrrFigureRouteTests(DrrFigureRouteTestCase):
    """What the route serves, and what it refuses."""

    def test_each_allow_listed_snippet_figure_is_served(self) -> None:
        """One server-rendered partial per figure the snippet holds."""
        for figure_id in ("pca", "radar_compound"):
            with self.subTest(figure_id=figure_id):
                response = self.figure(figure_id=figure_id)

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "plotly-figure")

    def test_the_partial_is_the_figure_body_and_not_the_page(self) -> None:
        """An htmx swap replaces one block, so the response carries no page chrome."""
        response = self.figure(figure_id="pca")
        body = response.content.decode()

        self.assertIn('id="figure-pca"', body)
        self.assertNotIn("<html", body)
        self.assertNotIn("Downloads", body)

    def test_the_swapped_figure_keeps_the_placed_block_s_editorial_settings(self) -> None:
        """Alt text, caption and height survive the swap, so the page holds its shape."""
        response = self.figure(figure_id="radar_compound", cbkid="CBK1")
        body = response.content.decode()

        self.assertIn("Radar of morphological change", body)
        self.assertIn("Both radars share one axis ring.", body)
        self.assertIn("640px", body)

    def test_the_swapped_figure_carries_its_basis_caveat_as_page_text(self) -> None:
        """The qualification survives the swap, and as wrapping text rather than chart ink.

        Inside the chart it would be a Plotly annotation, which does not wrap
        and is clipped at the plot's edge on a narrow viewport — so the reader
        who most needs the sentence is the one who cannot finish it.
        """
        response = self.figure(figure_id="radar_compound", cbkid="CBK1")

        self.assertContains(response, "1,144 morphology features")
        self.assertContains(response, "all 1,467 features, unclipped")
        self.assertInHTML(
            f'<p class="text-sm text-pp-dark-grey mt-2">{RADAR_CAVEAT}</p>',
            response.content.decode(),
        )

    def test_a_figure_without_a_caveat_renders_no_empty_paragraph(self) -> None:
        """Only a payload that declares one gets the line; the PCA declares none."""
        response = self.figure(figure_id="pca")

        self.assertNotContains(response, "text-sm text-pp-dark-grey mt-2")

    def test_a_figure_id_outside_the_allow_list_is_404_not_a_path_lookup(self) -> None:
        """The id names a key, never a file: an unknown one is refused before any read."""
        (self.artefacts / "figures" / "evil.json").write_text("{}", encoding="utf-8")

        for figure_id in ("evil", "../summary", "summary.json", ""):
            with self.subTest(figure_id=figure_id):
                self.assertEqual(self.figure(figure_id=figure_id).status_code, 404)

    def test_an_allow_listed_figure_the_dataset_lacks_is_404(self) -> None:
        """``umap`` is allow-listed but unprecomputed here, so there is nothing to serve."""
        self.assertEqual(self.figure(figure_id="umap").status_code, 404)

    def test_only_the_radar_takes_a_compound(self) -> None:
        """The heatmap and PCA are single figures; a cbkid on them is a bad request."""
        self.assertEqual(self.figure(figure_id="pca", cbkid="CBK1").status_code, 404)


class DrrRadarSetRouteTests(DrrFigureRouteTestCase):
    """Resolving a reader's compound to the file precompute wrote for it."""

    def test_a_named_compound_is_served_from_the_set(self) -> None:
        """The response is that compound's radar, not the snippet's default."""
        response = self.figure(figure_id="radar_compound", cbkid="CBK1")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Remdesivir (CBK1)")

    def test_a_bracketed_control_id_round_trips_through_the_query_string(self) -> None:
        """``[stau]`` cannot sit in a path segment, which is why it travels as a parameter."""
        response = self.figure(figure_id="radar_compound", cbkid="[stau]")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "[stau] (control)")

    def test_an_unknown_compound_is_404_and_leaves_the_default_standing(self) -> None:
        """The page keeps the radar it already rendered; nothing on it changes."""
        response = self.figure(figure_id="radar_compound", cbkid="CBK404")
        page = self.client.get(self.page.url)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'id="figure-radar_compound"')

    def test_a_compound_with_no_radar_is_404_rather_than_someone_else_s(self) -> None:
        """CBK2 has no treated well, so the index gives it no key and nothing is served."""
        self.assertEqual(self.figure(figure_id="radar_compound", cbkid="CBK2").status_code, 404)

    def test_a_missing_artefact_is_404(self) -> None:
        """An index that names a file the run never wrote costs the swap, not the page."""
        (self.artefacts / "figures" / "radar" / "CBK1.json").unlink()

        self.assertEqual(self.figure(figure_id="radar_compound", cbkid="CBK1").status_code, 404)

    def test_an_unreadable_artefact_is_404(self) -> None:
        """A truncated file is refused where a half-written generation would produce one."""
        (self.artefacts / "figures" / "radar" / "CBK1.json").write_text("{not json", "utf-8")

        self.assertEqual(self.figure(figure_id="radar_compound", cbkid="CBK1").status_code, 404)

    def test_traversal_through_the_compound_id_is_rejected(self) -> None:
        """The id only ever looks a key up, and the lookup then takes the download guard."""
        secret = self.artefacts / "summary.json"
        secret.write_text(json.dumps({"data": [], "layout": {}}), encoding="utf-8")

        for cbkid in (
            "../summary",
            f"../../drr/{SLUG}/summary",
            "/etc/passwd",
            "%2e%2e%2fsummary",
        ):
            with self.subTest(cbkid=cbkid):
                response = self.figure(figure_id="radar_compound", cbkid=cbkid)

                self.assertEqual(response.status_code, 404)

    def test_an_index_naming_a_key_outside_the_directory_is_refused(self) -> None:
        """The last line of defence: even a poisoned index cannot escape the guard."""
        (self.artefacts.parent / "escaped.json").write_text(
            json.dumps({"data": [], "layout": {}}), encoding="utf-8"
        )
        self.write_compound_index(
            {
                "cbkid": ["CBK1"],
                "kind": ["compound"],
                "name": ["Remdesivir"],
                "radar_key": ["../../../escaped"],
            }
        )

        self.assertEqual(self.figure(figure_id="radar_compound", cbkid="CBK1").status_code, 404)


class DrrFigureRouteCacheTests(DrrFigureRouteTestCase):
    """The render cache extends the block's key rather than adding a second one."""

    def test_two_compounds_cannot_serve_each_other_s_figure(self) -> None:
        """``cbkid`` is part of the key, so the second request is not the first's render."""
        first = self.figure(figure_id="radar_compound", cbkid="CBK1")
        second = self.figure(figure_id="radar_compound", cbkid="[stau]")

        self.assertContains(first, "Remdesivir (CBK1)")
        self.assertContains(second, "[stau] (control)")

    def test_the_default_view_and_a_compound_do_not_share_a_key(self) -> None:
        """Same ``figure_id``, different figures: the variant is what separates them."""
        default = self.figure(figure_id="radar_compound")
        compound = self.figure(figure_id="radar_compound", cbkid="CBK1")

        self.assertNotEqual(default.content, compound.content)

    def test_a_new_source_file_hash_re_renders(self) -> None:
        """A re-run's figures reach the reader rather than yesterday's cached HTML."""
        before = self.figure(figure_id="radar_compound", cbkid="CBK1").content

        self.write_radar("CBK1", CONTROL_RADAR_ON_DISK)
        self.data.source_file_hash = "hash-two"
        self.data.save()

        self.assertNotEqual(self.figure(figure_id="radar_compound", cbkid="CBK1").content, before)


class DrrRadarPickerTests(DrrFigureRouteTestCase):
    """The section 9 control that drives the route."""

    def test_the_picker_offers_only_compounds_with_a_radar(self) -> None:
        """Every option resolves, so no option can 404 (as FREYA-2583's already does)."""
        context = self.page.get_context(self.client.get(self.page.url).wsgi_request)

        self.assertEqual(
            [(option["cbkid"], option["label"]) for option in context["radar_compounds"]],
            [("CBK1", "Remdesivir (CBK1)"), ("[stau]", "[stau] (control)")],
        )

    def test_the_rendered_picker_targets_the_radar_and_names_the_figure(self) -> None:
        """An htmx GET to the route, swapping that one figure's body."""
        response = self.client.get(self.page.url)

        self.assertContains(response, 'hx-target="#figure-radar_compound"')
        self.assertContains(response, 'name="figure_id" value="radar_compound"')
        self.assertContains(response, self.page.url + "figure/")

    def test_the_page_renders_its_default_radar_without_the_control(self) -> None:
        """Progressive enhancement: the figure is complete before anything is picked."""
        response = self.client.get(self.page.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="figure-radar_compound"')

    def test_no_picker_without_a_precomputed_set(self) -> None:
        """An index with no radar keys offers no control at all."""
        self.write_compound_index(
            {"cbkid": ["CBK1"], "kind": ["compound"], "name": ["Remdesivir"], "radar_key": [None]}
        )

        response = self.client.get(self.page.url)

        self.assertNotIn("radar_compounds", self.page.get_context(response.wsgi_request))
        self.assertNotContains(response, "Radar: choose a compound")

    def test_no_picker_when_the_radar_block_is_not_placed(self) -> None:
        """A control needs the figure it swaps: without the block there is no target.

        The set can be fully precomputed and the editor still not have placed
        the radar. Offering the picker anyway would give the reader a control
        whose ``hx-target`` does not exist, which fails in the browser and
        shows nothing — a worse outcome than no control at all.
        """
        page = DrrDatasetPage.objects.get(pk=self.page.pk)
        page.content = [
            {
                "type": "plotly_figure",
                "value": {"figure_id": "pca", "alt_text": "PCA", "height": 500},
            }
        ]
        page.save_revision().publish()

        response = self.client.get(page.url)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("radar_compounds", page.get_context(response.wsgi_request))
        self.assertNotContains(response, "Radar: choose a compound")
        self.assertNotContains(response, 'hx-target="#figure-radar_compound"')

    def test_the_route_still_serves_a_figure_the_page_does_not_place(self) -> None:
        """What may be served follows from what was precomputed, not from the layout."""
        page = DrrDatasetPage.objects.get(pk=self.page.pk)
        page.content = []
        page.save_revision().publish()

        self.assertEqual(self.figure(figure_id="radar_compound", cbkid="CBK1").status_code, 200)
