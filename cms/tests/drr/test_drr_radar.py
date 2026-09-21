"""Tests for Figure 3C's radar ring and statistic (FREYA-2636, spec section 6).

The fixture column set here is the real table's shape rather than a handful of
columns: every module the export carries, both families the notebook drops, and
one column per channel in each per-stain module. That is what lets these tests
say the ring is *exactly* 24 axes — the assertion the ticket's readiness
addendum asks for, and the one a six-column fixture cannot make.
"""

from __future__ import annotations

import numpy as np
from django.test import SimpleTestCase

from dashboard_visualisation.drr.channels import channel_map, figure_feature_columns
from dashboard_visualisation.drr.radar import (
    artefact_key,
    axis_values,
    build_ring,
    require_populations,
    unplotted_columns,
)

SLUG = "sars-cov2-a549-ace2-validation"

MORPHOLOGY_CHANNELS = ("illumHOECHST", "illumSYTO", "illumPHAandWGA", "illumMITO")
ALL_CHANNELS = (*MORPHOLOGY_CHANNELS, "illumCONC")

# The families the published ring plots.
RING_COLUMNS = [
    "Children_nuclei_Count_cells",
    *(f"AreaShape_Area_{compartment}" for compartment in ("cells", "cytoplasm", "nuclei")),
    *(
        f"{module}_Stat_{channel}_{compartment}"
        for module in ("Intensity", "Granularity", "RadialDistribution")
        for channel in ALL_CHANNELS
        for compartment in ("nuclei", "cells")
    ),
    *(f"Neighbors_PercentTouching_Adjacent_{compartment}" for compartment in ("cells", "nuclei")),
    *(
        f"Correlation_Correlation_{first}_{second}_nuclei"
        for index, first in enumerate(ALL_CHANNELS)
        for second in ALL_CHANNELS[index + 1 :]
    ),
]

# The families it does not: the notebook has no branch for them, so they fall to
# its "Uncategorized" bucket (DS-8 item 1). ``Count_nuclei`` never even reaches
# the feature set — ``loader.METADATA_COLUMNS`` holds it as QC metadata.
UNPLOTTED_COLUMNS = [
    "Location_CenterMassIntensity_X_illumHOECHST_nuclei",
    "Location_Center_Y_cells",
    "Parent_cells_nuclei",
    "Parent_nuclei_cytoplasm",
]

FEATURE_COLUMNS = [*RING_COLUMNS, *UNPLOTTED_COLUMNS]


def _ring(columns: list[str] | None = None) -> list:
    """Build the ring over the figure basis of the fixture columns."""
    channels = channel_map(SLUG)
    basis = figure_feature_columns(columns or FEATURE_COLUMNS, channels)
    return build_ring(basis, channels)


class DrrRadarRingTests(SimpleTestCase):
    """The ring's shape, which is the author's own code's and not an estimate."""

    def test_the_ring_is_exactly_twenty_four_axes(self) -> None:
        """1 Children + 3 area/shape + 4 stains x 3 modules + 2 neighbours + 6 pairs."""
        self.assertEqual(len(_ring()), 24)

    def test_the_ring_is_ordered_and_names_every_axis(self) -> None:
        """Children leads, as ``desired_order`` places it, and the pairs close the ring."""
        labels = [axis.label for axis in _ring()]

        self.assertEqual(
            labels,
            [
                "Children N",
                "Area/shape C",
                "Area/shape CY",
                "Area/shape N",
                "DNA I",
                "DNA G",
                "DNA RD",
                "RNA I",
                "RNA G",
                "RNA RD",
                "AGP I",
                "AGP G",
                "AGP RD",
                "ER I",
                "ER G",
                "ER RD",
                "Neighbors C",
                "Neighbors N",
                "DNA-RNA",
                "DNA-AGP",
                "DNA-ER",
                "RNA-AGP",
                "RNA-ER",
                "AGP-ER",
            ],
        )

    def test_the_children_axis_carries_the_table_s_one_children_column(self) -> None:
        """One column, one spoke — which is why the arc looked like a rounding error."""
        children = _ring()[0]

        self.assertEqual(children.columns, ("Children_nuclei_Count_cells",))

    def test_every_axis_has_a_column_on_this_screen(self) -> None:
        """A gap here would mean the ring describes a table nobody has."""
        empty = [axis.label for axis in _ring() if not axis.columns]

        self.assertEqual(empty, [])

    def test_location_parent_and_count_nuclei_are_absent(self) -> None:
        """The dropped families reach no axis, asserted by name (DS-8 item 1)."""
        plotted = {column for axis in _ring() for column in axis.columns}

        for column in UNPLOTTED_COLUMNS:
            self.assertNotIn(column, plotted)
        self.assertNotIn("Count_nuclei", plotted)

    def test_what_the_ring_leaves_out_is_reported_rather_than_dropped_silently(self) -> None:
        """A grown export shows up as a number, not as a quietly thinner figure."""
        channels = channel_map(SLUG)
        basis = figure_feature_columns(FEATURE_COLUMNS, channels)

        self.assertEqual(sorted(unplotted_columns(basis, _ring())), sorted(UNPLOTTED_COLUMNS))


class DrrRadarBasisTests(SimpleTestCase):
    """The ring is grouped against the figure basis, not the download set."""

    def test_the_antibody_channel_reaches_no_axis(self) -> None:
        """Its own module columns and its five correlation pairs are all gone."""
        plotted = {column for axis in _ring() for column in axis.columns}

        self.assertEqual([column for column in plotted if "illumCONC" in column], [])

    def test_the_grouping_is_the_figure_basis_and_not_the_download_set(self) -> None:
        """The same ring over the two inputs does not describe them the same way.

        Over the figure basis every column it is given lands on an axis but the
        two dropped families. Over the download set the antibody's columns land
        on none either — the ring rings four stain groups, and the fifth channel
        is not one of them — so the difference between the two bases is visible
        here rather than only in the column count (spec section 10).
        """
        channels = channel_map(SLUG)
        basis = figure_feature_columns(FEATURE_COLUMNS, channels)
        antibody = [column for column in FEATURE_COLUMNS if "illumCONC" in column]

        self.assertNotEqual(antibody, [])
        self.assertEqual([column for column in basis if "illumCONC" in column], [])
        self.assertEqual(sorted(unplotted_columns(basis, _ring())), sorted(UNPLOTTED_COLUMNS))
        self.assertEqual(
            sorted(unplotted_columns(FEATURE_COLUMNS, build_ring(FEATURE_COLUMNS, channels))),
            sorted([*antibody, *UNPLOTTED_COLUMNS]),
        )


class DrrRadarStatisticTests(SimpleTestCase):
    """The published statistic: mean within the condition, absolute, then grouped."""

    def setUp(self) -> None:
        """Build a ring over three columns: two on one axis, one on another."""
        self.axes = _ring(
            [
                "Intensity_Stat_illumHOECHST_nuclei",
                "Intensity_Stat_illumHOECHST_cells",
                "Intensity_Stat_illumSYTO_nuclei",
            ]
        )
        self.matrix = np.array(
            [
                [2.0, -4.0, 1.0],
                [4.0, -8.0, 3.0],
                [0.0, 0.0, 0.0],
                [10.0, 10.0, 10.0],
            ]
        )
        self.condition = np.array([True, True, False, False])

    def _values(self) -> dict[str, float | None]:
        """Return the condition's radar values, keyed by axis label."""
        return dict(
            zip(
                [axis.label for axis in self.axes],
                axis_values(self.matrix, self.axes, self.condition),
                strict=True,
            )
        )

    def test_the_absolute_value_is_taken_per_feature_then_averaged(self) -> None:
        """|mean(2, 4)| = 3 and |mean(-4, -8)| = 6 average to 4.5 on the DNA axis.

        Averaging first and taking the absolute value of the group — the other
        order — would give |(3 + -6) / 2| = 1.5, so this pins the sequence and
        not merely the arithmetic.
        """
        self.assertAlmostEqual(self._values()["DNA I"], 4.5, places=6)

    def test_no_control_mean_is_subtracted(self) -> None:
        """The other rows are not the reference: MAD normalisation already did that.

        Subtracting the last row's 10.0 would put this axis at 8.0, not 2.0.
        """
        self.assertAlmostEqual(self._values()["RNA I"], 2.0, places=6)

    def test_an_axis_without_a_column_is_none_rather_than_zero(self) -> None:
        """A gap says "no column here"; 0.0 would claim a measured absence of signal."""
        self.assertIsNone(self._values()["ER G"])

    def test_an_empty_condition_raises_instead_of_widening(self) -> None:
        """A radar of every profile is not the figure that was asked for."""
        with self.assertRaisesMessage(ValueError, "no profile"):
            axis_values(self.matrix, self.axes, np.zeros(4, dtype=bool))


class DrrRadarPopulationTests(SimpleTestCase):
    """Which populations a run needs before it may publish either radar."""

    def test_a_complete_table_passes(self) -> None:
        """All three labels present, so both contrasts can be computed."""
        require_populations(["trt", "negcon", "non-inf", "poscon"])

    def test_each_missing_population_is_named(self) -> None:
        """The message says which one is absent, since the fix differs for each."""
        for missing, present in (
            ("negcon", ["trt", "non-inf"]),
            ("non-inf", ["trt", "negcon"]),
            ("trt", ["negcon", "non-inf"]),
        ):
            with self.subTest(missing=missing), self.assertRaisesMessage(ValueError, missing):
                require_populations(present)


class DrrRadarArtefactKeyTests(SimpleTestCase):
    """The on-disk key precompute derives, which a request never supplies."""

    def test_a_plain_compound_id_is_its_own_key(self) -> None:
        """The common case stays readable on disk."""
        self.assertEqual(artefact_key("CBK008271G"), "CBK008271G")

    def test_a_bracketed_control_id_is_made_filename_safe(self) -> None:
        """``[stau]`` cannot be a filename, and its key carries no bracket."""
        key = artefact_key("[stau]")

        self.assertTrue(key.startswith("stau_"))
        self.assertNotIn("[", key)
        self.assertNotIn("]", key)

    def test_two_ids_that_sanitise_alike_keep_different_keys(self) -> None:
        """Otherwise one compound would serve another's figure off the same file."""
        self.assertNotEqual(artefact_key("[stau]"), artefact_key("stau"))

    def test_a_traversal_attempt_cannot_survive_sanitisation(self) -> None:
        """Keys are derived, not requested — this is the belt to that braces."""
        key = artefact_key("../../etc/passwd")

        self.assertNotIn("/", key)
        self.assertNotIn("..", key)

    def test_the_key_is_stable_across_runs(self) -> None:
        """Precompute writes it and the compound index records it; they must agree."""
        self.assertEqual(artefact_key("[stau]"), artefact_key("[stau]"))
