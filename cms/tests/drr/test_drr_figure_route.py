"""Tests for the radar partial, its picker and the swap route (FREYA-2636, spec section 8.3).

The radars and their compound picker render together from the page's own
partial, not from editor-placed figure blocks, and the route returns one
compound's radar through that same partial. What these assert is the boundary
around it — a ``cbkid`` resolved through the compound index rather than
assembled from the request, a 404 that leaves the figure already on the page
standing — and that the page shows each radar once, picker beside it.
"""

from __future__ import annotations

import json
from typing import Any

import polars as pl
from django.core.cache import cache
from django.http import HttpResponse
from django.utils.html import escape

from cms.pages.drr_dataset import _RADAR_FIGURES, _SWAPPED_RADAR_CAPTION, DrrDatasetPage
from cms.snippets.drr_dataset_data import DrrDatasetData
from cms.tests.drr.test_drr_dataset_page import DrrDatasetPageTestCase
from cms.tests.utils import create_test_image, use_temp_media_root
from dashboard_visualisation.drr import artefact_key

SLUG = "drr-figure-route"

# The control id's key as precompute derives it, so the fixture cannot drift
# from the sanitiser the run actually uses.
STAU_KEY = artefact_key("[stau]")

# Three figures on the snippet and a radar set on disk, which is the split spec
# section 4 draws: one figure per figure_id in the snippet, a keyed set on disk.
SNIPPET_FIGURES = {
    "pca": {"data": [{"type": "scatter", "x": [1.0], "y": [2.0]}], "layout": {}},
    "radar_compound": {
        "data": [{"type": "scatterpolar", "r": [1.0], "theta": ["DNA I"]}],
        "layout": {},
    },
    "radar_infected": {
        "data": [{"type": "scatterpolar", "r": [2.0], "theta": ["DNA I"]}],
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
        """Publish a DRR dataset page placing the PCA; the radars come from the partial."""
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
                    "value": {"figure_id": "pca", "alt_text": "PCA of profiles", "height": 500},
                },
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

    def page_body(self) -> str:
        """GET the page and return its HTML."""
        response = self.client.get(self.page.url)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()


class DrrFigureRouteTests(DrrFigureRouteTestCase):
    """What the route serves, and what it refuses."""

    def test_the_partial_is_one_radar_and_not_the_page(self) -> None:
        """An htmx swap replaces one figure, so the response carries no page chrome."""
        response = self.figure(cbkid="CBK1")
        body = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="drr-radar-radar_compound"', body)
        self.assertIn("plotly-figure", body)
        self.assertNotIn("<html", body)
        self.assertNotIn("Radar plots", body)

    def test_the_swapped_figure_keeps_the_page_s_settings(self) -> None:
        """Alt text and height come from the page's radar settings, so it holds its shape.

        The caption does not: the page's describes the pooled view the swap
        replaces, so a swapped radar says it is one compound's instead.
        """
        body = self.figure(cbkid="CBK1").content.decode()

        self.assertIn(_RADAR_FIGURES[0]["alt_text"], body)
        self.assertIn(escape(_SWAPPED_RADAR_CAPTION), body)
        self.assertNotIn(_RADAR_FIGURES[0]["caption"], body)
        self.assertIn(f"{_RADAR_FIGURES[0]['height']}px", body)

    def test_the_swapped_figure_carries_its_basis_caveat_as_page_text(self) -> None:
        """The qualification survives the swap, and as wrapping text rather than chart ink.

        Inside the chart it would be a Plotly annotation, which does not wrap
        and is clipped at the plot's edge on a narrow viewport — so the reader
        who most needs the sentence is the one who cannot finish it.
        """
        response = self.figure(cbkid="CBK1")

        self.assertInHTML(
            f'<p class="text-sm text-pp-dark-grey mt-2">{RADAR_CAVEAT}</p>',
            response.content.decode(),
        )

    def test_a_radar_without_a_caveat_renders_no_empty_paragraph(self) -> None:
        """Only a payload that declares one gets the line; the control radar declares none."""
        response = self.figure(cbkid="[stau]")

        self.assertNotContains(response, "text-sm text-pp-dark-grey mt-2")

    def test_no_compound_is_404(self) -> None:
        """The route serves the per-compound set only; the defaults are on the page."""
        self.assertEqual(self.figure().status_code, 404)
        self.assertEqual(self.figure(cbkid="  ").status_code, 404)

    def test_the_route_serves_no_other_figure(self) -> None:
        """A ``figure_id`` names nothing any more: the route is the compound radar's alone."""
        for figure_id in ("pca", "radar_infected", "../summary"):
            with self.subTest(figure_id=figure_id):
                self.assertEqual(self.figure(figure_id=figure_id).status_code, 404)


class DrrRadarSetRouteTests(DrrFigureRouteTestCase):
    """Resolving a reader's compound to the file precompute wrote for it."""

    def test_a_named_compound_is_served_from_the_set(self) -> None:
        """The response is that compound's radar, not the snippet's default."""
        response = self.figure(cbkid="CBK1")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Remdesivir (CBK1)")

    def test_a_bracketed_control_id_round_trips_through_the_query_string(self) -> None:
        """``[stau]`` cannot sit in a path segment, which is why it travels as a parameter."""
        response = self.figure(cbkid="[stau]")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "[stau] (control)")

    def test_an_unknown_compound_is_404_and_leaves_the_default_standing(self) -> None:
        """The page keeps the radar it already rendered; nothing on it changes."""
        response = self.figure(cbkid="CBK404")

        self.assertEqual(response.status_code, 404)
        self.assertIn('id="drr-radar-radar_compound"', self.page_body())

    def test_a_compound_with_no_radar_is_404_rather_than_someone_else_s(self) -> None:
        """CBK2 has no treated well, so the index gives it no key and nothing is served."""
        self.assertEqual(self.figure(cbkid="CBK2").status_code, 404)

    def test_a_missing_artefact_is_404(self) -> None:
        """An index that names a file the run never wrote costs the swap, not the page."""
        (self.artefacts / "figures" / "radar" / "CBK1.json").unlink()

        self.assertEqual(self.figure(cbkid="CBK1").status_code, 404)

    def test_an_unreadable_artefact_is_404(self) -> None:
        """A truncated file is refused where a half-written generation would produce one."""
        (self.artefacts / "figures" / "radar" / "CBK1.json").write_text("{not json", "utf-8")

        self.assertEqual(self.figure(cbkid="CBK1").status_code, 404)

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
                response = self.figure(cbkid=cbkid)

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

        self.assertEqual(self.figure(cbkid="CBK1").status_code, 404)


class DrrFigureRouteCacheTests(DrrFigureRouteTestCase):
    """The radar render cache is DRR's own and keys on the compound."""

    def test_two_compounds_cannot_serve_each_other_s_figure(self) -> None:
        """``cbkid`` is part of the key, so the second request is not the first's render."""
        first = self.figure(cbkid="CBK1")
        second = self.figure(cbkid="[stau]")

        self.assertContains(first, "Remdesivir (CBK1)")
        self.assertContains(second, "[stau] (control)")

    def test_the_page_default_and_a_compound_do_not_share_a_key(self) -> None:
        """Same ``figure_id``, different figures: rendering the page first changes nothing."""
        self.page_body()

        self.assertContains(self.figure(cbkid="CBK1"), "Remdesivir (CBK1)")

    def test_a_new_source_file_hash_re_renders(self) -> None:
        """A re-run's figures reach the reader rather than yesterday's cached HTML."""
        before = self.figure(cbkid="CBK1").content

        self.write_radar("CBK1", CONTROL_RADAR_ON_DISK)
        self.data.source_file_hash = "hash-two"
        self.data.save()

        self.assertNotEqual(self.figure(cbkid="CBK1").content, before)


class DrrRadarPartialTests(DrrFigureRouteTestCase):
    """The radars and their picker, rendered together from the page's partial."""

    def test_the_picker_offers_only_compounds_with_a_radar(self) -> None:
        """Every option resolves, so no option can 404 (as FREYA-2583's already does)."""
        context = self.page.get_context(self.client.get(self.page.url).wsgi_request)

        self.assertEqual(
            [(option["cbkid"], option["label"]) for option in context["radar_compounds"]],
            [("CBK1", "Remdesivir (CBK1)"), ("[stau]", "[stau] (control)")],
        )

    def test_the_rendered_picker_targets_the_compound_radar(self) -> None:
        """An htmx GET to the route, swapping that one figure."""
        body = self.page_body()

        self.assertIn('hx-target="#drr-radar-radar_compound"', body)
        self.assertIn(self.page.url + "figure/", body)
        self.assertNotIn('name="figure_id"', body)

    def test_the_picker_sits_with_the_radars_after_the_editorial_content(self) -> None:
        """PCA, then the radar section: its picker, the compound radar, the infected radar."""
        body = self.page_body()

        positions = [
            body.index('aria-label="PCA of profiles"'),
            body.index('id="drr-radars-heading"'),
            body.index('id="drr-radar-compound"'),
            body.index('id="drr-radar-radar_compound"'),
            body.index('id="drr-radar-radar_infected"'),
        ]
        self.assertEqual(positions, sorted(positions))

    def test_each_radar_s_caption_sits_under_its_plot_before_the_caveat(self) -> None:
        """The caption says which population is plotted, so it follows the chart directly."""
        self.data.data = {
            **SNIPPET_FIGURES,
            "radar_infected": {
                **SNIPPET_FIGURES["radar_infected"],
                "layout": {"meta": {"caveat": RADAR_CAVEAT}},
            },
        }
        self.data.save()

        body = self.page_body()
        infected = body[body.index('id="drr-radar-radar_infected"') :]

        for settings in _RADAR_FIGURES:
            self.assertInHTML(
                f'<figcaption class="text-sm italic text-gray-500 mt-2 text-center">'
                f"{settings['caption']}</figcaption>",
                body,
            )
        self.assertLess(
            infected.index("<figcaption"),
            infected.index('<p class="text-sm text-pp-dark-grey mt-2">'),
        )

    def test_the_page_renders_its_default_radar_without_the_control(self) -> None:
        """Progressive enhancement: the figure is complete before anything is picked."""
        self.write_compound_index(
            {"cbkid": ["CBK1"], "kind": ["compound"], "name": ["Remdesivir"], "radar_key": [None]}
        )

        body = self.page_body()

        self.assertIn('id="drr-radar-radar_compound"', body)
        self.assertNotIn('id="drr-radar-compound"', body)

    def test_a_radar_s_caveat_renders_on_the_page(self) -> None:
        """The default view carries its basis caveat as page text, as a swap does."""
        self.data.data = {
            **SNIPPET_FIGURES,
            "radar_compound": {
                **SNIPPET_FIGURES["radar_compound"],
                "layout": {"meta": {"caveat": RADAR_CAVEAT}},
            },
        }
        self.data.save()

        self.assertInHTML(
            f'<p class="text-sm text-pp-dark-grey mt-2">{RADAR_CAVEAT}</p>', self.page_body()
        )

    def test_no_picker_without_a_precomputed_set(self) -> None:
        """An index with no radar keys offers no control at all."""
        self.write_compound_index(
            {"cbkid": ["CBK1"], "kind": ["compound"], "name": ["Remdesivir"], "radar_key": [None]}
        )

        response = self.client.get(self.page.url)

        self.assertNotIn("radar_compounds", self.page.get_context(response.wsgi_request))

    def test_no_radar_section_and_no_picker_without_the_default_radar(self) -> None:
        """A control needs the figure it swaps: without it there is no target.

        Offering the picker anyway would give the reader a control whose
        ``hx-target`` does not exist, which fails in the browser and shows
        nothing — a worse outcome than no control at all.
        """
        self.data.data = {"pca": SNIPPET_FIGURES["pca"]}
        self.data.save()

        body = self.page_body()

        self.assertNotIn("Radar plots", body)
        self.assertNotIn('hx-target="#drr-radar-radar_compound"', body)
        self.assertEqual(self.figure(cbkid="CBK1").status_code, 200)
