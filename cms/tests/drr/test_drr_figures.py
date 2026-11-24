"""Tests for the channel map, the figure basis and its clip, and the PCA's fit and styling.

FREYA-2923 and 2968 own the basis and the clip; FREYA-3200 the PCA's fit and styling.
Every fixture here carries a column in **each of the five** imaging channels. That
is deliberate: the A549-ACE2 and Vero E6 screens name opposite stains with the same
two tokens, so a fixture that omits a channel cannot tell an inverted map from a
correct one — which is how the inverted reading survived three sessions of work on
these figures.
"""

from __future__ import annotations

import base64
from itertools import pairwise
from unittest.mock import patch

import numpy as np
import plotly.graph_objects as go
import polars as pl
from django.test import SimpleTestCase

from dashboard_visualisation.drr.channels import (
    channel_map,
    figure_feature_columns,
    present_channels,
)
from dashboard_visualisation.drr.figures import (
    FEATURE_BASIS_FIGURE_IDS,
    FIGURE_CLIP_BOUND,
    NEAR_EMPTY_NUCLEI_THRESHOLD,
    PCA_CONTROL_MARKER_SIZE,
    build_all_figures,
    clip_figure_values,
    clip_report,
    figure_basis_token,
    pca_fit_report,
)
from dashboard_visualisation.drr.loader import FeatureTable
from dashboard_visualisation.drr.radar import POPULATION_LABELS, population_label
from dashboard_visualisation.utils.plotly import figure_to_json

SLUG = "sars-cov2-a549-ace2-validation"

# Nine feature columns: one per channel in Intensity, the ER channel under
# Granularity, RNA under RadialDistribution, and two that name no channel at all.
# The two antibody columns are the ones the figure basis must drop, and one of
# them is a Correlation pair naming a second channel alongside it.
AREA_SHAPE_COLUMN = "AreaShape_Area_nuclei"
INTENSITY_COLUMNS = [
    "Intensity_MeanIntensity_illumHOECHST_nuclei",
    "Intensity_MeanIntensity_illumSYTO_cells",
    "Intensity_MeanIntensity_illumPHAandWGA_cells",
]
GRANULARITY_COLUMN = "Granularity_1_illumMITO_cells"
RADIAL_COLUMN = "RadialDistribution_MeanFrac_illumSYTO_1of4_cells"
ANTIBODY_COLUMNS = [
    "Intensity_MeanIntensity_illumCONC_nuclei",
    "Correlation_Correlation_illumCONC_illumHOECHST_cytoplasm",
]
NEIGHBORS_COLUMN = "Neighbors_FirstClosestDistance_Adjacent_cells"

FEATURE_COLUMNS = [
    AREA_SHAPE_COLUMN,
    *INTENSITY_COLUMNS,
    GRANULARITY_COLUMN,
    RADIAL_COLUMN,
    *ANTIBODY_COLUMNS,
    NEIGHBORS_COLUMN,
]

# Per-column values, identical within a perturbation class: the two ``trt`` rows
# carry these and the two controls carry half of each. The antibody columns are an
# order of magnitude larger than everything else, so a figure that still includes
# them cannot match the expected means by coincidence.
TRT_VALUES = {
    AREA_SHAPE_COLUMN: 5.0,
    INTENSITY_COLUMNS[0]: 1.0,
    INTENSITY_COLUMNS[1]: 2.0,
    INTENSITY_COLUMNS[2]: 3.0,
    GRANULARITY_COLUMN: 7.0,
    RADIAL_COLUMN: 11.0,
    ANTIBODY_COLUMNS[0]: 100.0,
    ANTIBODY_COLUMNS[1]: 50.0,
    NEIGHBORS_COLUMN: 9.0,
}


# Three morphology columns pushed to the clip's three cases: the feature table's
# own measured maximum and minimum, and a value sitting exactly on the
# bound, which the closed range must leave alone. The halved control rows stay
# out of range too, so every row of both columns is clipped.
OUT_OF_RANGE_VALUES = {
    AREA_SHAPE_COLUMN: 1814.135748,
    INTENSITY_COLUMNS[0]: -210.759515,
    NEIGHBORS_COLUMN: 50.0,
}


def _decode_array(payload: dict | list) -> np.ndarray:
    """Return a numeric array from figure JSON, decoding Plotly's base64 form.

    Plotly serialises a 2-D array to base64 with a ``shape`` key and a 1-D one
    without, and a small enough array as a plain list, so all three forms are
    handled rather than assumed.
    """
    if isinstance(payload, list):
        return np.asarray(payload)
    array = np.frombuffer(base64.b64decode(payload["bdata"]), dtype=payload["dtype"])
    shape = payload.get("shape")
    if shape:
        return array.reshape(tuple(int(part) for part in shape.split(",")))
    return array


def _feature_table(values: dict[str, float] | None = None) -> FeatureTable:
    """Return a four-profile table: two ``trt`` rows, then both halved controls.

    The two control rows are the populations the radars contrast — the infected
    DMSO baseline and the uninfected wells — because a table missing either now
    fails the run rather than widening to every profile (FREYA-2636). Every
    well has a typical nuclei count, so the PCA fits all four (FREYA-3200).
    """
    row_values = {**TRT_VALUES, **(values or {})}
    frame = pl.DataFrame(
        {
            "pert_type": ["trt", "trt", "negcon", "non-inf"],
            "cbkid": ["CBK1", "CBK1", "CBK2", "CBK2"],
            "cmpd_conc": [1.0, 10.0, 0.3, 0.3],
            "Count_nuclei": [240.0, 240.0, 240.0, 240.0],
            **{
                column: [value, value, value / 2, value / 2] for column, value in row_values.items()
            },
        }
    )
    return FeatureTable(
        frame=frame,
        metadata_columns=["pert_type", "cbkid", "cmpd_conc", "Count_nuclei"],
        feature_columns=FEATURE_COLUMNS,
    )


class DrrChannelMapTests(SimpleTestCase):
    """The screen's token-to-stain vocabulary, and what it excludes."""

    def test_each_token_is_paired_with_this_screen_s_own_stain(self) -> None:
        """The whole map is asserted: a swapped pair fails here before anywhere else."""
        channels = channel_map(SLUG)

        self.assertEqual(
            {channel.column_tag: (channel.label, channel.stain) for channel in channels},
            {
                "illumHOECHST": ("HOECHST", "Hoechst 33342"),
                "illumSYTO": ("SYTO", "SYTO 13/14"),
                "illumPHAandWGA": ("PHAandWGA", "Phalloidin + WGA"),
                "illumMITO": ("CONC", "Concanavalin A"),
                "illumCONC": ("SARS-CoV-2-N-Ab", "SARS-CoV-2 nucleocapsid antibody"),
            },
        )

    def test_the_antibody_is_the_only_channel_the_figures_exclude(self) -> None:
        """Four morphology channels in, the infection readout out."""
        channels = channel_map(SLUG)

        excluded = [channel.column_tag for channel in channels if not channel.in_figures]
        self.assertEqual(excluded, ["illumCONC"])

    def test_an_unregistered_slug_raises_and_names_what_is_registered(self) -> None:
        """No map is guessed for an unknown screen: two screens invert two tokens."""
        with self.assertRaises(ValueError) as raised:
            channel_map("vero-e6-primary")

        message = str(raised.exception)
        self.assertIn("vero-e6-primary", message)
        self.assertIn(SLUG, message)


class DrrFigureBasisTests(SimpleTestCase):
    """Which feature columns the figures may compute on."""

    def test_every_antibody_column_is_dropped_correlation_pairs_included(self) -> None:
        """A Correlation column naming the antibody goes too — that is how 323 was counted."""
        columns = figure_feature_columns(FEATURE_COLUMNS, channel_map(SLUG))

        self.assertEqual(len(columns), len(FEATURE_COLUMNS) - len(ANTIBODY_COLUMNS))
        for column in ANTIBODY_COLUMNS:
            self.assertNotIn(column, columns)

    def test_the_other_four_channels_survive(self) -> None:
        """Only the excluded channel's columns go; the morphology basis keeps its own."""
        columns = figure_feature_columns(FEATURE_COLUMNS, channel_map(SLUG))

        for token in ("illumHOECHST", "illumSYTO", "illumPHAandWGA", "illumMITO"):
            self.assertTrue(any(token in column for column in columns), token)

    def test_the_pca_matrix_is_the_figure_basis_and_nothing_wider(self) -> None:
        """The matrix the figures consume has one column per figure-basis feature."""
        table = _feature_table()
        columns = figure_feature_columns(table.feature_columns, channel_map(SLUG))

        self.assertEqual(table.numeric_matrix(columns).shape, (4, 7))
        self.assertEqual(table.numeric_matrix().shape, (4, 9))

    def test_emptying_a_non_empty_feature_set_is_refused(self) -> None:
        """A map that excludes everything does not describe the table it was given."""
        with self.assertRaisesMessage(ValueError, "illumCONC"):
            figure_feature_columns(ANTIBODY_COLUMNS, channel_map(SLUG))


class DrrChannelReportTests(SimpleTestCase):
    """What the summary panel is given to publish."""

    def test_channels_are_reported_in_display_order(self) -> None:
        """Four morphology channels, then the antibody, as FREYA-2923 states."""
        reported = present_channels(FEATURE_COLUMNS, channel_map(SLUG))

        self.assertEqual(
            [channel["label"] for channel in reported],
            ["HOECHST", "SYTO", "PHAandWGA", "CONC", "SARS-CoV-2-N-Ab"],
        )
        self.assertEqual([channel["in_figures"] for channel in reported], [True] * 4 + [False])

    def test_a_channel_absent_from_the_columns_is_not_reported(self) -> None:
        """The panel describes the table in hand, not the vocabulary in the abstract."""
        reported = present_channels([GRANULARITY_COLUMN], channel_map(SLUG))

        self.assertEqual(len(reported), 1)
        self.assertEqual(reported[0]["stain"], "Concanavalin A")
        self.assertEqual(reported[0]["measures"], "endoplasmic reticulum (ER)")


class DrrFigureBuildTests(SimpleTestCase):
    """The basis reaches the figures, not only the column list."""

    def setUp(self) -> None:
        """Build every figure on the figure basis of the fixture table."""
        table = _feature_table()
        columns = figure_feature_columns(table.feature_columns, channel_map(SLUG))
        self.figures = build_all_figures(table, feature_columns=columns, channels=channel_map(SLUG))

    def _radar_axes(self, figure_id: str) -> dict[str, float | None]:
        """Return one radar's values, keyed by axis label and minus the closing point."""
        trace = self.figures[figure_id]["data"][0]
        return dict(zip(trace["theta"][:-1], trace["r"][:-1], strict=True))

    def test_every_feature_basis_figure_is_built(self) -> None:
        """Every feature-derived figure is built."""
        self.assertEqual(set(self.figures), set(FEATURE_BASIS_FIGURE_IDS))

    def test_the_radar_averages_the_figure_basis_only(self) -> None:
        """Each stain keeps its own axis, and the antibody's 100.0 is on none of them."""
        axes = self._radar_axes("radar_compound")

        self.assertAlmostEqual(axes["DNA I"], 1.0, places=6)
        self.assertAlmostEqual(axes["RNA I"], 2.0, places=6)
        self.assertAlmostEqual(axes["AGP I"], 3.0, places=6)
        self.assertAlmostEqual(axes["Area/shape N"], 5.0, places=6)
        self.assertAlmostEqual(axes["ER G"], 7.0, places=6)
        self.assertAlmostEqual(axes["RNA RD"], 11.0, places=6)
        self.assertAlmostEqual(axes["Neighbors C"], 9.0, places=6)

    def test_an_axis_left_with_no_column_reports_nothing_not_the_antibody(self) -> None:
        """The only Correlation column here names the antibody, so every pair is a gap.

        A gap, not a zero: on a ring of 24 axes a plotted 0.0 reads as a measured
        absence of signal, which is a different claim from having no column.
        """
        axes = self._radar_axes("radar_compound")

        self.assertIsNone(axes["DNA-RNA"])
        self.assertEqual([label for label, value in axes.items() if value is None].count("ER I"), 1)

    def test_the_infection_radar_plots_the_uninfected_wells(self) -> None:
        """Its condition is ``non-inf``, on the same ring and the same basis.

        The input is MAD-normalised against each plate's infected DMSO, so those
        wells sit at ~0 by construction and are the baseline rather than the
        plotted condition. Here that is the halved control row.
        """
        axes = self._radar_axes("radar_infected")

        self.assertAlmostEqual(axes["DNA I"], 0.5, places=6)
        self.assertAlmostEqual(axes["ER G"], 3.5, places=6)


class DrrPopulationLabelTests(SimpleTestCase):
    """What a reader sees for each population, and what stays a key (FREYA-3009)."""

    @staticmethod
    def _table_with(extra_pert_type: str) -> FeatureTable:
        """Return the fixture table plus one more profile carrying ``extra_pert_type``."""
        table = _feature_table()
        extra = table.frame.head(1).with_columns(
            pl.lit(extra_pert_type).alias("pert_type"),
            pl.lit("CBK3").alias("cbkid"),
        )
        return FeatureTable(
            frame=pl.concat([table.frame, extra]),
            metadata_columns=table.metadata_columns,
            feature_columns=table.feature_columns,
        )

    @staticmethod
    def _figures(table: FeatureTable) -> dict:
        """Build every figure of ``table`` on its figure basis."""
        channels = channel_map(SLUG)
        columns = figure_feature_columns(table.feature_columns, channels)
        return build_all_figures(table, feature_columns=columns, channels=channels)

    def test_the_names_are_keyed_by_exactly_the_raw_tokens(self) -> None:
        """The mapping names the four populations the screen has, and nothing else."""
        self.assertEqual(set(POPULATION_LABELS), {"negcon", "non-inf", "poscon", "trt"})

    def test_each_population_has_its_plain_language_name(self) -> None:
        """Infected and uninfected are the DMSO controls, named as the authors name them."""
        self.assertEqual(population_label("negcon"), "Infected control (DMSO)")
        self.assertEqual(population_label("non-inf"), "Uninfected control (DMSO)")
        self.assertEqual(population_label("poscon"), "Positive control")
        self.assertEqual(population_label("trt"), "Treated")

    def test_the_pca_legend_names_every_population_and_no_token(self) -> None:
        """One trace per population, bottom to top, so no control hides under Treated."""
        pca = self._figures(self._table_with("poscon"))["pca"]

        self.assertEqual(
            [trace["name"] for trace in pca["data"]],
            [
                "Treated",
                "Positive control",
                "Infected control (DMSO)",
                "Uninfected control (DMSO)",
            ],
        )
        self.assertEqual(pca["layout"]["legend"]["title"]["text"], "Well population")

    def test_the_raw_token_stays_the_data_value(self) -> None:
        """Only the display is renamed: the table the downloads publish is untouched."""
        table = self._table_with("poscon")

        self._figures(table)

        self.assertEqual(
            table.frame["pert_type"].to_list(), ["trt", "trt", "negcon", "non-inf", "poscon"]
        )

    def test_an_unnamed_population_fails_rather_than_rendering_its_token(self) -> None:
        """A token with no name stops the build, naming the token."""
        for token in ("mystery", ""):
            with self.subTest(token=token):
                with self.assertRaisesMessage(ValueError, repr(token)):
                    population_label(token)
                with self.assertRaisesMessage(ValueError, repr(token)):
                    self._figures(self._table_with(token))


class DrrFigureClipTests(SimpleTestCase):
    """The clip the authors' pipeline applies, on the figure path only (FREYA-2968)."""

    def setUp(self) -> None:
        """Take a table whose morphology values run past the bound in both directions."""
        self.table = _feature_table(OUT_OF_RANGE_VALUES)
        self.columns = figure_feature_columns(self.table.feature_columns, channel_map(SLUG))

    def _figures(self, bound: float | None = None) -> dict:
        """Build every figure, optionally against a different clip bound."""
        if bound is None:
            return build_all_figures(
                self.table, feature_columns=self.columns, channels=channel_map(SLUG)
            )
        with patch("dashboard_visualisation.drr.figures.FIGURE_CLIP_BOUND", bound):
            return build_all_figures(
                self.table, feature_columns=self.columns, channels=channel_map(SLUG)
            )

    @staticmethod
    def _radar_axes(figures: dict, figure_id: str) -> dict[str, float | None]:
        """Return one radar's values, keyed by axis label and minus the closing point."""
        trace = figures[figure_id]["data"][0]
        return dict(zip(trace["theta"][:-1], trace["r"][:-1], strict=True))

    @staticmethod
    def _pc1_spread(figures: dict) -> float:
        """Return the largest absolute PC1 score across a PCA figure's traces."""
        return max(
            float(np.abs(_decode_array(trace["x"])).max()) for trace in figures["pca"]["data"]
        )

    def test_the_bound_is_the_published_one(self) -> None:
        """50 in MAD units, which is where the paper's pipeline clips."""
        self.assertEqual(FIGURE_CLIP_BOUND, 50.0)

    def test_each_of_the_three_cases_lands_where_it_should(self) -> None:
        """Above the bound, below it, and inside: 50, -50 and the value itself."""
        clipped = clip_figure_values(np.array([[1814.135748, -210.759515, 7.0, 50.0, -50.0]]))

        self.assertEqual(clipped.tolist(), [[50.0, -50.0, 7.0, 50.0, -50.0]])

    def test_the_callers_own_array_is_left_alone(self) -> None:
        """The clip returns a new array, so nothing upstream of it is rewritten."""
        matrix = np.array([[1814.135748]])
        clip_figure_values(matrix)

        self.assertEqual(matrix.tolist(), [[1814.135748]])

    def test_the_clip_reaches_the_figure_matrix_and_not_the_frame(self) -> None:
        """The radar sees 50; the frame the downloads are written from still sees 1814."""
        axes = self._radar_axes(self._figures(), "radar_compound")

        self.assertAlmostEqual(axes["Area/shape N"], FIGURE_CLIP_BOUND, places=6)
        self.assertEqual(self.table.frame[AREA_SHAPE_COLUMN].to_list()[0], 1814.135748)

    def test_a_value_on_the_bound_is_not_moved(self) -> None:
        """The range is closed: the Neighbors axis keeps its 50.0 rather than reporting less."""
        axes = self._radar_axes(self._figures(), "radar_compound")

        self.assertAlmostEqual(axes["Neighbors C"], 50.0, places=6)

    def test_no_out_of_range_value_reaches_a_radar(self) -> None:
        """Every plotted mean is a mean of clipped values, so none can exceed the bound."""
        figures = self._figures()

        for figure_id in ("radar_compound", "radar_infected"):
            for radius in figures[figure_id]["data"][0]["r"]:
                if radius is None:
                    continue
                self.assertLessEqual(abs(float(radius)), FIGURE_CLIP_BOUND, figure_id)

    def test_the_pca_is_computed_on_the_clipped_values(self) -> None:
        """The outlier stops driving the spread once the bound applies.

        The percent-variance annotation cannot show this on a fixture whose rows
        are proportional — PC1 explains everything either way — so the scores
        themselves are what say which values the decomposition saw.
        """
        clipped = self._pc1_spread(self._figures())
        unclipped = self._pc1_spread(self._figures(bound=1e9))

        self.assertLess(clipped * 5, unclipped)

    def test_the_report_counts_what_moved_and_names_the_worst_columns(self) -> None:
        """Both out-of-range columns, all four rows each; the on-bound column is absent."""
        report = clip_report(self.table, self.columns)

        self.assertEqual(report["lower"], -FIGURE_CLIP_BOUND)
        self.assertEqual(report["upper"], FIGURE_CLIP_BOUND)
        self.assertEqual(report["n_values"], 4 * len(self.columns))
        self.assertEqual(report["n_values_clipped"], 8)
        self.assertEqual(report["n_columns_clipped"], 2)
        self.assertEqual(
            report["most_affected_columns"],
            [
                {"column": AREA_SHAPE_COLUMN, "n_clipped": 4},
                {"column": INTENSITY_COLUMNS[0], "n_clipped": 4},
            ],
        )

    def test_a_table_inside_the_bound_reports_nothing_clipped(self) -> None:
        """The report describes this run, not the possibility of clipping."""
        report = clip_report(_feature_table(), self.columns)

        self.assertEqual(report["n_values_clipped"], 0)
        self.assertEqual(report["most_affected_columns"], [])

    def test_the_basis_token_carries_the_column_count_then_the_bound(self) -> None:
        """A fixed order, so the digest it feeds is stable across runs."""
        self.assertEqual(
            figure_basis_token(self.columns),
            "figure-basis:7:50.0:min-nuclei-50:labels-9b654e1eb7fc",
        )

    def test_the_basis_token_moves_with_the_bound_and_with_the_basis(self) -> None:
        """Either half of "how the figures were computed" busts the render cache."""
        with patch("dashboard_visualisation.drr.figures.FIGURE_CLIP_BOUND", 25.0):
            self.assertEqual(
                figure_basis_token(self.columns),
                "figure-basis:7:25.0:min-nuclei-50:labels-9b654e1eb7fc",
            )

        self.assertNotEqual(
            figure_basis_token(self.columns),
            figure_basis_token(self.columns[:-1]),
        )

    def test_the_basis_token_moves_with_the_population_names(self) -> None:
        """A reworded label or legend title busts the render cache (FREYA-3009)."""
        before = figure_basis_token(self.columns)
        reworded = {**POPULATION_LABELS, "negcon": "Infected DMSO wells"}

        with patch("dashboard_visualisation.drr.radar.POPULATION_LABELS", reworded):
            self.assertNotEqual(figure_basis_token(self.columns), before)
        with patch("dashboard_visualisation.drr.radar.POPULATION_LEGEND_TITLE", "Population"):
            self.assertNotEqual(figure_basis_token(self.columns), before)
        self.assertEqual(figure_basis_token(self.columns), before)


# One well per entry: ``(pert_type, cbkid, dose in µM, nuclei)``. Well 3 is
# near-empty, at a dose no fitted well has; well 4 sits exactly on the threshold,
# which the fit keeps. The positive control's dose is below every treated dose,
# so a dose range that counted the controls would say so.
PCA_WELLS: list[tuple[str, str, float, float]] = [
    ("trt", "CBK1", 0.1, 240.0),
    ("trt", "CBK1", 1.0, 240.0),
    ("trt", "CBK1", 10.0, 240.0),
    ("trt", "CBK2", 100.0, 49.0),
    ("trt", "CBK2", 30.0, 50.0),
    ("poscon", "[stau]", 0.01, 240.0),
    ("negcon", "CBK281357", 0.3, 240.0),
    ("non-inf", "CBK281357", 0.3, 240.0),
    ("trt", "CBK310015", 0.3, 240.0),
    ("trt", "CBK310015", 30.0, 240.0),
    ("trt", "DO8167002", 3.0, 240.0),
    ("trt", "CBK310023", 10.0, 240.0),
]
NEAR_EMPTY_WELL = 3
ON_THRESHOLD_WELL = 4
TREATED_WELLS = [0, 1, 2, 4]
ANTIVIRAL_WELLS = {"Remdesivir": [8, 9], "Nirmatrelvir": [10], "GC376": [11]}
CONTROL_TRACES = ["Positive control", "Infected control (DMSO)", "Uninfected control (DMSO)"]

# A second component for the variance-share test: the near-empty well is the
# outlier on it, so the shares move when it enters the fit.
NEIGHBORS_VALUES = [0.0, 1.0, 0.0, 40.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0]


def _pca_table(
    wells: list[tuple[str, str, float, float]] | None = None,
    *,
    neighbors: list[float] | None = None,
) -> FeatureTable:
    """Return one profile per well, each placed on PC1 by its own position.

    Well ``i`` carries ``i + 1`` in the AreaShape column and zero in every other
    feature, so PC1 is that column centred over the fitted wells: each well's
    score names it, a trace's scores say exactly which wells it holds, and their
    centre says which wells were fitted. ``neighbors`` gives the Neighbors column
    values of its own, for a second component.
    """
    wells = PCA_WELLS if wells is None else wells
    features = {column: [0.0] * len(wells) for column in FEATURE_COLUMNS}
    features[AREA_SHAPE_COLUMN] = [float(index + 1) for index in range(len(wells))]
    if neighbors is not None:
        features[NEIGHBORS_COLUMN] = neighbors
    frame = pl.DataFrame(
        {
            "pert_type": [well[0] for well in wells],
            "cbkid": [well[1] for well in wells],
            "cmpd_conc": [well[2] for well in wells],
            "Count_nuclei": [well[3] for well in wells],
            **features,
        }
    )
    return FeatureTable(
        frame=frame,
        metadata_columns=["pert_type", "cbkid", "cmpd_conc", "Count_nuclei"],
        feature_columns=FEATURE_COLUMNS,
    )


def _build(table: FeatureTable, threshold: float | None = None) -> dict:
    """Build every figure of ``table``, optionally against another near-empty threshold."""
    channels = channel_map(SLUG)
    columns = figure_feature_columns(table.feature_columns, channels)
    if threshold is None:
        return build_all_figures(table, feature_columns=columns, channels=channels)
    with patch("dashboard_visualisation.drr.figures.NEAR_EMPTY_NUCLEI_THRESHOLD", threshold):
        return build_all_figures(table, feature_columns=columns, channels=channels)


def _expected_pc1(indices: list[int]) -> list[float]:
    """Return the PC1 scores ``_pca_table`` gives these wells, sorted."""
    positions = np.arange(1, len(PCA_WELLS) + 1, dtype=np.float64)
    fitted = np.array([well[3] >= NEAR_EMPTY_NUCLEI_THRESHOLD for well in PCA_WELLS])
    return sorted((positions - positions[fitted].mean())[indices].tolist())


def _traces(pca: dict) -> dict[str, dict]:
    """Return a PCA figure's traces keyed by legend name."""
    return {trace["name"]: trace for trace in pca["data"]}


def _pc1(trace: dict) -> list[float]:
    """Return one trace's PC1 scores, sorted."""
    return sorted(_decode_array(trace["x"]).tolist())


class DrrPcaFitTests(SimpleTestCase):
    """Which wells the PCA fits, and what that leaves alone (FREYA-3200)."""

    def setUp(self) -> None:
        """Build every figure of the well-by-well fixture."""
        self.pca = _build(_pca_table())["pca"]

    def test_the_threshold_is_the_agreed_one(self) -> None:
        """50 nuclei, the line the group's four defaults settled on 2026-11-20."""
        self.assertEqual(NEAR_EMPTY_NUCLEI_THRESHOLD, 50)

    def test_a_near_empty_well_is_neither_fitted_nor_drawn(self) -> None:
        """Every drawn score is centred on the fitted wells alone, and well 3 is not drawn.

        Had the near-empty well been fitted, the centre would move and every
        score with it; had it been drawn, there would be one point more.
        """
        drawn = sorted(score for trace in self.pca["data"] for score in _pc1(trace))
        fitted = [index for index in range(len(PCA_WELLS)) if index != NEAR_EMPTY_WELL]

        self.assertEqual(len(drawn), len(PCA_WELLS) - 1)
        for got, want in zip(drawn, _expected_pc1(fitted), strict=True):
            self.assertAlmostEqual(got, want, places=9)

    def test_a_well_at_exactly_the_threshold_is_kept(self) -> None:
        """The comparison is strict: 50 nuclei is not near-empty."""
        treated = _pc1(_traces(self.pca)["Treated"])

        self.assertEqual(len(treated), len(TREATED_WELLS))
        self.assertTrue(
            any(abs(score - _expected_pc1([ON_THRESHOLD_WELL])[0]) < 1e-9 for score in treated)
        )

    def test_the_axis_shares_are_of_the_fitted_wells(self) -> None:
        """Each axis title states its component's share of the fitted wells' variation."""
        table = _pca_table(neighbors=NEIGHBORS_VALUES)
        layout = _build(table)["pca"]["layout"]
        columns = figure_feature_columns(table.feature_columns, channel_map(SLUG))
        matrix = clip_figure_values(table.numeric_matrix(columns))
        fitted = table.frame["Count_nuclei"].to_numpy() >= NEAR_EMPTY_NUCLEI_THRESHOLD

        expected = self._variance_shares(matrix[fitted])
        for axis, component, want in (("xaxis", "PC1", expected[0]), ("yaxis", "PC2", expected[1])):
            self.assertEqual(
                layout[axis]["title"]["text"],
                f"{component} ({want:.1f}% of the fitted wells' variance)",
            )
        # Over every well the outlier would have moved the shares, so the
        # assertion above is sensitive to which wells were fitted.
        self.assertNotEqual(f"{self._variance_shares(matrix)[0]:.1f}", f"{expected[0]:.1f}")

    def test_the_axes_autorange(self) -> None:
        """No range is pinned, so the axes follow the fitted wells."""
        layout = self.pca["layout"]

        self.assertNotIn("range", layout.get("xaxis", {}))
        self.assertNotIn("range", layout.get("yaxis", {}))

    def test_the_radars_keep_every_well(self) -> None:
        """Only the PCA changes: the radars are identical whatever the threshold."""
        table = _pca_table(neighbors=NEIGHBORS_VALUES)
        at_threshold = _build(table)
        every_well = _build(table, threshold=0)

        for figure_id in ("radar_compound", "radar_infected"):
            self.assertEqual(at_threshold[figure_id], every_well[figure_id], figure_id)
        # The fit itself did move, so the comparison above is not vacuous.
        self.assertNotEqual(at_threshold["pca"], every_well["pca"])

    def test_the_basis_token_moves_with_the_threshold(self) -> None:
        """A changed threshold busts the render cache, as a changed clip bound does."""
        columns = figure_feature_columns(FEATURE_COLUMNS, channel_map(SLUG))
        before = figure_basis_token(columns)

        with patch("dashboard_visualisation.drr.figures.NEAR_EMPTY_NUCLEI_THRESHOLD", 100):
            moved = figure_basis_token(columns)

        self.assertNotEqual(moved, before)
        self.assertIn(":min-nuclei-100:", moved)

    def test_the_report_counts_the_fitted_and_the_near_empty_wells(self) -> None:
        """``summary.json`` is told the threshold and how many wells it leaves out."""
        self.assertEqual(
            pca_fit_report(_pca_table()),
            {
                "column": "Count_nuclei",
                "min_nuclei": 50,
                "n_wells_fitted": len(PCA_WELLS) - 1,
                "n_near_empty_wells": 1,
            },
        )

    def test_a_table_without_nuclei_counts_or_doses_fails_naming_the_column(self) -> None:
        """Neither column is guessed: an absent one stops the build, naming it."""
        for column in ("Count_nuclei", "cmpd_conc"):
            with self.subTest(column=column):
                table = _pca_table()
                without = FeatureTable(
                    frame=table.frame.drop(column),
                    metadata_columns=[name for name in table.metadata_columns if name != column],
                    feature_columns=table.feature_columns,
                )
                with self.assertRaisesMessage(ValueError, repr(column)):
                    _build(without)

    def test_an_incomplete_nuclei_count_or_dose_fails_naming_the_column(self) -> None:
        """A missing value is not read as near-empty, nor as the smallest dose."""
        for position, column in ((3, "Count_nuclei"), (2, "cmpd_conc")):
            with self.subTest(column=column):
                wells = [list(well) for well in PCA_WELLS]
                wells[0][position] = float("nan")
                with self.assertRaisesMessage(ValueError, repr(column)):
                    _build(_pca_table([tuple(well) for well in wells]))

    def test_a_table_with_no_fitted_well_fails(self) -> None:
        """An empty fit stops the build rather than drawing an empty figure."""
        with self.assertRaisesMessage(ValueError, "nothing to fit"):
            _build(_pca_table(), threshold=1e6)

    def test_a_named_population_with_no_place_in_the_order_fails(self) -> None:
        """A population the drawing order does not know would otherwise go undrawn."""
        wells = [*PCA_WELLS, ("extra", "CBK9", 1.0, 240.0)]
        labelled = {**POPULATION_LABELS, "extra": "Extra population"}

        with (
            patch("dashboard_visualisation.drr.radar.POPULATION_LABELS", labelled),
            self.assertRaisesMessage(ValueError, "no place in the PCA's drawing order"),
        ):
            _build(_pca_table(wells))

    @staticmethod
    def _variance_shares(matrix: np.ndarray) -> np.ndarray:
        """Return the percent variance of the first two components of a matrix."""
        eigenvalues = np.sort(np.linalg.eigvalsh(np.cov(matrix, rowvar=False, bias=True)))[::-1]
        return 100 * eigenvalues[:2] / eigenvalues.sum()


class DrrPcaStylingTests(SimpleTestCase):
    """How the PCA draws what it fitted: order, colours, antivirals, dose (FREYA-3200)."""

    def setUp(self) -> None:
        """Build the PCA of the well-by-well fixture."""
        self.pca = _build(_pca_table())["pca"]
        self.traces = _traces(self.pca)

    def test_the_traces_run_bottom_to_top_with_the_antivirals_last(self) -> None:
        """Plotly draws later traces on top, so no control hides under Treated."""
        self.assertEqual(
            [trace["name"] for trace in self.pca["data"]],
            [
                "Treated",
                "Positive control",
                "Infected control (DMSO)",
                "Uninfected control (DMSO)",
                "Remdesivir",
                "Nirmatrelvir",
                "GC376",
            ],
        )

    def test_each_population_has_its_fixed_colour(self) -> None:
        """The portal's red and blue for the two DMSO controls, greys for the rest."""
        self.assertEqual(
            {name: trace["marker"]["color"] for name, trace in self.traces.items()},
            {
                "Treated": "#d8d8d8",
                "Positive control": "#55585a",
                "Infected control (DMSO)": "#a0302c",
                "Uninfected control (DMSO)": "#4770b1",
                "Remdesivir": "#f3b153",
                "Nirmatrelvir": "#f3b153",
                "GC376": "#f3b153",
            },
        )

    def test_the_antivirals_are_outlined(self) -> None:
        """The yellow is under 3:1 against white, so each antiviral marker is outlined."""
        for name in ANTIVIRAL_WELLS:
            self.assertEqual(self.traces[name]["marker"]["line"]["color"], "#1a1c1a", name)
        for name in ("Treated", *CONTROL_TRACES):
            self.assertNotIn("line", self.traces[name]["marker"], name)

    def test_each_antiviral_trace_holds_exactly_its_own_wells(self) -> None:
        """Each id's wells, at every dose, and none of them left in Treated."""
        for name, wells in ANTIVIRAL_WELLS.items():
            for got, want in zip(_pc1(self.traces[name]), _expected_pc1(wells), strict=True):
                self.assertAlmostEqual(got, want, places=9, msg=name)
        for got, want in zip(
            _pc1(self.traces["Treated"]), _expected_pc1(TREATED_WELLS), strict=True
        ):
            self.assertAlmostEqual(got, want, places=9)

    def test_a_marker_grows_strictly_with_its_dose(self) -> None:
        """Across Treated and the antivirals, a higher dose is always a larger marker."""
        index_of = {round(_expected_pc1([index])[0], 6): index for index in range(len(PCA_WELLS))}
        size_by_dose: dict[float, set[float]] = {}
        for name in ("Treated", *ANTIVIRAL_WELLS):
            trace = self.traces[name]
            scores = _decode_array(trace["x"]).tolist()
            sizes = _decode_array(trace["marker"]["size"]).tolist()
            for score, size in zip(scores, sizes, strict=True):
                dose = PCA_WELLS[index_of[round(score, 6)]][2]
                size_by_dose.setdefault(dose, set()).add(size)

        self.assertTrue(all(len(sizes) == 1 for sizes in size_by_dose.values()), size_by_dose)
        sizes_in_dose_order = [size_by_dose[dose].pop() for dose in sorted(size_by_dose)]
        self.assertEqual(len(sizes_in_dose_order), 6)
        self.assertTrue(
            all(lower < higher for lower, higher in pairwise(sizes_in_dose_order)),
            sizes_in_dose_order,
        )

    def test_the_controls_keep_one_size(self) -> None:
        """Only treated and antiviral wells are sized by dose; every control shares one size."""
        sizes = {self.traces[name]["marker"]["size"] for name in CONTROL_TRACES}

        self.assertEqual(sizes, {PCA_CONTROL_MARKER_SIZE})

    def test_the_subtitle_says_larger_is_higher_and_gives_the_drawn_dose_range(self) -> None:
        """The range is the drawn dosed wells': not the near-empty 100, not the control's 0.01."""
        subtitle = self.pca["layout"]["title"]["subtitle"]["text"]

        self.assertEqual(subtitle, "Marker size shows dose: larger is higher, from 0.1 to 30 µM")

    def test_the_legend_keeps_its_title(self) -> None:
        """The legend still names what its entries are."""
        self.assertEqual(self.pca["layout"]["legend"]["title"]["text"], "Well population")


class DrrTwoDimensionalArraySerialisationTests(SimpleTestCase):
    """Plotly's base64 ``bdata``/``shape`` form for a 2-D array.

    Every figure this package builds is a 1-D trace now that the heatmap is gone,
    so nothing else exercises Plotly serialising a 2-D array: it comes back with
    a ``shape`` key alongside ``bdata``, where a 1-D array carries ``bdata``
    alone. This pins the decoder's 2-D path directly, independent of any figure.
    """

    def test_a_two_dimensional_array_keeps_its_shape_key(self) -> None:
        """A small 2-D array still round-trips through ``bdata`` and ``shape``."""
        matrix = np.arange(12, dtype=np.float64).reshape(3, 4)
        figure = go.Figure(go.Heatmap(z=matrix))

        payload = figure_to_json(figure)["data"][0]["z"]

        self.assertIsInstance(payload, dict)
        self.assertIn("bdata", payload)
        self.assertIn("shape", payload)
        self.assertEqual(_decode_array(payload).tolist(), matrix.tolist())
