"""Management command: precompute DRR dataset artefacts (FREYA-2556).

Manual, repeatable, offline pipeline (spec section 5). Turns a Cell Painting
feature CSV plus its CBCS metadata TSV into the derived artefacts a
``DrrDatasetPage`` serves and upserts the slug-keyed ``DrrDatasetData`` row.
Raw imagery is never touched; only derived artefacts land under
``media/drr/<slug>/``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import structlog
from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from cms.snippets.drr_dataset_data import DrrDatasetData
from dashboard_visualisation.drr import (
    build_all_figures,
    build_compound_index,
    build_summary,
    load_feature_table,
    load_metadata,
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
        title = options["title"] or slug

        output_dir = Path(settings.MEDIA_ROOT) / "drr" / slug
        figures_dir = output_dir / "figures"
        figures_dir.mkdir(parents=True, exist_ok=True)

        LOGGER.info("drr.precompute.start", slug=slug, input=str(input_path))

        table = load_feature_table(input_path)
        metadata = load_metadata(metadata_path)

        compound_index = build_compound_index(table, metadata)
        compound_index.write_parquet(output_dir / "compounds.parquet")

        table.frame.write_csv(output_dir / "features.csv")
        table.frame.write_parquet(output_dir / "features.parquet")

        figures = build_all_figures(table, umap_coords=options["umap_coords"])
        self._write_figures(figures_dir, figures)

        feature_hash = self._hash_file(input_path)
        input_hashes = [feature_hash, self._hash_file(metadata_path)]
        if options["umap_coords"]:
            input_hashes.append(self._hash_file(Path(options["umap_coords"])))
        source_hash = self._combine_hashes(input_hashes)
        generated_at = timezone.now()
        summary = build_summary(
            table,
            source_filename=input_path.name,
            source_hash=feature_hash,
            generated_at=generated_at.isoformat(),
        )
        (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

        data_updated_at = self._resolve_updated_date(slug, source_hash, options["data_updated_at"])
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
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Precomputed DRR dataset '{slug}': {summary['n_compounds']} compounds, "
                f"{summary['n_profiles']} profiles, {len(figures)} figures -> {output_dir}"
            )
        )

    @staticmethod
    def _write_figures(figures_dir: Path, figures: dict[str, Any]) -> None:
        """Write each figure JSON to disk, clearing any stale figures first."""
        for stale in figures_dir.glob("*.json"):
            stale.unlink()
        for figure_id, payload in figures.items():
            (figures_dir / f"{figure_id}.json").write_text(json.dumps(payload), encoding="utf-8")

    @staticmethod
    def _hash_file(path: Path) -> str:
        """Return the SHA-256 of a file (calculate_file_hash needs a handle)."""
        with path.open("rb") as handle:
            return calculate_file_hash(handle)

    @staticmethod
    def _combine_hashes(hex_digests: list[str]) -> str:
        """Combine per-input SHA-256 digests into one stable cache-busting hash.

        Folding every precompute input (feature table, metadata, and any UMAP
        coordinates) into ``source_file_hash`` ensures the ``PlotlyFigureBlock``
        render cache (keyed by slug + figure_id + source_file_hash) is busted
        whenever any input that affects the figures changes.
        """
        hasher = hashlib.sha256()
        for digest in hex_digests:
            hasher.update(digest.encode("ascii"))
            hasher.update(b"\0")
        return hasher.hexdigest()

    @staticmethod
    def _resolve_updated_date(slug: str, source_hash: str, override: str | None) -> date:
        """Pick the data-updated date, keeping it stable when the source is unchanged."""
        if override:
            return date.fromisoformat(override)
        existing = DrrDatasetData.get_data(slug)
        if existing and existing.source_file_hash == source_hash and existing.data_updated_at:
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
