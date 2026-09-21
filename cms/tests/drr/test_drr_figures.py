"""Tests for the channel map, the figure feature basis and its clip (FREYA-2923, 2968).

Every fixture here carries a column in **each of the five** imaging channels. That
is deliberate: the A549-ACE2 and Vero E6 screens name opposite stains with the same
two tokens, so a fixture that omits a channel cannot tell an inverted map from a
correct one — which is how the inverted reading survived three sessions of work on
these figures (``plans/DRR/reference/data-sources.md`` DS-8).
"""

from __future__ import annotations

import base64
from unittest.mock import patch

import numpy as np
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
    build_all_figures,
    clip_figure_values,
    clip_report,
    figure_basis_token,
)
from dashboard_visualisation.drr.loader import FeatureTable

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
# own measured maximum and minimum (DS-3), and a value sitting exactly on the
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
    handled rather than assumed (spec section 10).
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
    fails the run rather than widening to every profile (FREYA-2636).
    """
    row_values = {**TRT_VALUES, **(values or {})}
    frame = pl.DataFrame(
        {
            "pert_type": ["trt", "trt", "negcon", "non-inf"],
            "cbkid": ["CBK1", "CBK1", "CBK2", "CBK2"],
            **{
                column: [value, value, value / 2, value / 2] for column, value in row_values.items()
            },
        }
    )
    return FeatureTable(
        frame=frame,
        metadata_columns=["pert_type", "cbkid"],
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
        """Four morphology channels in, the infection readout out (spec section 5)."""
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
        """The four feature-derived figures are built; umap needs its own coordinates."""
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
        plotted condition (DS-8 item 4). Here that is the halved control row.
        """
        axes = self._radar_axes("radar_infected")

        self.assertAlmostEqual(axes["DNA I"], 0.5, places=6)
        self.assertAlmostEqual(axes["ER G"], 3.5, places=6)


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
        """50 in MAD units, which is where the paper's pipeline clips (DS-3)."""
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

    def test_no_out_of_range_value_reaches_a_radar_or_the_heatmap(self) -> None:
        """Every plotted mean is a mean of clipped values, so none can exceed the bound."""
        figures = self._figures()

        for figure_id in ("radar_compound", "radar_infected"):
            for radius in figures[figure_id]["data"][0]["r"]:
                if radius is None:
                    continue
                self.assertLessEqual(abs(float(radius)), FIGURE_CLIP_BOUND, figure_id)
        cells = _decode_array(figures["heatmap"]["data"][0]["z"])
        self.assertLessEqual(float(np.abs(cells).max()), FIGURE_CLIP_BOUND)

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
        self.assertEqual(figure_basis_token(self.columns), "figure-basis:7:50.0")

    def test_the_basis_token_moves_with_the_bound_and_with_the_basis(self) -> None:
        """Either half of "how the figures were computed" busts the render cache."""
        with patch("dashboard_visualisation.drr.figures.FIGURE_CLIP_BOUND", 25.0):
            self.assertEqual(figure_basis_token(self.columns), "figure-basis:7:25.0")

        self.assertNotEqual(
            figure_basis_token(self.columns),
            figure_basis_token(self.columns[:-1]),
        )
