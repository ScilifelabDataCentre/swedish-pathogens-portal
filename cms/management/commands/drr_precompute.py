"""Management command: precompute DRR dataset artefacts (FREYA-2556).

Manual, repeatable, offline pipeline (spec section 5). Turns a Cell Painting
feature CSV plus its CBCS metadata TSV — and optionally a compound-name lookup
(FREYA-2628) — into the derived artefacts a ``DrrDatasetPage`` serves, and
upserts the slug-keyed ``DrrDatasetData`` row. Raw imagery is never touched;
only derived artefacts land under ``media/drr/<slug>/``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl
import structlog
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from cms.snippets.drr_dataset_data import DrrDatasetData
from dashboard_visualisation.drr import (
    SNIPPET_FIGURE_BYTE_CEILING,
    artefact_dir,
    artefact_key,
    build_compound_index,
    build_figure_bundle,
    build_summary,
    channel_map,
    compound_label,
    figure_basis_token,
    figure_feature_columns,
    load_compound_names,
    load_feature_table,
    load_metadata,
    name_lookup_report,
    oversized_figures,
    reconciliation_report,
    require_populations,
)
from dashboard_visualisation.utils.uploads import calculate_file_hash

LOGGER = structlog.get_logger(__name__)


class Command(BaseCommand):
    """Precompute derived artefacts for one DRR dataset and upsert its data row."""

    help = "Precompute DRR dataset artefacts (features, compounds, figures, summary)."

    def add_arguments(self, parser: CommandParser) -> None:
        """Register command-line arguments."""
        parser.add_argument("--slug", required=True, help="Dataset slug; matches the page slug.")
        parser.add_argument(
            "--input", required=True, help="Path to the feature table CSV (semicolon-delimited)."
        )
        parser.add_argument(
            "--metadata", required=True, help="Path to the CBCS compound metadata TSV."
        )
        parser.add_argument(
            "--compound-names",
            dest="compound_names",
            default=None,
            help="Optional Arrow file read as a cbkid -> pert_iname lookup; skipped if omitted.",
        )
        parser.add_argument("--title", default="", help="Human-readable dataset title.")
        parser.add_argument(
            "--umap-coords",
            dest="umap_coords",
            default=None,
            help="Optional precomputed UMAP coordinates (parquet/CSV); skipped if omitted.",
        )
        parser.add_argument(
            "--data-updated-at",
            dest="data_updated_at",
            default=None,
            help="Optional ISO date shown as the public data-updated date.",
        )

    def handle(self, *args: object, **options: object) -> None:
        """Run the precompute pipeline for the requested slug."""
        slug = options["slug"]
        input_path = Path(options["input"])
        metadata_path = Path(options["metadata"])
        names_path = Path(options["compound_names"]) if options["compound_names"] else None
        title = options["title"] or slug

        LOGGER.info("drr.precompute.start", slug=slug, input=str(input_path))

        # Read and validate every input before touching the artefact directory:
        # the page advertises downloads from the files on disk, so a run that
        # fails afterwards would leave them describing a different generation.
        table = load_feature_table(input_path)
        metadata = load_metadata(metadata_path)
        names = load_compound_names(names_path) if names_path else None
        # The channel-to-stain map belongs to the screen, and it decides both the
        # stain names the page publishes and which channel the figures exclude.
        # An unregistered slug therefore stops the run here — inputs read, and
        # nothing written — rather than labelling this page from another screen's
        # vocabulary (FREYA-2923).
        try:
            channels = channel_map(slug)
        except ValueError as error:
            raise CommandError(str(error)) from error
        figure_columns = figure_feature_columns(table.feature_columns, channels)
        # Both radars are contrasts, so a table missing one of the populations
        # they contrast cannot produce them. Checked here, before anything is
        # written, rather than by widening the condition to every profile and
        # publishing a different figure under the published one's name
        # (FREYA-2636 criterion 6).
        try:
            require_populations(table.frame["pert_type"].to_list())
        except (ValueError, pl.exceptions.ColumnNotFoundError) as error:
            raise CommandError(str(error)) from error

        compound_index = build_compound_index(table, metadata, names)
        reconciliation = reconciliation_report(compound_index)

        # Everything is computed before the first write: a figure that cannot be
        # built must leave the generation already on disk intact, rather than
        # replacing half of it (spec section 10).
        bundle = build_figure_bundle(
            table,
            feature_columns=figure_columns,
            channels=channels,
            compound_labels=self._compound_labels(compound_index),
            umap_coords=options["umap_coords"],
        )
        figures = bundle.figures
        oversized = oversized_figures(figures)
        if oversized:
            raise CommandError(
                "These figures are too large for the snippet, which is read whole to render "
                f"any one of them: {oversized} bytes against a ceiling of "
                f"{SNIPPET_FIGURE_BYTE_CEILING}. A figure this size belongs on disk as a set "
                "(spec section 4), not in DrrDatasetData.data."
            )
        radar_keys = {cbkid: artefact_key(cbkid) for cbkid in bundle.radars}
        compound_index = self._with_radar_keys(compound_index, radar_keys)

        output_dir = artefact_dir(slug)
        figures_dir = output_dir / "figures"
        figures_dir.mkdir(parents=True, exist_ok=True)

        compound_index.write_parquet(output_dir / "compounds.parquet")

        table.frame.write_csv(output_dir / "features.csv")
        table.frame.write_parquet(output_dir / "features.parquet")

        self._write_figures(figures_dir, figures)
        self._write_radar_set(figures_dir / "radar", bundle.radars, radar_keys)

        feature_hash = self._hash_file(input_path)
        names_hash = self._hash_file(names_path) if names_path else None
        # Fixed order — feature table, metadata, name lookup, UMAP coordinates —
        # so the digest depends on the inputs and not on the order the optional
        # ones were passed in. Two digests come out of it, and they answer
        # different questions: the inputs-only one says whether the *data* moved,
        # and the one with the figure-basis token appended says whether anything
        # a rendered figure depends on moved.
        input_hashes = [feature_hash, self._hash_file(metadata_path)]
        if names_hash:
            input_hashes.append(names_hash)
        if options["umap_coords"]:
            input_hashes.append(self._hash_file(Path(options["umap_coords"])))
        inputs_hash = self._combine_hashes(input_hashes)
        source_hash = self._combine_hashes([*input_hashes, figure_basis_token(figure_columns)])
        generated_at = timezone.now()
        summary = build_summary(
            table,
            channels=channels,
            figure_feature_columns=figure_columns,
            source_filename=input_path.name,
            source_hash=feature_hash,
            inputs_hash=inputs_hash,
            generated_at=generated_at.isoformat(),
        )
        summary["compound_reconciliation"] = reconciliation
        summary["name_lookup"] = name_lookup_report(
            compound_index,
            names,
            source_filename=names_path.name if names_path else None,
            source_hash=names_hash,
        )
        (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

        data_updated_at = self._resolve_updated_date(slug, inputs_hash, options["data_updated_at"])
        self._upsert_data_row(
            slug=slug,
            title=title,
            figures=figures,
            summary=summary,
            source_hash=source_hash,
            generated_at=generated_at,
            data_updated_at=data_updated_at,
        )

        LOGGER.info(
            "drr.precompute.done",
            slug=slug,
            figures=sorted(figures),
            compounds=compound_index.height,
            profiles=summary["n_profiles"],
            download_features=summary["n_features"],
            figure_features=len(figure_columns),
            radar_axes=len(bundle.axes),
            radar_files=len(bundle.radars),
            radar_unplotted_columns=len(bundle.unplotted_columns),
            figure_values_clipped=summary["feature_sets"]["figures"]["clip"]["n_values_clipped"],
            matched=reconciliation["n_annotated"],
            unmatched=reconciliation["n_unannotated"],
            controls=reconciliation["n_control_ids"],
        )
        figure_basis = summary["feature_sets"]["figures"]
        excluded_channels = ", ".join(figure_basis["excluded_channels"])
        clip = figure_basis["clip"]
        report = (
            f"Precomputed DRR dataset '{slug}': {summary['n_compounds']} compounds, "
            f"{summary['n_profiles']} profiles, {len(figures)} figures -> {output_dir}\n"
            f"  cbkid join: {reconciliation['n_annotated']} annotated "
            f"({reconciliation['n_recovered']} via normalization), "
            f"{reconciliation['n_unannotated']} unannotated, "
            f"{reconciliation['n_control_ids']} controls\n"
            f"  features: {summary['n_features']} for download, {len(figure_columns)} for the "
            f"figures (excluding {excluded_channels})\n"
            f"  figure clip: {clip['n_values_clipped']} of {clip['n_values']} values in "
            f"{clip['n_columns_clipped']} column(s) brought to "
            f"{clip['lower']:g}..{clip['upper']:g}; the downloads keep every value\n"
            f"  radar: {len(bundle.axes)} axes, {len(bundle.radars)} per-compound file(s) under "
            f"figures/radar/, {len(bundle.unplotted_columns)} figure-basis column(s) on no axis"
        )
        if names_path:
            name_lookup = summary["name_lookup"]
            report += (
                f"\n  name lookup: {name_lookup['n_named']} named, "
                f"{name_lookup['n_unnamed']} unnamed, "
                f"{name_lookup['n_lookup_ids']} lookup ids, "
                f"{name_lookup['n_conflicting_ids']} conflicting"
            )
        self.stdout.write(self.style.SUCCESS(report))

    @staticmethod
    def _compound_labels(compound_index: pl.DataFrame) -> dict[str, str]:
        """Map each compound id to the name a reader sees, for the radar titles."""
        columns = [
            column for column in ("cbkid", "name", "kind") if column in compound_index.columns
        ]
        return {
            row["cbkid"]: compound_label(row["cbkid"], name=row.get("name"), kind=row.get("kind"))
            for row in compound_index.select(columns).to_dicts()
        }

    @staticmethod
    def _with_radar_keys(compound_index: pl.DataFrame, radar_keys: dict[str, str]) -> pl.DataFrame:
        """Record each compound's radar artefact key on the index.

        The key is derived here, from the compound id, and never from a request
        value: the section 8.3 route resolves a reader's ``cbkid`` by looking it
        up in this column. A compound with no treated well has no radar and
        carries a null, which is also what keeps the figure picker from offering
        an option that would 404 (FREYA-2636 criterion 5).
        """
        return compound_index.with_columns(
            pl.col("cbkid")
            .replace_strict(radar_keys, default=None, return_dtype=pl.String)
            .alias("radar_key")
        )

    @staticmethod
    def _write_figures(figures_dir: Path, figures: dict[str, Any]) -> None:
        """Write each figure JSON to disk, clearing any stale figures first."""
        for stale in figures_dir.glob("*.json"):
            stale.unlink()
        for figure_id, payload in figures.items():
            (figures_dir / f"{figure_id}.json").write_text(json.dumps(payload), encoding="utf-8")

    @staticmethod
    def _write_radar_set(
        radar_dir: Path,
        radars: dict[str, Any],
        radar_keys: dict[str, str],
    ) -> None:
        """Write one radar per compound, keyed by its sanitised artefact key.

        The set stays on disk and out of ``DrrDatasetData.data``: the snippet is
        a single ``JSONField`` deserialised whole to render one figure, and a
        ``RevisionMixin`` that would snapshot every re-run (spec section 4).
        """
        radar_dir.mkdir(parents=True, exist_ok=True)
        for stale in radar_dir.glob("*.json"):
            stale.unlink()
        for cbkid, payload in radars.items():
            (radar_dir / f"{radar_keys[cbkid]}.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )

    @staticmethod
    def _hash_file(path: Path) -> str:
        """Return the SHA-256 of a file (calculate_file_hash needs a handle)."""
        with path.open("rb") as handle:
            return calculate_file_hash(handle)

    @staticmethod
    def _combine_hashes(tokens: list[str]) -> str:
        """Combine per-input digests and the figure-basis token into one hash.

        Folding every precompute input (feature table, metadata, and any UMAP
        coordinates) into ``source_file_hash`` ensures the ``PlotlyFigureBlock``
        render cache (keyed by slug + figure_id + source_file_hash) is busted
        whenever any input that affects the figures changes. The last token
        describes the figure basis instead of an input: a change to *how* the
        figures are computed moves no input digest, and the cache holds for 24
        hours, so without it the page would serve the previous render for a day
        (FREYA-2968).
        """
        hasher = hashlib.sha256()
        for token in tokens:
            hasher.update(token.encode("ascii"))
            hasher.update(b"\0")
        return hasher.hexdigest()

    @staticmethod
    def _resolve_updated_date(slug: str, inputs_hash: str, override: str | None) -> date:
        """Pick the data-updated date, keeping it stable when the inputs are unchanged.

        The comparison is against the **inputs** digest rather than
        ``source_file_hash``, which also covers the figure basis: otherwise a
        figure-only correction — a changed clip bound, a changed channel
        exclusion — would move this date and advertise source data that nobody
        updated (FREYA-2968).

        Args:
            slug: The dataset slug.
            inputs_hash: The combined digest over this run's input files.
            override: An explicit ISO date, which always wins.

        Returns:
            The previous date when the inputs are unchanged, else today. A row
            written before the inputs digest existed carries no previous value
            to compare, so it takes today's date rather than a guess.
        """
        if override:
            return date.fromisoformat(override)
        existing = DrrDatasetData.get_data(slug)
        if not existing or not existing.data_updated_at:
            return timezone.localdate()
        previous = ((existing.summary or {}).get("source") or {}).get("inputs_sha256")
        if previous == inputs_hash:
            return existing.data_updated_at
        return timezone.localdate()

    @staticmethod
    def _upsert_data_row(
        *,
        slug: str,
        title: str,
        figures: dict[str, Any],
        summary: dict[str, Any],
        source_hash: str,
        generated_at: datetime,
        data_updated_at: date,
    ) -> None:
        """Create or update the ``DrrDatasetData`` row for the slug."""
        DrrDatasetData.objects.update_or_create(
            dataset_slug=slug,
            defaults={
                "dataset_title": title,
                "data": figures,
                "summary": summary,
                "source_file_hash": source_hash,
                "generated_at": generated_at,
                "data_updated_at": data_updated_at,
            },
        )
