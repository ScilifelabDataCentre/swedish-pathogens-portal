"""Tests for the per-screen channel map and the figure feature basis (FREYA-2923).

Every fixture here carries a column in **each of the five** imaging channels. That
is deliberate: the A549-ACE2 and Vero E6 screens name opposite stains with the same
two tokens, so a fixture that omits a channel cannot tell an inverted map from a
correct one — which is how the inverted reading survived three sessions of work on
these figures (``plans/DRR/reference/data-sources.md`` DS-8).
"""

from __future__ import annotations

import polars as pl
from django.test import SimpleTestCase

from dashboard_visualisation.drr.channels import (
    channel_map,
    figure_feature_columns,
    present_channels,
)
from dashboard_visualisation.drr.figures import (
    FEATURE_BASIS_FIGURE_IDS,
    FEATURE_CATEGORIES,
    build_all_figures,
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


def _feature_table() -> FeatureTable:
    """Return a four-profile table: two ``trt`` rows, then two halved controls."""
    frame = pl.DataFrame(
        {
            "pert_type": ["trt", "trt", "ctrl", "ctrl"],
            "cbkid": ["CBK1", "CBK1", "CBK2", "CBK2"],
            **{
                column: [value, value, value / 2, value / 2] for column, value in TRT_VALUES.items()
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
        self.figures = build_all_figures(table, feature_columns=columns)

    def _radar_axes(self, figure_id: str) -> dict[str, float]:
        """Return one radar's per-category values, keyed by category."""
        radii = self.figures[figure_id]["data"][0]["r"]
        return dict(zip(FEATURE_CATEGORIES, radii, strict=False))

    def test_every_feature_basis_figure_is_built(self) -> None:
        """The four feature-derived figures are built; umap needs its own coordinates."""
        self.assertEqual(set(self.figures), set(FEATURE_BASIS_FIGURE_IDS))

    def test_the_radar_averages_the_figure_basis_only(self) -> None:
        """Intensity is the mean of the three kept channels; the antibody's 100.0 is gone."""
        axes = self._radar_axes("radar_compound")

        self.assertAlmostEqual(axes["Intensity"], 2.0, places=6)
        self.assertAlmostEqual(axes["AreaShape"], 5.0, places=6)
        self.assertAlmostEqual(axes["Granularity"], 7.0, places=6)
        self.assertAlmostEqual(axes["RadialDistribution"], 11.0, places=6)
        self.assertAlmostEqual(axes["Neighbors"], 9.0, places=6)

    def test_a_category_left_with_no_column_reports_nothing_not_the_antibody(self) -> None:
        """Correlation holds only an antibody pair here, so its axis is empty, not 50.0."""
        self.assertAlmostEqual(self._radar_axes("radar_compound")["Correlation"], 0.0, places=6)

    def test_the_control_radar_uses_the_same_basis(self) -> None:
        """The infected-reference radar averages the halved control rows, antibody-free."""
        axes = self._radar_axes("radar_infected")

        self.assertAlmostEqual(axes["Intensity"], 1.0, places=6)
        self.assertAlmostEqual(axes["Granularity"], 3.5, places=6)
