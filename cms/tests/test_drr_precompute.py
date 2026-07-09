"""Tests for the drr_precompute management command (FREYA-2556)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import polars as pl
from django.core.management import call_command
from django.test import TestCase, override_settings

from cms.snippets.drr_dataset_data import DrrDatasetData

SLUG = "test-drr-dataset"

# Six well-level profiles across two plates, three compounds, and both trt and
# control perturbations. Feature columns span all three compartments and four
# channels so summary derivation and category aggregation are exercised. The
# leading unnamed column mirrors the upstream export's row index.
FEATURE_CSV = (
    ";Metadata_Barcode;Metadata_Well;comp_conc;pert_type;batch_id;cmpd_conc;cbkid;"
    "AreaShape_Area_nuclei;Intensity_MeanIntensity_illumCONC_nuclei;"
    "Granularity_1_illumMITO_cells;Correlation_Correlation_illumCONC_illumHOECHST_cytoplasm;"
    "RadialDistribution_MeanFrac_illumSYTO_1of4_cells;"
    "Neighbors_FirstClosestDistance_Adjacent_cells\n"
    "0;P1;A01;10;trt;B1;10;CBK1;1.0;2.0;3.0;0.10;0.50;2.0\n"
    "1;P1;A02;10;trt;B1;10;CBK1;1.2;2.1;3.4;0.20;0.60;2.1\n"
    "2;P1;A03;10;ctrl;B1;0;CBK2;0.9;1.8;2.9;0.05;0.40;1.9\n"
    "3;P2;B01;10;trt;B1;10;CBK3;1.5;2.5;3.9;0.30;0.70;2.4\n"
    "4;P2;B02;10;ctrl;B1;0;CBK2;0.8;1.7;2.7;0.02;0.35;1.8\n"
    "5;P2;B03;10;trt;B1;10;CBK3;1.6;2.6;4.1;0.35;0.75;2.5\n"
)

# CBK3 is intentionally absent to exercise the unmatched-cbkid path.
METADATA_TSV = (
    "cbkid\tname\tbroad_moa\tbroad_target\tFiles\n"
    "CBK1\tcompoundA\tinhibitor\tTGT1\tcovid-repurpose/a.ome.zarr.zip\n"
    "CBK2\tcompoundB\tnull\tnull\tcovid-repurpose/b.ome.zarr.zip\n"
)

EXPECTED_FIGURE_IDS = {"pca", "heatmap", "radar_compound", "radar_infected"}
ARTEFACT_SUFFIXES = {".csv", ".parquet", ".json"}


class DrrPrecomputeTests(TestCase):
    """Exercise the offline precompute pipeline end-to-end on tiny fixtures."""

    def setUp(self) -> None:
        """Write fixture inputs and set up an isolated media root per test."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.input_path = self.base / "features.csv"
        self.input_path.write_text(FEATURE_CSV, encoding="utf-8")
        self.metadata_path = self.base / "metadata.tsv"
        self.metadata_path.write_text(METADATA_TSV, encoding="utf-8")
        self.media = self.base / "media"
        self.out_dir = self.media / "drr" / SLUG

    def _run(self, **extra: str) -> None:
        """Invoke drr_precompute against the fixtures with MEDIA_ROOT overridden."""
        with override_settings(MEDIA_ROOT=str(self.media)):
            call_command(
                "drr_precompute",
                slug=SLUG,
                input=str(self.input_path),
                metadata=str(self.metadata_path),
                title="Test DRR",
                **extra,
            )

    def test_artefacts_written(self) -> None:
        """All derived files are written; umap is skipped without coordinates."""
        self._run()
        for name in ("features.csv", "features.parquet", "compounds.parquet", "summary.json"):
            self.assertTrue((self.out_dir / name).is_file(), name)
        for figure_id in EXPECTED_FIGURE_IDS:
            self.assertTrue((self.out_dir / "figures" / f"{figure_id}.json").is_file(), figure_id)
        self.assertFalse((self.out_dir / "figures" / "umap.json").exists())

    def test_data_row_upserted(self) -> None:
        """A DrrDatasetData row is created with figures, summary, and provenance."""
        self._run()
        row = DrrDatasetData.get_data(SLUG)
        self.assertIsNotNone(row)
        self.assertEqual(set(row.data), EXPECTED_FIGURE_IDS)
        self.assertEqual(len(row.source_file_hash), 64)
        self.assertIsNotNone(row.data_updated_at)
        self.assertIsNotNone(row.generated_at)
        self.assertEqual(row.dataset_title, "Test DRR")

    def test_summary_counts(self) -> None:
        """Summary statistics reflect the fixture's compounds, plates, and wells."""
        self._run()
        summary = json.loads((self.out_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["n_compounds"], 3)
        self.assertEqual(summary["n_plates"], 2)
        self.assertEqual(summary["n_wells"], 6)
        self.assertEqual(summary["n_profiles"], 6)
        self.assertEqual(summary["n_features"], 6)
        self.assertEqual(summary["pert_type_counts"], {"ctrl": 2, "trt": 4})
        self.assertEqual(summary["compartments"], ["nuclei", "cells", "cytoplasm"])
        self.assertEqual(summary["channels"], ["CONC", "HOECHST", "MITO", "SYTO"])
        self.assertEqual(summary["source"]["filename"], "features.csv")

    def test_compound_index_includes_unmatched(self) -> None:
        """Every feature cbkid is indexed; unmatched compounds keep null metadata."""
        self._run()
        compounds = pl.read_parquet(self.out_dir / "compounds.parquet")
        self.assertEqual(compounds.height, 3)
        self.assertEqual(compounds["cbkid"].to_list(), ["CBK1", "CBK2", "CBK3"])
        unmatched = compounds.filter(pl.col("name").is_null())
        self.assertEqual(unmatched["cbkid"].to_list(), ["CBK3"])

    def test_features_parquet_is_cbkid_anchored(self) -> None:
        """The features parquet retains cbkid so per-compound slicing is possible."""
        self._run()
        features = pl.read_parquet(self.out_dir / "features.parquet")
        self.assertIn("cbkid", features.columns)
        self.assertEqual(features.height, 6)

    def test_idempotent(self) -> None:
        """Re-running reproduces an identical hash and figure JSON, without duplicating rows."""
        self._run()
        first = DrrDatasetData.get_data(SLUG)
        first_hash = first.source_file_hash
        first_pca = json.dumps(first.data["pca"], sort_keys=True)

        self._run()
        self.assertEqual(DrrDatasetData.objects.filter(dataset_slug=SLUG).count(), 1)
        second = DrrDatasetData.get_data(SLUG)
        self.assertEqual(second.source_file_hash, first_hash)
        self.assertEqual(json.dumps(second.data["pca"], sort_keys=True), first_pca)

    def test_figures_have_no_trace_uid(self) -> None:
        """Serialised figures drop Plotly's random trace uids (hash stability)."""
        self._run()
        row = DrrDatasetData.get_data(SLUG)
        for payload in row.data.values():
            for trace in payload.get("data", []):
                self.assertNotIn("uid", trace)

    def test_no_raw_images_persisted(self) -> None:
        """Only derived csv/parquet/json artefacts are written; no raw imagery."""
        self._run()
        for path in self.out_dir.rglob("*"):
            if path.is_file():
                self.assertIn(path.suffix, ARTEFACT_SUFFIXES, str(path))

    def test_umap_included_with_coords(self) -> None:
        """Supplying UMAP coordinates adds the umap figure and artefact."""
        coords_path = self.base / "umap.parquet"
        pl.DataFrame(
            {
                "umap_x": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
                "umap_y": [1.1, 1.2, 1.3, 1.4, 1.5, 1.6],
                "pert_type": ["trt", "trt", "ctrl", "trt", "ctrl", "trt"],
            }
        ).write_parquet(coords_path)

        self._run(umap_coords=str(coords_path))

        self.assertTrue((self.out_dir / "figures" / "umap.json").is_file())
        row = DrrDatasetData.get_data(SLUG)
        self.assertIn("umap", row.data)

    def test_umap_coords_change_busts_source_hash(self) -> None:
        """Changing only the UMAP coords changes source_file_hash (busts the render cache)."""
        coords_a = self.base / "umap_a.parquet"
        pl.DataFrame(
            {
                "umap_x": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
                "umap_y": [1.1, 1.2, 1.3, 1.4, 1.5, 1.6],
                "pert_type": ["trt", "trt", "ctrl", "trt", "ctrl", "trt"],
            }
        ).write_parquet(coords_a)
        self._run(umap_coords=str(coords_a))
        first = DrrDatasetData.get_data(SLUG)
        first_hash = first.source_file_hash
        first_umap = json.dumps(first.data["umap"], sort_keys=True)

        coords_b = self.base / "umap_b.parquet"
        pl.DataFrame(
            {
                "umap_x": [5.1, 5.2, 5.3, 5.4, 5.5, 5.6],
                "umap_y": [9.1, 9.2, 9.3, 9.4, 9.5, 9.6],
                "pert_type": ["trt", "trt", "ctrl", "trt", "ctrl", "trt"],
            }
        ).write_parquet(coords_b)
        self._run(umap_coords=str(coords_b))
        second = DrrDatasetData.get_data(SLUG)

        self.assertNotEqual(second.source_file_hash, first_hash)
        self.assertNotEqual(json.dumps(second.data["umap"], sort_keys=True), first_umap)
