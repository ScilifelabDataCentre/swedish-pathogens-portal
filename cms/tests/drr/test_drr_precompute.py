"""Tests for the drr_precompute management command (FREYA-2556)."""

from __future__ import annotations

import base64
import json
import re
import tempfile
from pathlib import Path

import numpy as np
import polars as pl
from django.core.management import call_command
from django.test import TestCase, override_settings

from cms.snippets.drr_dataset_data import DrrDatasetData
from dashboard_visualisation.drr.figures import FEATURE_CATEGORIES
from dashboard_visualisation.drr.loader import load_feature_table

SLUG = "test-drr-dataset"

# Six well-level profiles across two plates, three compounds, and both trt and
# control perturbations. Feature columns span all three compartments and four
# channels so summary derivation and category aggregation are exercised. The
# leading unnamed column mirrors the upstream export's row index, and
# ``Count_nuclei`` sits where the export carries it: numeric, but QC metadata
# rather than a feature (spec section 5).
FEATURE_CSV = (
    ";Metadata_Barcode;Metadata_Well;comp_conc;pert_type;batch_id;cmpd_conc;cbkid;Count_nuclei;"
    "AreaShape_Area_nuclei;Intensity_MeanIntensity_illumCONC_nuclei;"
    "Granularity_1_illumMITO_cells;Correlation_Correlation_illumCONC_illumHOECHST_cytoplasm;"
    "RadialDistribution_MeanFrac_illumSYTO_1of4_cells;"
    "Neighbors_FirstClosestDistance_Adjacent_cells\n"
    "0;P1;A01;10;trt;B1;10;CBK1;1200;1.0;2.0;3.0;0.10;0.50;2.0\n"
    "1;P1;A02;10;trt;B1;10;CBK1;1250;1.2;2.1;3.4;0.20;0.60;2.1\n"
    "2;P1;A03;10;ctrl;B1;0;CBK2;1400;0.9;1.8;2.9;0.05;0.40;1.9\n"
    "3;P2;B01;10;trt;B1;10;CBK3;1150;1.5;2.5;3.9;0.30;0.70;2.4\n"
    "4;P2;B02;10;ctrl;B1;0;CBK2;1380;0.8;1.7;2.7;0.02;0.35;1.8\n"
    "5;P2;B03;10;trt;B1;10;CBK3;1100;1.6;2.6;4.1;0.35;0.75;2.5\n"
)

# Per-category means of the fixture rows, in the input's own units: the two ctrl
# rows (the radar's "infected" reference, and CBK2's heatmap row), the four trt
# rows (the "compound" radar), and the two remaining compounds' heatmap rows.
# These hold only while the figures run on the values as delivered; standardising
# the columns again drives each of them to a z-score around -1 to 1 instead.
CTRL_CATEGORY_MEANS = {
    "AreaShape": 0.85,
    "Intensity": 1.75,
    "Granularity": 2.8,
    "Correlation": 0.035,
    "RadialDistribution": 0.375,
    "Neighbors": 1.85,
}
TRT_CATEGORY_MEANS = {
    "AreaShape": 1.325,
    "Intensity": 2.3,
    "Granularity": 3.6,
    "Correlation": 0.2375,
    "RadialDistribution": 0.6375,
    "Neighbors": 2.25,
}
CBK1_CATEGORY_MEANS = {
    "AreaShape": 1.1,
    "Intensity": 2.05,
    "Granularity": 3.2,
    "Correlation": 0.15,
    "RadialDistribution": 0.55,
    "Neighbors": 2.05,
}
CBK3_CATEGORY_MEANS = {
    "AreaShape": 1.55,
    "Intensity": 2.55,
    "Granularity": 4.0,
    "Correlation": 0.325,
    "RadialDistribution": 0.725,
    "Neighbors": 2.45,
}

# CBK3 is intentionally absent to exercise the unmatched-cbkid path.
METADATA_TSV = (
    "cbkid\tname\tbroad_moa\tbroad_target\tFiles\n"
    "CBK1\tcompoundA\tinhibitor\tTGT1\tcovid-repurpose/a.ome.zarr.zip\n"
    "CBK2\tcompoundB\tnull\tnull\tcovid-repurpose/b.ome.zarr.zip\n"
)

# The name lookup in miniature (FREYA-2628): one treated compound the feature
# table also holds, one negative control whose "name" is its condition and is
# therefore excluded, and one lookup id absent from the feature table. CBK3 is
# absent from the lookup, so it keeps a null name.
NAME_LOOKUP_ROWS = {
    "cbkid": ["CBK1", "CBK2", "CBK9"],
    "pert_iname": ["remdesivir", "DMSO", "aloxistatin"],
    "pert_type": ["trt", "negcon", "trt"],
}

EXPECTED_FIGURE_IDS = {"pca", "heatmap", "radar_compound", "radar_infected"}
ARTEFACT_SUFFIXES = {".csv", ".parquet", ".json"}


def _decode_array(payload: dict | list) -> np.ndarray:
    """Return a numeric array from figure JSON, decoding Plotly's base64 form."""
    if isinstance(payload, list):
        return np.asarray(payload)
    shape = tuple(int(part) for part in payload["shape"].split(","))
    buffer = base64.b64decode(payload["bdata"])
    return np.frombuffer(buffer, dtype=payload["dtype"]).reshape(shape)


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

    def _write_names(self, names: list[str] | None = None) -> Path:
        """Write the name lookup as a compressed Arrow file, as upstream ships it."""
        rows = dict(NAME_LOOKUP_ROWS)
        if names is not None:
            rows["pert_iname"] = names
        path = self.base / "names.feather"
        pl.DataFrame(rows).write_ipc(path, compression="zstd")
        return path

    def _write_incomplete_input(self) -> None:
        """Blank one ctrl row's AreaShape value, leaving a gap in the feature matrix."""
        self.input_path.write_text(
            FEATURE_CSV.replace("0;CBK2;1400;0.9;", "0;CBK2;1400;;"), encoding="utf-8"
        )

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

    def test_count_nuclei_is_metadata_not_a_feature(self) -> None:
        """Count_nuclei is QC metadata: out of the feature set, still in the download."""
        self._run()
        table = load_feature_table(self.input_path)
        self.assertIn("Count_nuclei", table.metadata_columns)
        self.assertNotIn("Count_nuclei", table.feature_columns)

        summary = json.loads((self.out_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["n_features"], 6)
        features = pl.read_parquet(self.out_dir / "features.parquet")
        self.assertIn("Count_nuclei", features.columns)

    def test_radars_are_not_standardised(self) -> None:
        """Both radar modes plot category means in the values' own units (spec section 5)."""
        self._run()
        figures = DrrDatasetData.get_data(SLUG).data

        for figure_id, expected in (
            ("radar_infected", CTRL_CATEGORY_MEANS),
            ("radar_compound", TRT_CATEGORY_MEANS),
        ):
            radii = figures[figure_id]["data"][0]["r"]
            self.assertEqual(len(radii), len(FEATURE_CATEGORIES) + 1, figure_id)
            for index, category in enumerate(FEATURE_CATEGORIES):
                self.assertAlmostEqual(radii[index], expected[category], places=6, msg=figure_id)
            # The ring closes on its first axis.
            self.assertAlmostEqual(radii[-1], radii[0], places=6, msg=figure_id)

    def test_heatmap_cells_are_not_standardised(self) -> None:
        """Heatmap cells are per-compound category means, one row per compound."""
        self._run()
        trace = DrrDatasetData.get_data(SLUG).data["heatmap"]["data"][0]

        self.assertEqual(trace["y"], ["CBK1", "CBK2", "CBK3"])
        self.assertEqual(trace["x"], FEATURE_CATEGORIES)
        cells = _decode_array(trace["z"])
        for row, expected in enumerate(
            (CBK1_CATEGORY_MEANS, CTRL_CATEGORY_MEANS, CBK3_CATEGORY_MEANS)
        ):
            for column, category in enumerate(FEATURE_CATEGORIES):
                self.assertAlmostEqual(
                    float(cells[row][column]), expected[category], places=6, msg=category
                )

    def test_pca_axes_carry_the_variance_they_explain(self) -> None:
        """Each PCA axis states its own share of the variance, as paper Fig 1C does.

        The expected shares come from the eigenvalues of the feature covariance,
        which is the same quantity by a different route: it agrees only while the
        decomposition is mean-centred and left unscaled.
        """
        self._run()
        layout = DrrDatasetData.get_data(SLUG).data["pca"]["layout"]

        matrix = load_feature_table(self.input_path).numeric_matrix()
        eigenvalues = np.sort(np.linalg.eigvalsh(np.cov(matrix, rowvar=False, bias=True)))[::-1]
        expected = 100 * eigenvalues[:2] / eigenvalues.sum()

        for axis, component, want in (("xaxis", "PC1", expected[0]), ("yaxis", "PC2", expected[1])):
            title = layout[axis]["title"]["text"]
            match = re.fullmatch(rf"{component} \((\d+\.\d)% variance\)", title)
            self.assertIsNotNone(match, title)
            self.assertEqual(match.group(1), f"{want:.1f}", title)

    def test_missing_feature_values_are_not_imputed(self) -> None:
        """A gap in the feature matrix fails loudly, naming its column, rather than being filled."""
        self._write_incomplete_input()
        with self.assertRaisesMessage(ValueError, "AreaShape_Area_nuclei"):
            self._run()

    def test_incomplete_input_publishes_nothing(self) -> None:
        """A run that cannot build figures leaves no downloadable artefact behind."""
        self._write_incomplete_input()
        with self.assertRaises(ValueError):
            self._run()

        self.assertEqual([path for path in self.out_dir.rglob("*") if path.is_file()], [])
        self.assertIsNone(DrrDatasetData.get_data(SLUG))

    def test_incomplete_rerun_leaves_the_previous_generation_intact(self) -> None:
        """A failed re-run cannot leave a new download beside the old figures."""
        self._run()
        before = {path: path.read_bytes() for path in self.out_dir.rglob("*") if path.is_file()}
        row = DrrDatasetData.get_data(SLUG)

        self._write_incomplete_input()
        with self.assertRaises(ValueError):
            self._run()

        after = {path: path.read_bytes() for path in self.out_dir.rglob("*") if path.is_file()}
        self.assertEqual(after, before)
        reloaded = DrrDatasetData.get_data(SLUG)
        self.assertEqual(reloaded.source_file_hash, row.source_file_hash)
        self.assertEqual(reloaded.data, row.data)

    def test_compound_index_includes_unmatched(self) -> None:
        """Every feature cbkid is indexed; unmatched compounds keep null metadata."""
        self._run()
        compounds = pl.read_parquet(self.out_dir / "compounds.parquet")
        self.assertEqual(compounds.height, 3)
        self.assertEqual(compounds["cbkid"].to_list(), ["CBK1", "CBK2", "CBK3"])
        unmatched = compounds.filter(pl.col("name").is_null())
        self.assertEqual(unmatched["cbkid"].to_list(), ["CBK3"])

    def test_compound_index_has_reconciliation_columns(self) -> None:
        """The index carries the normalized join key and the compound/control kind."""
        self._run()
        compounds = pl.read_parquet(self.out_dir / "compounds.parquet")
        self.assertEqual(
            compounds.columns,
            [
                "cbkid",
                "cbkid_normalized",
                "kind",
                "n_profiles",
                "name",
                "broad_moa",
                "broad_target",
            ],
        )
        self.assertEqual(compounds["cbkid_normalized"].to_list(), ["CBK1", "CBK2", "CBK3"])
        self.assertEqual(compounds["kind"].unique().to_list(), ["compound"])

    def test_compound_names_are_joined_when_supplied(self) -> None:
        """The lookup adds pert_iname last; conditions and absent ids stay null."""
        self._run(compound_names=str(self._write_names()))
        compounds = pl.read_parquet(self.out_dir / "compounds.parquet")

        self.assertEqual(
            compounds.columns,
            [
                "cbkid",
                "cbkid_normalized",
                "kind",
                "n_profiles",
                "name",
                "broad_moa",
                "broad_target",
                "pert_iname",
            ],
        )
        self.assertEqual(compounds["pert_iname"].to_list(), ["remdesivir", None, None])

    def test_summary_has_name_lookup_block(self) -> None:
        """The name_lookup counts describe the join the run actually made."""
        names_path = self._write_names()
        self._run(compound_names=str(names_path))
        summary = json.loads((self.out_dir / "summary.json").read_text(encoding="utf-8"))
        lookup = summary["name_lookup"]

        self.assertEqual(lookup["source"], "names.feather")
        self.assertEqual(len(lookup["sha256"]), 64)
        self.assertEqual(lookup["n_lookup_ids"], 2)
        self.assertEqual(lookup["n_named"], 1)
        self.assertEqual(lookup["n_unnamed"], 2)
        self.assertEqual(lookup["n_condition_rows_excluded"], 1)
        self.assertEqual(lookup["n_conflicting_ids"], 0)

    def test_without_compound_names_nothing_changes(self) -> None:
        """Omitted, the flag leaves no name column and a null lookup source."""
        self._run()
        compounds = pl.read_parquet(self.out_dir / "compounds.parquet")
        summary = json.loads((self.out_dir / "summary.json").read_text(encoding="utf-8"))

        self.assertNotIn("pert_iname", compounds.columns)
        self.assertIsNone(summary["name_lookup"]["source"])
        self.assertIsNone(summary["name_lookup"]["sha256"])

    def test_compound_names_never_reach_the_downloads(self) -> None:
        """pert_iname is a compound-index column only: the feature artefacts keep their shape."""
        self._run(compound_names=str(self._write_names()))

        features = pl.read_parquet(self.out_dir / "features.parquet")
        self.assertNotIn("pert_iname", features.columns)
        header = (self.out_dir / "features.csv").read_text(encoding="utf-8").splitlines()[0]
        self.assertNotIn("pert_iname", header)

    def test_name_change_busts_snippet_hash_only(self) -> None:
        """A names-only change folds into the snippet hash; summary keeps the feature digest."""
        self._run(compound_names=str(self._write_names()))
        first = DrrDatasetData.get_data(SLUG)
        first_summary_sha = json.loads((self.out_dir / "summary.json").read_text(encoding="utf-8"))[
            "source"
        ]["sha256"]

        self._run(compound_names=str(self._write_names(["remdesivir-alt", "DMSO", "aloxistatin"])))
        second = DrrDatasetData.get_data(SLUG)
        second_summary = json.loads((self.out_dir / "summary.json").read_text(encoding="utf-8"))

        self.assertNotEqual(second.source_file_hash, first.source_file_hash)
        self.assertEqual(second_summary["source"]["sha256"], first_summary_sha)
        compounds = pl.read_parquet(self.out_dir / "compounds.parquet")
        self.assertEqual(compounds["pert_iname"].to_list(), ["remdesivir-alt", None, None])

    def test_summary_has_reconciliation_block(self) -> None:
        """The summary carries the cbkid reconciliation report for editors."""
        self._run()
        summary = json.loads((self.out_dir / "summary.json").read_text(encoding="utf-8"))
        recon = summary["compound_reconciliation"]
        self.assertEqual(recon["n_compound_ids"], 3)
        self.assertEqual(recon["n_control_ids"], 0)
        self.assertEqual(recon["n_annotated"], 2)
        self.assertEqual(recon["n_recovered"], 0)
        self.assertEqual(recon["n_unannotated"], 1)
        self.assertEqual(recon["unmatched_cbkids"], ["CBK3"])

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

    def test_metadata_change_busts_snippet_hash_only(self) -> None:
        """A metadata-only change folds into the snippet hash; summary keeps the feature digest."""
        self._run()
        first = DrrDatasetData.get_data(SLUG)
        first_summary_sha = json.loads((self.out_dir / "summary.json").read_text(encoding="utf-8"))[
            "source"
        ]["sha256"]

        # Annotate the previously-unmatched CBK3; the feature CSV is untouched.
        self.metadata_path.write_text(
            METADATA_TSV + "CBK3\tcompoundC\tnull\tnull\tcovid-repurpose/c.ome.zarr.zip\n",
            encoding="utf-8",
        )
        self._run()
        second = DrrDatasetData.get_data(SLUG)
        second_summary = json.loads((self.out_dir / "summary.json").read_text(encoding="utf-8"))

        # The metadata input is folded into the snippet hash (busts the render cache)...
        self.assertNotEqual(second.source_file_hash, first.source_file_hash)
        # ...while summary.source.sha256 stays the feature-file digest.
        self.assertEqual(second_summary["source"]["sha256"], first_summary_sha)
        # And the reconciliation reflects the new annotation (CBK3 now matched).
        self.assertEqual(second_summary["compound_reconciliation"]["unmatched_cbkids"], [])
