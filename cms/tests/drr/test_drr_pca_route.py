"""Tests for the PCA's colourings, their precompute and the ``pca/`` swap route (FREYA-3201).

The page draws the PCA from its own partial, and a colour-by picker swaps in one of
the colourings precompute wrote. Every colouring is drawn from one fit and recolours
the treated wells only: the controls and the three antivirals keep their traces,
colours and place on top, so a reader comparing two views compares the treated
wells and nothing else. A compound picker beside it draws one compound's wells and
its dose line over whichever colouring is shown (FREYA-3202).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import plotly.graph_objects as go
import polars as pl
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.http import HttpResponse
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils.html import escape
from openpyxl import Workbook

from cms.pages.drr_dataset import (
    _PCA_COLOURING_CHOICES,
    _PCA_FIGURE,
    _PCA_OVERLAY_CAPTION,
    DrrDatasetPage,
)
from cms.services.file_downloads import resolve_file_in_directory
from cms.snippets.drr_dataset_data import DrrDatasetData
from cms.tests.drr.test_drr_dataset_page import DrrDatasetPageTestCase
from cms.tests.drr.test_drr_figures import SLUG as FIGURES_SLUG
from cms.tests.drr.test_drr_figures import _decode_array, _pca_table
from cms.tests.drr.test_drr_precompute import FEATURE_CSV, METADATA_TSV, PLATE_METADATA_TSV
from cms.tests.drr.test_drr_precompute import SLUG as PRECOMPUTE_SLUG
from cms.tests.drr.test_drr_table import page_table
from cms.tests.utils import create_test_image, use_temp_media_root
from dashboard_visualisation.drr import artefact_key
from dashboard_visualisation.drr.channels import channel_map, figure_feature_columns
from dashboard_visualisation.drr.figures import (
    NEAR_EMPTY_NUCLEI_THRESHOLD,
    PCA_COLOURINGS,
    PCA_DEFAULT_COLOURING,
    PCA_MOA_COLOURS,
    PCA_MOA_GROUPS,
    PCA_NOT_ANNOTATED,
    PCA_NOT_REPORTED,
    PCA_OTHER_MECHANISMS,
    PCA_OVERLAY_CENTROID_SUFFIX,
    PCA_OVERLAY_COLOUR,
    FigureBundle,
    build_figure_bundle,
    combine_pca_overlay,
)
from dashboard_visualisation.drr.loader import FeatureTable

# One well per entry: ``(pert_type, cbkid, dose in µM, nuclei)``. Compounds 11 to 21
# carry nine mechanisms between them, so the top eight leave one over; 22 to 24 have
# none. CBK25's only well is near-empty, so it is not drawn and must not count.
COLOURING_WELLS: list[tuple[str, str, float, float]] = [
    ("trt", "CBK11", 0.1, 240.0),
    ("trt", "CBK11", 10.0, 240.0),
    ("trt", "CBK12", 1.0, 240.0),
    ("trt", "CBK13", 3.0, 240.0),
    ("trt", "CBK14", 30.0, 240.0),
    ("trt", "CBK15", 0.3, 240.0),
    ("trt", "CBK16", 1.0, 240.0),
    ("trt", "CBK17", 3.0, 240.0),
    ("trt", "CBK18", 10.0, 240.0),
    ("trt", "CBK19", 0.1, 240.0),
    ("trt", "CBK20", 1.0, 240.0),
    ("trt", "CBK21", 3.0, 240.0),
    ("trt", "CBK22", 10.0, 240.0),
    ("trt", "CBK23", 30.0, 240.0),
    ("trt", "CBK24", 0.3, 240.0),
    ("trt", "CBK25", 1.0, 10.0),
    ("poscon", "[stau]", 0.01, 240.0),
    ("negcon", "CBK281357", 0.3, 240.0),
    ("non-inf", "CBK281357", 0.3, 240.0),
    ("trt", "CBK310015", 0.3, 240.0),
    ("trt", "CBK310015", 30.0, 240.0),
    ("trt", "DO8167002", 3.0, 240.0),
    ("trt", "CBK310023", 10.0, 240.0),
]

# ``alpha`` and ``beta|gamma`` tie on two compounds and name breaks the tie; a
# pipe-joined value is its own group, not ``beta``'s; the seven single-compound
# groups tie and name decides which six of them fit beside the two — ``zeta`` is
# ninth. CBK25's ``aaa`` would rank third if a near-empty well counted, and the
# antivirals' ``omega`` first if their wells were recoloured.
MECHANISMS: dict[str, str | None] = {
    "CBK11": "alpha",
    "CBK12": "alpha",
    "CBK13": "beta|gamma",
    "CBK14": "beta|gamma",
    "CBK15": "beta",
    "CBK16": "delta",
    "CBK17": "epsilon",
    "CBK18": "eta",
    "CBK19": "iota",
    "CBK20": "kappa",
    "CBK21": "zeta",
    "CBK22": None,
    "CBK23": "  ",
    "CBK25": "aaa",
    "CBK310015": "omega",
    "DO8167002": "omega",
    "CBK310023": "omega",
}
RANKED_GROUPS = ["alpha", "beta|gamma", "beta", "delta", "epsilon", "eta", "iota", "kappa"]

# Two compounds scored, one null and the rest absent, which is how the compound
# table carries a compound Table S8 does not. Remdesivir's score is never drawn:
# its wells keep their own trace.
MORPHOLOGY_SCORES: dict[str, float | None] = {
    "CBK11": 0.9,
    "CBK12": 0.25,
    "CBK13": None,
    "CBK310015": 0.7,
}

# The traces every colouring keeps, in their place on top.
KEPT_TRACES = [
    "Positive control",
    "Infected control (DMSO)",
    "Uninfected control (DMSO)",
    "Remdesivir",
    "Nirmatrelvir",
    "GC376",
]

# ``_pca_table`` puts well ``i`` at ``i + 1`` on its one varying column, so PC1 is
# that position centred over the drawn wells, and a score names its well.
_DRAWN = [
    index for index, well in enumerate(COLOURING_WELLS) if well[3] >= NEAR_EMPTY_NUCLEI_THRESHOLD
]
_CENTRE = sum(index + 1 for index in _DRAWN) / len(_DRAWN)
_WELL_AT = {round(index + 1 - _CENTRE, 6): index for index in _DRAWN}


def _views(
    table: FeatureTable,
    *,
    morphology_scores: dict[str, float | None] | None = MORPHOLOGY_SCORES,
    mechanisms: dict[str, str | None] | None = MECHANISMS,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Return every PCA view of ``table`` as figure JSON, keyed by colouring, and the report."""
    channels = channel_map(FIGURES_SLUG)
    bundle = build_figure_bundle(
        table,
        feature_columns=figure_feature_columns(table.feature_columns, channels),
        channels=channels,
        morphology_scores=morphology_scores,
        mechanisms=mechanisms,
    )
    views = {PCA_DEFAULT_COLOURING: bundle.figures["pca"], **bundle.pca_colourings}
    return views, bundle.pca_report


def _names(view: dict[str, Any]) -> list[str]:
    """Return a view's trace names, bottom to top."""
    return [trace["name"] for trace in view["data"]]


def _well_order(trace: dict[str, Any]) -> list[int]:
    """Return which fixture well each of a trace's points is, in the trace's own order."""
    return [_WELL_AT[round(score, 6)] for score in _decode_array(trace["x"]).tolist()]


def _wells_by_trace(view: dict[str, Any]) -> dict[str, list[int]]:
    """Return the fixture wells each trace of a view draws, sorted."""
    return {trace["name"]: sorted(_well_order(trace)) for trace in view["data"]}


def _wells_of(*cbkids: str) -> list[int]:
    """Return the drawn fixture wells of these compounds."""
    return [index for index in _DRAWN if COLOURING_WELLS[index][1] in cbkids]


class DrrPcaColouringTests(SimpleTestCase):
    """What each colouring draws, and what every colouring leaves alone."""

    def setUp(self) -> None:
        """Build every PCA view of the colouring fixture."""
        self.views, self.report = _views(_pca_table(COLOURING_WELLS))

    def test_the_allow_list_is_the_default_and_two_colourings(self) -> None:
        """The picker's order: today's population view first, then the two colourings."""
        self.assertEqual(PCA_COLOURINGS, ("population", "morphology", "moa"))
        self.assertEqual(PCA_DEFAULT_COLOURING, "population")
        self.assertEqual(set(self.views), set(PCA_COLOURINGS))

    def test_controls_and_antivirals_are_identical_in_every_view(self) -> None:
        """Their traces equal the default's, in the same place on top."""
        kept = self.views[PCA_DEFAULT_COLOURING]["data"][-len(KEPT_TRACES) :]
        self.assertEqual([trace["name"] for trace in kept], KEPT_TRACES)

        for colouring, view in self.views.items():
            with self.subTest(colouring=colouring):
                self.assertEqual(view["data"][-len(KEPT_TRACES) :], kept)

    def test_every_view_shares_the_fit_the_axes_and_the_layout(self) -> None:
        """One fit: the same layout, axis shares and subtitle, and the same wells drawn."""
        default = self.views[PCA_DEFAULT_COLOURING]

        for colouring, view in self.views.items():
            with self.subTest(colouring=colouring):
                self.assertEqual(view["layout"], default["layout"])
                self.assertEqual(
                    sorted(well for trace in view["data"] for well in _well_order(trace)),
                    _DRAWN,
                )

    def test_marker_size_keeps_encoding_dose(self) -> None:
        """Each treated well keeps the size the default view gives it."""
        default = self._treated_sizes(self.views[PCA_DEFAULT_COLOURING])

        for colouring, view in self.views.items():
            with self.subTest(colouring=colouring):
                self.assertEqual(self._treated_sizes(view), default)

    def test_an_unscored_compound_is_not_reported_and_never_zero(self) -> None:
        """A null or absent score is one grey trace at the bottom; the scale holds the rest."""
        view = self.views["morphology"]
        traces = {trace["name"]: trace for trace in view["data"]}
        wells = _wells_by_trace(view)

        self.assertEqual(_names(view)[:2], [PCA_NOT_REPORTED, "Morphology score"])
        self.assertEqual(wells["Morphology score"], _wells_of("CBK11", "CBK12"))
        self.assertEqual(
            wells[PCA_NOT_REPORTED], _wells_of(*(f"CBK{number}" for number in range(13, 25)))
        )
        self.assertEqual(traces[PCA_NOT_REPORTED]["marker"]["color"], "#d8d8d8")

        scored = traces["Morphology score"]
        colours = _decode_array(scored["marker"]["color"]).tolist()
        self.assertEqual(
            dict(zip(_well_order(scored), colours, strict=True)),
            {
                well: MORPHOLOGY_SCORES[COLOURING_WELLS[well][1]]
                for well in wells["Morphology score"]
            },
        )
        self.assertNotIn(0.0, colours)

    def test_the_morphology_scale_is_cividis_with_a_titled_colour_bar(self) -> None:
        """Plotly's colour-blind-safe sequential scale, named on the bar beside it."""
        scored = {trace["name"]: trace for trace in self.views["morphology"]["data"]}[
            "Morphology score"
        ]
        cividis = go.scatter.Marker(colorscale="Cividis").to_plotly_json()["colorscale"]

        self.assertEqual([list(stop) for stop in scored["marker"]["colorscale"]], cividis)
        self.assertTrue(scored["marker"]["showscale"])
        self.assertEqual(scored["marker"]["colorbar"]["title"]["text"], "Morphology score")

    def test_no_morphology_view_without_scores(self) -> None:
        """Precompute passes no scores when it built no table, so the view is not built."""
        views, report = _views(_pca_table(COLOURING_WELLS), morphology_scores=None)

        self.assertEqual(set(views), {"population", "moa"})
        self.assertEqual(report["written"], ["population", "moa"])
        self.assertNotIn("morphology", report)

    def test_the_mechanism_rule(self) -> None:
        """Top eight by compounds drawn, ties by name; the rest and the unannotated grouped."""
        view = self.views["moa"]
        traces = {trace["name"]: trace for trace in view["data"]}
        wells = _wells_by_trace(view)

        self.assertEqual(
            _names(view),
            [PCA_NOT_ANNOTATED, PCA_OTHER_MECHANISMS, *RANKED_GROUPS, *KEPT_TRACES],
        )
        self.assertEqual(wells["alpha"], _wells_of("CBK11", "CBK12"))
        self.assertEqual(wells["beta|gamma"], _wells_of("CBK13", "CBK14"))
        self.assertEqual(wells["beta"], _wells_of("CBK15"))
        self.assertEqual(wells[PCA_OTHER_MECHANISMS], _wells_of("CBK21"))
        self.assertEqual(wells[PCA_NOT_ANNOTATED], _wells_of("CBK22", "CBK23", "CBK24"))
        self.assertEqual(
            [traces[group]["marker"]["color"] for group in RANKED_GROUPS], list(PCA_MOA_COLOURS)
        )
        self.assertEqual(traces[PCA_OTHER_MECHANISMS]["marker"]["color"], "#a8a8a8")
        self.assertEqual(traces[PCA_NOT_ANNOTATED]["marker"]["color"], "#d8d8d8")

    def test_the_mechanism_colours_are_eight_distinct_fixed_values(self) -> None:
        """One colour per ranked group, none of them a grey the buckets or controls use."""
        self.assertEqual(PCA_MOA_GROUPS, 8)
        self.assertEqual(len(set(PCA_MOA_COLOURS)), PCA_MOA_GROUPS)
        self.assertFalse({"#d8d8d8", "#a8a8a8", "#55585a"} & set(PCA_MOA_COLOURS))

    def test_the_views_build_without_any_mechanisms(self) -> None:
        """An index without ``broad_moa`` leaves every treated compound unannotated."""
        views, report = _views(_pca_table(COLOURING_WELLS), mechanisms=None)

        self.assertEqual(_names(views["moa"]), [PCA_NOT_ANNOTATED, *KEPT_TRACES])
        self.assertEqual(report["moa_groups"], [])

    def test_the_report_says_what_was_written_and_how_many_are_scored(self) -> None:
        """The compounds counted are the ones the colouring draws: no antiviral, no CBK25."""
        self.assertEqual(
            self.report,
            {
                "written": ["population", "morphology", "moa"],
                "morphology": {"n_compounds_scored": 2, "n_compounds_not_reported": 12},
                "moa_groups": RANKED_GROUPS,
            },
        )

    @staticmethod
    def _treated_sizes(view: dict[str, Any]) -> dict[int, float]:
        """Return the marker size of every treated, non-antiviral well a view draws."""
        sizes: dict[int, float] = {}
        for trace in view["data"][: -len(KEPT_TRACES)]:
            values = _decode_array(trace["marker"]["size"]).tolist()
            sizes.update(zip(_well_order(trace), values, strict=True))
        return sizes


class DrrPcaPrecomputeTests(TestCase):
    """What precompute writes for the colourings and the overlays, and what it refuses to write.

    The fixture is ``test_drr_precompute``'s: two treated compounds, CBK1 named
    ``compoundA`` with a ``broad_moa`` and a Table S8 score, and CBK3 with neither.
    """

    def setUp(self) -> None:
        """Write the precompute fixture's inputs and an isolated media root."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.inputs = {
            "input": self.base / "features.csv",
            "metadata": self.base / "metadata.tsv",
            "plate_metadata": self.base / "plates.tsv",
        }
        for key, text in (
            ("input", FEATURE_CSV),
            ("metadata", METADATA_TSV),
            ("plate_metadata", PLATE_METADATA_TSV),
        ):
            self.inputs[key].write_text(text, encoding="utf-8")
        self.media = self.base / "media"
        self.out_dir = self.media / "drr" / PRECOMPUTE_SLUG
        self.pca_dir = self.out_dir / "figures" / "pca"

    def _run(self, *, with_table: bool = True) -> None:
        """Run precompute on the fixture, with or without Table S8."""
        extra = {"table_s8": str(self._write_table_s8())} if with_table else {}
        with override_settings(MEDIA_ROOT=str(self.media)):
            call_command(
                "drr_precompute",
                slug=PRECOMPUTE_SLUG,
                title="Test DRR",
                **{key: str(path) for key, path in self.inputs.items()},
                **extra,
            )

    def _write_table_s8(self) -> Path:
        """Write a two-dose Table S8 scoring CBK1's CBCS name only."""
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(
            [
                "Compound_name",
                "Concentration (uM)",
                "morphology_score",
                "Cell count (%)",
                "Infection rate (%)",
            ]
        )
        sheet.append(["compoundA", "1", 0.8, 100, 20])
        sheet.append(["compoundA", "0.3", 0.1, 104, 95])
        path = self.base / "s8.xlsx"
        workbook.save(path)
        return path

    def test_the_colourings_go_under_figures_pca_and_the_default_stays_in_the_snippet(self) -> None:
        """Two files on disk, none for the default, and the snippet's figure ids unchanged.

        The overlays' folder sits beside them (FREYA-3202).
        """
        self._run()

        self.assertEqual(
            sorted(path.name for path in self.pca_dir.iterdir()),
            ["compound", "moa.json", "morphology.json"],
        )
        self.assertEqual(
            set(DrrDatasetData.get_data(PRECOMPUTE_SLUG).data),
            {"pca", "radar_compound", "radar_infected"},
        )

    def test_without_the_table_no_morphology_is_written_and_a_stale_one_goes(self) -> None:
        """A colouring left by a run with the table would describe another generation."""
        self._run()
        self._run(with_table=False)

        self.assertEqual(
            sorted(path.name for path in self.pca_dir.iterdir()), ["compound", "moa.json"]
        )

    def test_the_summary_records_the_colourings_and_the_scored_count(self) -> None:
        """CBK1 is scored and CBK3 is not; ``inhibitor`` is the one mechanism drawn."""
        self._run()
        summary = json.loads((self.out_dir / "summary.json").read_text(encoding="utf-8"))

        self.assertEqual(
            summary["feature_sets"]["figures"]["pca_colourings"],
            {
                "written": ["population", "morphology", "moa"],
                "morphology": {"n_compounds_scored": 1, "n_compounds_not_reported": 1},
                "moa_groups": ["inhibitor"],
            },
        )
        self.assertEqual(
            DrrDatasetData.get_data(PRECOMPUTE_SLUG).summary["feature_sets"]["figures"][
                "pca_colourings"
            ]["written"],
            ["population", "morphology", "moa"],
        )

    def test_an_oversized_colouring_fails_the_run_before_anything_is_written(self) -> None:
        """Every colouring is checked against the ceiling, as the snippet's figures are."""

        def only_colourings_too_large(figures: dict[str, Any]) -> dict[str, int]:
            return {key: 2_000_000 for key in figures if key.startswith("pca/")}

        with (
            patch(
                "cms.management.commands.drr_precompute.oversized_figures",
                side_effect=only_colourings_too_large,
            ),
            self.assertRaisesMessage(CommandError, "'pca/moa': 2000000"),
        ):
            self._run()

        self.assertEqual([path for path in self.out_dir.rglob("*") if path.is_file()], [])
        self.assertIsNone(DrrDatasetData.get_data(PRECOMPUTE_SLUG))

    def test_the_colourings_are_byte_stable_across_runs(self) -> None:
        """The idempotency contract holds for the set as for every other artefact.

        Every file under ``figures/pca/``, the overlays included (FREYA-3202).
        """
        self._run()
        first = self._pca_files()
        self._run()

        self.assertEqual(self._pca_files(), first)

    def _pca_files(self) -> dict[str, bytes]:
        """Return every file under ``figures/pca/``, keyed by its path there."""
        return {
            str(path.relative_to(self.pca_dir)): path.read_bytes()
            for path in sorted(self.pca_dir.rglob("*"))
            if path.is_file()
        }

    def test_the_default_view_does_not_depend_on_the_table(self) -> None:
        """Only the morphology colouring reads the table; the snippet's PCA never does."""
        self._run()
        with_table = DrrDatasetData.get_data(PRECOMPUTE_SLUG).data["pca"]
        self._run(with_table=False)

        self.assertEqual(DrrDatasetData.get_data(PRECOMPUTE_SLUG).data["pca"], with_table)

    # The per-compound overlays (FREYA-3202).

    def test_one_overlay_per_fitted_compound_goes_under_figures_pca_compound(self) -> None:
        """CBK1 and CBK3 are treated and fitted; CBK2's wells are controls, so it has none."""
        self._run()
        overlay_dir = self.pca_dir / "compound"

        self.assertEqual(
            sorted(path.name for path in overlay_dir.iterdir()), ["CBK1.json", "CBK3.json"]
        )
        overlay = json.loads((overlay_dir / "CBK1.json").read_text(encoding="utf-8"))
        self.assertEqual(set(overlay), {"data"})
        self.assertEqual(len(overlay["data"]), 2)

    def test_an_overlay_names_its_compound_the_way_the_radar_does(self) -> None:
        """One label rule, so the legend agrees with the picker and the radar."""
        self._run()
        overlay = json.loads((self.pca_dir / "compound" / "CBK1.json").read_text(encoding="utf-8"))
        radar = json.loads(
            (self.out_dir / "figures" / "radar" / "CBK1.json").read_text(encoding="utf-8")
        )
        name = overlay["data"][0]["name"]

        self.assertEqual(
            radar["layout"]["title"]["text"], f"Radar: {name} vs infected DMSO baseline"
        )
        self.assertEqual(overlay["data"][1]["name"], f"{name}{PCA_OVERLAY_CENTROID_SUFFIX}")

    def test_the_index_records_each_overlay_s_key(self) -> None:
        """The route resolves a reader's cbkid through this column; a null means no overlay."""
        self._run()
        index = pl.read_parquet(self.out_dir / "compounds.parquet")

        keys = dict(zip(index["cbkid"].to_list(), index["pca_key"].to_list(), strict=True))
        self.assertEqual(keys, {"CBK1": "CBK1", "CBK2": None, "CBK3": "CBK3"})

    def test_a_stale_overlay_does_not_survive_a_re_run(self) -> None:
        """The set describes this generation, as the radar set does."""
        self._run()
        stale = self.pca_dir / "compound" / "CBK404.json"
        stale.write_text("{}", encoding="utf-8")

        self._run()

        self.assertFalse(stale.exists())

    def test_an_oversized_overlay_combination_fails_the_run_before_anything_is_written(
        self,
    ) -> None:
        """Each view is checked with the heaviest overlay drawn over it, as a swap serves it."""
        checked: dict[str, Any] = {}

        def only_combinations_too_large(figures: dict[str, Any]) -> dict[str, int]:
            checked.update(figures)
            return {key: 2_000_000 for key in figures if key.endswith("+compound")}

        with (
            patch(
                "cms.management.commands.drr_precompute.oversized_figures",
                side_effect=only_combinations_too_large,
            ),
            self.assertRaisesMessage(CommandError, "'pca/population+compound': 2000000"),
        ):
            self._run()

        self.assertEqual([path for path in self.out_dir.rglob("*") if path.is_file()], [])
        self.assertIsNone(DrrDatasetData.get_data(PRECOMPUTE_SLUG))
        self.assertEqual(
            sorted(key for key in checked if key.endswith("+compound")),
            [f"pca/{key}+compound" for key in sorted(PCA_COLOURINGS)],
        )
        combined = checked["pca/moa+compound"]["data"]
        self.assertEqual(combined[:-2], checked["pca/moa"]["data"])
        self.assertTrue(combined[-1]["name"].endswith(PCA_OVERLAY_CENTROID_SUFFIX))


ROUTE_SLUG = "drr-pca-route"

# What each view's one trace is called, so a response says which view it carries.
VIEW_TRACES = {
    "population": "Population view",
    "morphology": "Morphology view",
    "moa": "Mechanism view",
}
CAPTIONS = {key: caption for key, _, caption in _PCA_COLOURING_CHOICES}


def _figure(trace_name: str) -> dict[str, Any]:
    """Return a one-trace figure whose trace name identifies it."""
    return {"data": [{"type": "scatter", "name": trace_name, "x": [1.0], "y": [2.0]}], "layout": {}}


SNIPPET_FIGURES = {
    "pca": _figure(VIEW_TRACES["population"]),
    "radar_compound": {
        "data": [{"type": "scatterpolar", "r": [1.0], "theta": ["DNA I"]}],
        "layout": {},
    },
    "radar_infected": {
        "data": [{"type": "scatterpolar", "r": [2.0], "theta": ["DNA I"]}],
        "layout": {},
    },
}


class DrrPcaRouteTestCase(DrrDatasetPageTestCase):
    """A published DRR page whose editor left a PCA block in ``content``.

    Both colourings are on disk, and so is the compound table, so every section
    the PCA sits between renders.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Publish the page: editorial prose, then a PCA block the template must skip."""
        super().setUpTestData()
        cls.image = create_test_image(title="DRR PCA", file_name="drr-pca.jpg")
        cls.page = DrrDatasetPage(
            title="DRR PCA Route",
            slug=ROUTE_SLUG,
            description="The PCA is recoloured in place.",
            image=cls.image,
            data_status="active",
            content=[
                {"type": "text", "value": "<h2>About this screen</h2><p>Editorial prose.</p>"},
                {
                    "type": "plotly_figure",
                    "value": {
                        "figure_id": "pca",
                        "alt_text": "Editorial PCA block",
                        "height": 500,
                    },
                },
            ],
        )
        cls.index.add_child(instance=cls.page)
        cls.page.save_revision().publish()

    def setUp(self) -> None:
        """Write the colourings and the table, create the data row, and clear the cache."""
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.artefacts = use_temp_media_root(self) / "drr" / ROUTE_SLUG
        self.pca_dir = self.artefacts / "figures" / "pca"
        self.pca_dir.mkdir(parents=True)
        for colouring in ("morphology", "moa"):
            self.write_colouring(colouring, _figure(VIEW_TRACES[colouring]))
        page_table().write_parquet(self.artefacts / "table.parquet")
        self.data = DrrDatasetData.objects.create(
            dataset_slug=ROUTE_SLUG,
            dataset_title="DRR PCA Route",
            data=SNIPPET_FIGURES,
            summary={"n_compounds": 3},
            source_file_hash="hash-one",
        )

    def write_colouring(self, colouring: str, payload: dict[str, Any]) -> None:
        """Write one colouring under ``figures/pca/``, as precompute does."""
        (self.pca_dir / f"{colouring}.json").write_text(json.dumps(payload), encoding="utf-8")

    def pca(self, **params: str) -> HttpResponse:
        """GET the PCA route with the given query parameters."""
        return self.client.get(self.page.url + "pca/", params)

    def page_body(self) -> str:
        """GET the page and return its HTML."""
        response = self.client.get(self.page.url)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def context(self) -> dict[str, Any]:
        """Return the page's template context for a plain GET."""
        return self.page.get_context(self.client.get(self.page.url).wsgi_request)


class DrrPcaRouteTests(DrrPcaRouteTestCase):
    """What the ``pca/`` route serves, and what it refuses."""

    def test_the_choices_are_the_allow_list(self) -> None:
        """The page labels exactly the colourings precompute knows, in the same order."""
        self.assertEqual(tuple(key for key, _, _ in _PCA_COLOURING_CHOICES), PCA_COLOURINGS)

    def test_each_colouring_is_one_pca_partial_and_not_the_page(self) -> None:
        """An htmx swap replaces one figure: its own trace and caption, no page chrome."""
        for colouring, trace in VIEW_TRACES.items():
            with self.subTest(colouring=colouring):
                response = self.pca(colour=colouring)
                body = response.content.decode()

                self.assertEqual(response.status_code, 200)
                self.assertEqual(body.count('id="drr-pca"'), 1)
                self.assertIn(trace, body)
                self.assertEqual([name for name in VIEW_TRACES.values() if name in body], [trace])
                self.assertIn(escape(CAPTIONS[colouring]), body)
                self.assertNotIn("<html", body)
                self.assertNotIn("Principal component analysis", body)

    def test_the_swapped_figure_keeps_the_page_s_alt_text_and_height(self) -> None:
        """Both come from the page code, so the figure holds its shape across a swap."""
        body = self.pca(colour="moa").content.decode()

        self.assertIn(f'aria-label="{_PCA_FIGURE["alt_text"]}"', body)
        self.assertIn(f"{_PCA_FIGURE['height']}px", body)

    def test_an_unknown_colouring_is_404_before_any_path_is_resolved(self) -> None:
        """Only an allow-listed key is looked up, so no request value reaches a path."""
        with patch("cms.pages.drr_dataset.resolve_file_in_directory") as resolve:
            self.assertEqual(self.client.get(self.page.url + "pca/").status_code, 404)
            for colour in ("", "umap", "MOA", "pca", "../summary", "figures/pca/moa", "moa.json"):
                with self.subTest(colour=colour):
                    self.assertEqual(self.pca(colour=colour).status_code, 404)

        resolve.assert_not_called()

    def test_a_missing_colouring_is_404_and_leaves_the_page_s_figure_standing(self) -> None:
        """A colouring the run did not write costs the swap and its option, not the page."""
        (self.pca_dir / "moa.json").unlink()

        self.assertEqual(self.pca(colour="moa").status_code, 404)
        body = self.page_body()
        self.assertIn('id="drr-pca"', body)
        self.assertNotIn('value="moa"', body)

    def test_an_unreadable_colouring_is_404(self) -> None:
        """A truncated file is refused where a half-written generation would leave one."""
        (self.pca_dir / "moa.json").write_text("{not json", encoding="utf-8")

        self.assertEqual(self.pca(colour="moa").status_code, 404)

    def test_no_default_view_means_no_section_and_a_404_for_it(self) -> None:
        """Without the snippet's PCA there is nothing to swap into, so nothing is offered."""
        self.data.data = {key: value for key, value in SNIPPET_FIGURES.items() if key != "pca"}
        self.data.save()

        self.assertEqual(self.pca(colour="population").status_code, 404)
        body = self.page_body()
        self.assertNotIn('id="drr-pca"', body)
        self.assertNotIn("Principal component analysis", body)
        self.assertNotIn('hx-target="#drr-pca"', body)


class DrrPcaPickerTests(DrrPcaRouteTestCase):
    """The colour-by picker and where the PCA sits on the page."""

    def test_the_picker_offers_only_the_colourings_precompute_wrote(self) -> None:
        """Every option resolves, so no option can 404."""
        self.assertEqual(
            [(option["key"], option["label"]) for option in self.context()["pca_colourings"]],
            [
                ("population", "Population"),
                ("morphology", "Morphology score"),
                ("moa", "Mechanism of action"),
            ],
        )

        (self.pca_dir / "morphology.json").unlink()

        self.assertEqual(
            [option["key"] for option in self.context()["pca_colourings"]],
            ["population", "moa"],
        )

    def test_no_picker_when_only_the_default_was_written(self) -> None:
        """A picker with one option changes nothing, so the figure renders without one."""
        for colouring in ("morphology", "moa"):
            (self.pca_dir / f"{colouring}.json").unlink()

        body = self.page_body()

        self.assertNotIn("pca_colourings", self.context())
        self.assertIn('id="drr-pca"', body)
        self.assertNotIn('id="drr-pca-colour"', body)

    def test_the_rendered_picker_swaps_the_pca_over_get(self) -> None:
        """An htmx GET to the route, replacing that one figure, starting on the default."""
        body = self.page_body()

        self.assertIn('hx-get="' + self.page.url + 'pca/"', body)
        self.assertIn('hx-target="#drr-pca"', body)
        self.assertIn('hx-swap="outerHTML"', body)
        self.assertIn('<select id="drr-pca-colour" name="colour"', body)
        self.assertIn('<label for="drr-pca-colour"', body)
        self.assertInHTML('<option value="population" selected>Population</option>', body)

    def test_the_pca_sits_after_the_content_and_before_the_radars_and_the_table(self) -> None:
        """Editorial prose, the PCA with its picker above it, the radars, the compound table."""
        body = self.page_body()

        positions = [
            body.index("Editorial prose."),
            body.index('id="drr-pca-heading"'),
            body.index('id="drr-pca-colour"'),
            body.index('id="drr-pca"'),
            body.index('id="drr-radars-heading"'),
            body.index('id="drr-compound-table-heading"'),
        ]
        self.assertEqual(positions, sorted(positions))

    def test_a_pca_block_left_in_content_is_not_drawn(self) -> None:
        """One PCA on the page, the template's; the editor's prose still renders."""
        body = self.page_body()

        self.assertEqual(body.count('id="drr-pca"'), 1)
        self.assertNotIn('aria-label="Editorial PCA block"', body)
        self.assertIn(f'aria-label="{_PCA_FIGURE["alt_text"]}"', body)
        self.assertIn("Editorial prose.", body)

    def test_the_table_of_contents_path_skips_the_pca_block_too(self) -> None:
        """With the TOC on, the content is rendered through the TOC tag, from the same stream."""
        self.page.show_toc = True
        self.page.save_revision().publish()

        body = self.page_body()

        self.assertNotIn('aria-label="Editorial PCA block"', body)
        self.assertIn("Editorial prose.", body)
        self.assertEqual(body.count('id="drr-pca"'), 1)


class DrrPcaCacheTests(DrrPcaRouteTestCase):
    """The PCA's render cache keys on the colouring and the data generation."""

    def test_two_colourings_cannot_serve_each_other_s_figure(self) -> None:
        """The colouring is in the key: the second request is not the first's render."""
        self.page_body()

        for colouring, trace in VIEW_TRACES.items():
            with self.subTest(colouring=colouring):
                self.assertContains(self.pca(colour=colouring), trace)

    def test_a_new_source_file_hash_re_renders(self) -> None:
        """A re-run's colouring reaches the reader rather than yesterday's cached HTML."""
        self.assertContains(self.pca(colour="moa"), VIEW_TRACES["moa"])

        self.write_colouring("moa", _figure("Rewritten view"))
        self.data.source_file_hash = "hash-two"
        self.data.save()

        self.assertContains(self.pca(colour="moa"), "Rewritten view")


# The overlays (FREYA-3202). The colouring fixture's compounds with a fitted treated
# or antiviral well: CBK25's only well is near-empty, and the rest are controls.
OVERLAID = sorted(
    {f"CBK{number}" for number in range(11, 25)} | {"CBK310015", "DO8167002", "CBK310023"}
)

# One compound at three doses, given out of order, two wells at 10 µM and a
# near-empty one at 1 µM, plus the two controls the radars need. Well ``i`` sits
# at ``i + 1`` on PC1 before centring, so the centroids are known exactly, and
# they do not rise with PC1: an order taken from the scores would fail.
OVERLAY_WELLS: list[tuple[str, str, float, float]] = [
    ("trt", "CBK31", 10.0, 240.0),
    ("trt", "CBK31", 0.1, 240.0),
    ("trt", "CBK31", 1.0, 240.0),
    ("trt", "CBK31", 10.0, 240.0),
    ("trt", "CBK31", 1.0, 10.0),
    ("trt", "CBK32", 3.0, 240.0),
    ("negcon", "CBK281357", 0.3, 240.0),
    ("non-inf", "CBK281357", 0.3, 240.0),
]


def _bundle(
    wells: list[tuple[str, str, float, float]],
    *,
    compound_labels: dict[str, str] | None = None,
) -> FigureBundle:
    """Build the figure bundle of a well fixture on the registered screen's basis."""
    table = _pca_table(wells)
    channels = channel_map(FIGURES_SLUG)
    return build_figure_bundle(
        table,
        feature_columns=figure_feature_columns(table.feature_columns, channels),
        channels=channels,
        compound_labels=compound_labels,
    )


def _sizes_by_well(trace: dict[str, Any]) -> dict[int, float]:
    """Return the marker size of each colouring-fixture well a trace draws."""
    wells = _well_order(trace)
    size = trace["marker"]["size"]
    values = _decode_array(size).tolist() if isinstance(size, dict | list) else [size] * len(wells)
    return dict(zip(wells, values, strict=True))


class DrrPcaOverlayTests(SimpleTestCase):
    """What one compound's overlay draws, and how it joins a colouring."""

    def setUp(self) -> None:
        """Build the colouring fixture's bundle."""
        self.bundle = _bundle(COLOURING_WELLS)

    def test_only_compounds_with_a_fitted_dosed_well_get_an_overlay(self) -> None:
        """No overlay for the near-empty CBK25, the positive control or the DMSO wells."""
        self.assertEqual(sorted(self.bundle.pca_overlays), OVERLAID)

    def test_an_overlay_carries_its_traces_only(self) -> None:
        """Wells, then the dose line: no layout, so any colouring's layout stands."""
        overlay = self.bundle.pca_overlays["CBK11"]
        wells, line = overlay["data"]

        self.assertEqual(set(overlay), {"data"})
        self.assertEqual((wells["name"], wells["mode"]), ("CBK11", "markers"))
        self.assertEqual(
            (line["name"], line["mode"]), (f"CBK11{PCA_OVERLAY_CENTROID_SUFFIX}", "lines+markers")
        )
        self.assertEqual(wells["marker"]["color"], PCA_OVERLAY_COLOUR)
        self.assertEqual(line["line"]["color"], PCA_OVERLAY_COLOUR)

    def test_an_overlay_draws_its_compound_s_fitted_wells_at_their_view_sizes(self) -> None:
        """Each well where the default view draws it, as large as the view draws it."""
        default = self.bundle.figures["pca"]
        view_sizes: dict[int, float] = {}
        for trace in default["data"]:
            view_sizes.update(_sizes_by_well(trace))

        for cbkid in ("CBK11", "CBK310015", "DO8167002"):
            with self.subTest(cbkid=cbkid):
                wells = self.bundle.pca_overlays[cbkid]["data"][0]
                sizes = _sizes_by_well(wells)

                self.assertEqual(sorted(sizes), _wells_of(cbkid))
                self.assertEqual(sizes, {well: view_sizes[well] for well in sizes})

    def test_the_antivirals_keep_their_fixed_names(self) -> None:
        """The index files Nirmatrelvir as a control (FREYA-3126); the overlay does not."""
        bundle = _bundle(
            COLOURING_WELLS,
            compound_labels={"DO8167002": "DO8167002 (control)", "CBK11": "compoundK (CBK11)"},
        )

        self.assertEqual(bundle.pca_overlays["DO8167002"]["data"][0]["name"], "Nirmatrelvir")
        self.assertEqual(bundle.pca_overlays["CBK11"]["data"][0]["name"], "compoundK (CBK11)")

    def test_the_centroids_run_in_ascending_dose_one_per_fitted_dose(self) -> None:
        """Each dose's fitted wells averaged, lowest dose first; the near-empty well left out."""
        bundle = _bundle(OVERLAY_WELLS)
        line = bundle.pca_overlays["CBK31"]["data"][1]
        fitted = [index for index, well in enumerate(OVERLAY_WELLS) if well[3] >= 50]
        centre = sum(index + 1 for index in fitted) / len(fitted)

        self.assertEqual(
            [round(value, 6) for value in _decode_array(line["x"]).tolist()],
            [round(position - centre, 6) for position in (2.0, 3.0, 2.5)],
        )
        sizes = _decode_array(line["marker"]["size"]).tolist()
        self.assertEqual(sizes, sorted(set(sizes)))

    def test_combining_draws_the_overlay_above_every_trace_of_the_view(self) -> None:
        """The view's traces and layout unchanged, then the overlay's two traces last."""
        overlay = self.bundle.pca_overlays["CBK11"]

        for colouring, view in (
            (PCA_DEFAULT_COLOURING, self.bundle.figures["pca"]),
            *self.bundle.pca_colourings.items(),
        ):
            with self.subTest(colouring=colouring):
                traces = list(view["data"])
                combined = combine_pca_overlay(view, overlay)

                self.assertEqual(combined["data"][:-2], traces)
                self.assertEqual(combined["data"][-2:], overlay["data"])
                self.assertEqual(combined["layout"], view["layout"])
                self.assertEqual(view["data"], traces)


STAU_KEY = artefact_key("[stau]")

# CBK2 has no overlay and no radar; CBK4 has a radar but no fitted well, so the PCA
# picker must not offer it while the radar picker does.
OVERLAY_INDEX_ROWS: dict[str, list[Any]] = {
    "cbkid": ["CBK1", "CBK2", "[stau]", "CBK4"],
    "kind": ["compound", "compound", "control", "compound"],
    "name": ["Remdesivir", "aloxistatin", None, "compoundD"],
    "radar_key": ["CBK1", None, STAU_KEY, "CBK4"],
    "pca_key": ["CBK1", None, STAU_KEY, None],
}


def _overlay(name: str) -> dict[str, Any]:
    """Return an overlay whose two trace names identify it."""
    return {
        "data": [
            {"type": "scatter", "name": f"{name} wells", "x": [3.0], "y": [4.0]},
            {
                "type": "scatter",
                "name": f"{name} centroids",
                "mode": "lines+markers",
                "x": [3.0],
                "y": [4.0],
            },
        ]
    }


class DrrPcaOverlayRouteTestCase(DrrPcaRouteTestCase):
    """The PCA route's page, with a compound index and two overlays on disk."""

    def setUp(self) -> None:
        """Write the index the route resolves keys through, and the overlays."""
        super().setUp()
        self.overlay_dir = self.pca_dir / "compound"
        self.overlay_dir.mkdir()
        self.write_index(OVERLAY_INDEX_ROWS)
        self.write_overlay("CBK1", _overlay("Remdesivir"))
        self.write_overlay(STAU_KEY, _overlay("Staurosporine"))

    def write_index(self, rows: dict[str, list[Any]]) -> None:
        """Write ``compounds.parquet``."""
        pl.DataFrame(rows).write_parquet(self.artefacts / "compounds.parquet")

    def write_overlay(self, key: str, payload: dict[str, Any] | str) -> None:
        """Write one overlay under ``figures/pca/compound/``, as precompute does."""
        text = payload if isinstance(payload, str) else json.dumps(payload)
        (self.overlay_dir / f"{key}.json").write_text(text, encoding="utf-8")


class DrrPcaOverlayRouteTests(DrrPcaOverlayRouteTestCase):
    """What the ``pca/`` route serves for a compound, and what it refuses."""

    def test_each_colouring_combines_with_a_compound(self) -> None:
        """The colouring's own trace, then the compound's wells and line on top."""
        for colouring, trace in VIEW_TRACES.items():
            with self.subTest(colouring=colouring):
                response = self.pca(colour=colouring, cbkid="CBK1")
                body = response.content.decode()

                self.assertEqual(response.status_code, 200)
                self.assertEqual(body.count('id="drr-pca"'), 1)
                self.assertEqual([name for name in VIEW_TRACES.values() if name in body], [trace])
                self.assertLess(body.index(trace), body.index("Remdesivir wells"))
                self.assertLess(body.index("Remdesivir wells"), body.index("Remdesivir centroids"))

    def test_the_caption_names_the_compound(self) -> None:
        """The colouring's caption, then one sentence on what is drawn on top."""
        body = self.pca(colour="moa", cbkid="CBK1").content.decode()

        self.assertIn(
            escape(f"{CAPTIONS['moa']} {_PCA_OVERLAY_CAPTION.format(label='Remdesivir (CBK1)')}"),
            body,
        )

    def test_no_compound_is_the_plain_colouring(self) -> None:
        """The picker's "None" sends an empty id, which draws no overlay."""
        body = self.pca(colour="moa", cbkid="").content.decode()

        self.assertIn(VIEW_TRACES["moa"], body)
        self.assertNotIn("Remdesivir wells", body)
        self.assertIn(escape(CAPTIONS["moa"]), body)
        self.assertNotIn(escape(_PCA_OVERLAY_CAPTION.format(label="")), body)

    def test_a_bracketed_id_round_trips(self) -> None:
        """A control id such as ``[stau]`` travels in the query string and finds its overlay."""
        response = self.pca(colour="population", cbkid="[stau]")

        self.assertContains(response, "Staurosporine wells")
        self.assertContains(response, escape("[stau] (control)"))

    def test_an_unknown_compound_or_one_without_an_overlay_is_404_before_any_path(self) -> None:
        """Only an id the index gives a ``pca_key`` is looked up, so no request value is a path.

        The default colouring is read from the snippet, so no path is resolved for it.
        """
        with patch("cms.pages.drr_dataset.resolve_file_in_directory") as resolve:
            for cbkid in ("CBK404", "CBK2", "CBK4", "cbk1", "../summary", "CBK1.json", "stau"):
                with self.subTest(cbkid=cbkid):
                    response = self.pca(colour=PCA_DEFAULT_COLOURING, cbkid=cbkid)
                    self.assertEqual(response.status_code, 404)

        resolve.assert_not_called()
        self.assertIn('id="drr-pca"', self.page_body())

    def test_an_unknown_colouring_is_404_whatever_the_compound(self) -> None:
        """The colouring is checked first, so a valid compound cannot widen it."""
        with patch("cms.pages.drr_dataset.resolve_file_in_directory") as resolve:
            self.assertEqual(self.pca(colour="umap", cbkid="CBK1").status_code, 404)

        resolve.assert_not_called()

    def test_a_missing_overlay_is_404_and_leaves_the_page_s_figure_standing(self) -> None:
        """An overlay the run did not write costs the swap, not the page."""
        (self.overlay_dir / "CBK1.json").unlink()

        self.assertEqual(self.pca(colour="moa", cbkid="CBK1").status_code, 404)
        self.assertIn('id="drr-pca"', self.page_body())

    def test_an_unreadable_or_malformed_overlay_is_404(self) -> None:
        """A truncated file, or JSON that is not an overlay, is refused rather than drawn."""
        for payload in ("{not json", "[1, 2]", '{"data": {}}'):
            with self.subTest(payload=payload):
                self.write_overlay("CBK1", payload)

                self.assertEqual(self.pca(colour="moa", cbkid="CBK1").status_code, 404)

    def test_a_poisoned_key_is_refused_by_the_downloads_guard(self) -> None:
        """Even an index pointing out of the directory cannot reach a file there.

        The default colouring is read from the snippet, so the overlay is the one
        path this request resolves.
        """
        (self.artefacts.parent / "escaped.json").write_text(
            json.dumps(_overlay("Escaped")), encoding="utf-8"
        )
        self.write_index(
            {**OVERLAY_INDEX_ROWS, "pca_key": ["../../../../escaped", None, None, None]}
        )

        with patch(
            "cms.pages.drr_dataset.resolve_file_in_directory", wraps=resolve_file_in_directory
        ) as resolve:
            response = self.pca(colour=PCA_DEFAULT_COLOURING, cbkid="CBK1")

        self.assertEqual(response.status_code, 404)
        resolve.assert_called_once_with(
            self.artefacts, "figures/pca/compound/../../../../escaped.json"
        )


class DrrPcaCompoundPickerTests(DrrPcaOverlayRouteTestCase):
    """The compound picker beside the colour-by picker."""

    def test_the_picker_offers_only_compounds_with_an_overlay(self) -> None:
        """Labelled as the radar picker labels them; CBK4 has a radar but no overlay."""
        context = self.context()

        self.assertEqual(
            [(option["cbkid"], option["label"]) for option in context["pca_compounds"]],
            [("CBK1", "Remdesivir (CBK1)"), ("[stau]", "[stau] (control)")],
        )
        self.assertIn("CBK4", [option["cbkid"] for option in context["radar_compounds"]])

    def test_one_form_carries_both_choices_and_starts_on_no_compound(self) -> None:
        """Colour, then compound, in the one form that swaps the PCA, "None" selected."""
        body = self.page_body()

        self.assertEqual(body.count('hx-target="#drr-pca"'), 1)
        self.assertIn('<select id="drr-pca-compound" name="cbkid"', body)
        self.assertIn('<label for="drr-pca-compound"', body)
        self.assertInHTML('<option value="" selected>None</option>', body)
        start = body.index('id="drr-pca-compound"')
        options = body[start : body.index("</select>", start)]
        self.assertInHTML('<option value="[stau]">[stau] (control)</option>', options)
        self.assertNotIn('value="CBK4"', options)
        positions = [
            body.index('hx-target="#drr-pca"'),
            body.index('id="drr-pca-colour"'),
            body.index('id="drr-pca-compound"'),
            body.index("</form>", body.index('id="drr-pca-compound"')),
            body.index('id="drr-pca"'),
        ]
        self.assertEqual(positions, sorted(positions))

    def test_with_one_colouring_a_hidden_field_carries_the_default(self) -> None:
        """Nothing to pick a colouring from, but the route still needs one."""
        for colouring in ("morphology", "moa"):
            (self.pca_dir / f"{colouring}.json").unlink()

        body = self.page_body()

        self.assertNotIn('id="drr-pca-colour"', body)
        self.assertInHTML('<input type="hidden" name="colour" value="population">', body)
        self.assertIn('<select id="drr-pca-compound" name="cbkid"', body)
        self.assertIn('hx-get="' + self.page.url + 'pca/"', body)

    def test_an_index_from_before_the_overlays_offers_no_compound(self) -> None:
        """An index without ``pca_key`` keeps the colour-by picker and adds nothing."""
        self.write_index(
            {key: value for key, value in OVERLAY_INDEX_ROWS.items() if key != "pca_key"}
        )

        body = self.page_body()

        self.assertNotIn("pca_compounds", self.context())
        self.assertNotIn('id="drr-pca-compound"', body)
        self.assertIn('id="drr-pca-colour"', body)


class DrrPcaOverlayCacheTests(DrrPcaOverlayRouteTestCase):
    """The render cache keys on the compound as well as the colouring."""

    def test_two_compounds_cannot_serve_each_other_s_render(self) -> None:
        """The second compound's request is not the first's cached HTML."""
        self.assertContains(self.pca(colour="moa", cbkid="CBK1"), "Remdesivir wells")

        second = self.pca(colour="moa", cbkid="[stau]")

        self.assertContains(second, "Staurosporine wells")
        self.assertNotContains(second, "Remdesivir wells")

    def test_a_compound_and_a_colouring_combine_without_crossing(self) -> None:
        """One compound over two colourings, then the colouring alone: three renders."""
        self.assertContains(self.pca(colour="moa", cbkid="CBK1"), VIEW_TRACES["moa"])

        over_population = self.pca(colour="population", cbkid="CBK1")
        alone = self.pca(colour="moa")

        self.assertContains(over_population, VIEW_TRACES["population"])
        self.assertNotContains(over_population, VIEW_TRACES["moa"])
        self.assertContains(over_population, "Remdesivir wells")
        self.assertNotContains(alone, "Remdesivir wells")

    def test_a_new_source_file_hash_re_renders_an_overlay(self) -> None:
        """A re-run's overlay reaches the reader rather than yesterday's cached HTML."""
        self.assertContains(self.pca(colour="moa", cbkid="CBK1"), "Remdesivir wells")

        self.write_overlay("CBK1", _overlay("Rewritten"))
        self.data.source_file_hash = "hash-two"
        self.data.save()

        self.assertContains(self.pca(colour="moa", cbkid="CBK1"), "Rewritten wells")
