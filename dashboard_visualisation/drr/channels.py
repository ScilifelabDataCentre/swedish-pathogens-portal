"""Per-screen channel-to-stain vocabulary for a DRR dataset (spec sections 5 and 7).

The feature columns carry the authors' internal acquisition-slot names rather than
stain names, and **the same token means a different stain on a different screen**:
on the A549-ACE2 validation screen this page renders, ``illumCONC`` is the
SARS-CoV-2 nucleocapsid antibody and ``illumMITO`` is Concanavalin A / ER, while the
Vero E6 primary screen uses those two the other way round. Measured 2026-09-03
against the authors' own renamed feature files, whole file and column by column
(FREYA-2923; ``plans/DRR/reference/data-sources.md`` DS-8).

Two facts therefore belong to the dataset and not to the project: which stain the
page names for each column token, and which channel the figures leave out. Both are
declared here per dataset slug, so a second screen has to state its own map instead
of inheriting one that describes someone else's assay.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Channel:
    """One imaging channel of a Cell Painting screen.

    Attributes:
        column_tag: The token this screen's feature columns carry, e.g.
            ``illumCONC``. The DRR documentation calls it the column token.
        label: The channel name the authors use today, after their own rename.
        stain: The dye or antibody imaged in that channel.
        measures: What it reports, in the paper's own vocabulary.
        in_figures: Whether its columns belong in the morphology feature basis.
            ``False`` for an infection readout: a figure computed on it would
            carry the assay's own answer as morphology (spec section 5).
    """

    column_tag: str
    label: str
    stain: str
    measures: str
    in_figures: bool


# The A549-ACE2 validation screen, in the display order FREYA-2923 states: the four
# morphology channels, then the antibody, which is the one the figures exclude.
A549_ACE2_VALIDATION_CHANNELS: tuple[Channel, ...] = (
    Channel(
        column_tag="illumHOECHST",
        label="HOECHST",
        stain="Hoechst 33342",
        measures="nuclei (DNA)",
        in_figures=True,
    ),
    Channel(
        column_tag="illumSYTO",
        label="SYTO",
        stain="SYTO 13/14",
        measures="nucleoli / cytoplasmic RNA",
        in_figures=True,
    ),
    Channel(
        column_tag="illumPHAandWGA",
        label="PHAandWGA",
        stain="Phalloidin + WGA",
        measures="actin, Golgi, membrane (AGP)",
        in_figures=True,
    ),
    Channel(
        column_tag="illumMITO",
        label="CONC",
        stain="Concanavalin A",
        measures="endoplasmic reticulum (ER)",
        in_figures=True,
    ),
    Channel(
        column_tag="illumCONC",
        label="SARS-CoV-2-N-Ab",
        stain="SARS-CoV-2 nucleocapsid antibody",
        measures="infection marker",
        in_figures=False,
    ),
)

# One entry per screen, keyed by dataset slug. A slug that is not here has no map,
# which stops a precompute run rather than labelling a page from another screen.
CHANNEL_MAPS: dict[str, tuple[Channel, ...]] = {
    "sars-cov2-a549-ace2-validation": A549_ACE2_VALIDATION_CHANNELS,
}


def channel_map(dataset_slug: str) -> tuple[Channel, ...]:
    """Return the channel-to-stain map for one dataset.

    Args:
        dataset_slug: The dataset slug, matching both the page slug and
            ``DrrDatasetData.dataset_slug``.

    Returns:
        That screen's channels, in display order.

    Raises:
        ValueError: If no map is registered for the slug. Two screens name
            opposite stains with the same two tokens, so defaulting to one of
            them would both mislabel the page and move the figure basis
            silently; a new screen declares its own map instead.
    """
    try:
        return CHANNEL_MAPS[dataset_slug]
    except KeyError as error:
        raise ValueError(
            f"No channel-to-stain map is registered for dataset slug '{dataset_slug}'. "
            "The map is per screen — illumCONC and illumMITO name opposite stains on the "
            "A549-ACE2 and Vero E6 screens — so add this screen's map to CHANNEL_MAPS "
            f"rather than reusing another's. Registered: {sorted(CHANNEL_MAPS)}."
        ) from error


def figure_feature_columns(feature_columns: list[str], channels: tuple[Channel, ...]) -> list[str]:
    """Return the feature columns the figures may compute on.

    Every column naming a channel that is out of the figure basis is dropped,
    including a ``Correlation`` column naming it as one half of a pair — which is
    how this screen's excluded 323 of 1,467 columns were counted (DS-8).

    Args:
        feature_columns: The table's numeric feature columns.
        channels: This screen's channel map.

    Returns:
        The subset of ``feature_columns`` that carries morphology only.

    Raises:
        ValueError: If the exclusion empties a non-empty feature set. That means
            the map does not describe this table, and a figure computed on
            nothing is worse than no figure at all.
    """
    excluded = tuple(channel.column_tag for channel in channels if not channel.in_figures)
    columns = [
        column for column in feature_columns if not any(token in column for token in excluded)
    ]
    if feature_columns and not columns:
        raise ValueError(
            f"Excluding channel(s) {list(excluded)} removes every one of the "
            f"{len(feature_columns)} feature columns, so this channel map does not describe "
            "the feature table it was given."
        )
    return columns


def present_channels(
    feature_columns: list[str], channels: tuple[Channel, ...]
) -> list[dict[str, Any]]:
    """Describe the channels present in the feature columns, in display order.

    Args:
        feature_columns: The table's numeric feature columns.
        channels: This screen's channel map.

    Returns:
        One JSON-serialisable entry per present channel, naming the stain rather
        than the column token. ``in_figures`` marks the excluded channel so the
        page can say which one the figures leave out (spec section 7).
    """
    return [
        {
            "column_tag": channel.column_tag,
            "label": channel.label,
            "stain": channel.stain,
            "measures": channel.measures,
            "in_figures": channel.in_figures,
        }
        for channel in channels
        if any(channel.column_tag in column for column in feature_columns)
    ]
