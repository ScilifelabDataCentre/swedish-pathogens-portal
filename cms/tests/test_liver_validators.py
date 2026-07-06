"""Tests for liver resource DE file validation."""

import csv
from io import BytesIO, StringIO
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from dashboard_visualisation.liver_resource.reference_data import get_data_root
from dashboard_visualisation.liver_resource.validators import (
    MAX_UPLOAD_BYTES,
    validate_de_data,
    validate_de_upload,
)


class TestLiverValidators(SimpleTestCase):
    """Verify DE upload validation rules."""

    def test_valid_example_file_passes(self) -> None:
        """Test bundled HCC-Control example passes validation."""
        path = get_data_root() / "examples" / "HCC-Control.txt"
        result = validate_de_upload(path)
        self.assertTrue(result.is_valid)
        self.assertEqual(result.errors, ())
        self.assertIsNotNone(result.de_data)
        self.assertGreater(result.gene_count, 10_000)

    def test_valid_csv_upload_passes(self) -> None:
        """Test comma-separated DE uploads pass validation."""
        path = get_data_root() / "examples" / "HCC-Control.txt"
        buffer = StringIO()
        writer = csv.writer(buffer)
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    writer.writerow(line.rstrip("\n").split("\t"))

        uploaded = SimpleUploadedFile(
            "HCC-Control.csv",
            buffer.getvalue().encode("utf-8"),
            content_type="text/csv",
        )
        result = validate_de_upload(uploaded)
        self.assertTrue(result.is_valid)
        self.assertGreater(result.gene_count, 10_000)

    def test_missing_required_columns(self) -> None:
        """Test missing logFC and adj.P.Val are rejected."""
        content = b"gene\tt\nENSG00000000003\t1.0\n"
        result = validate_de_upload(BytesIO(content))
        self.assertFalse(result.is_valid)
        self.assertTrue(any("Missing required columns" in error for error in result.errors))

    def test_invalid_ensembl_id(self) -> None:
        """Test non-Ensembl gene IDs are rejected."""
        header = "logFC\tadj.P.Val\tt\tP.Value\n"
        rows = "\n".join(f"GENE{i}\t0.1\t0.01\t1.0\t0.05" for i in range(101))
        result = validate_de_upload(BytesIO((header + rows).encode()))
        self.assertFalse(result.is_valid)
        self.assertTrue(any("Ensembl" in error for error in result.errors))

    def test_file_too_large(self) -> None:
        """Test upload size limit is enforced."""
        result = validate_de_upload(BytesIO(b""), size_bytes=MAX_UPLOAD_BYTES + 1)
        self.assertFalse(result.is_valid)
        self.assertTrue(any("too large" in error for error in result.errors))

    def test_duplicate_gene_ids(self) -> None:
        """Test duplicate gene IDs are rejected."""
        de_data = {
            "header": ["logFC", "adj.P.Val"],
            "genes": ["ENSG00000000003", "ENSG00000000003"],
            "data": {
                "ENSG00000000003": {"logFC": 1.0, "adj.P.Val": 0.01},
            },
        }
        errors = validate_de_data(de_data)
        self.assertTrue(any("Duplicate" in error for error in errors))

    def test_uploaded_file_object(self) -> None:
        """Test validation works with Django uploaded file objects."""
        path = Path(get_data_root() / "examples" / "HCC-Control.txt")
        upload = SimpleUploadedFile(
            name="HCC-Control.txt",
            content=path.read_bytes(),
            content_type="text/plain",
        )
        result = validate_de_upload(upload)
        self.assertTrue(result.is_valid)
