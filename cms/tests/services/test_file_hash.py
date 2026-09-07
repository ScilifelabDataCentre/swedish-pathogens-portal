"""Tests for dashboard source file hashing."""

from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from dashboard_visualisation.utils.uploads import calculate_file_hash


class TestCalculateFileHash(SimpleTestCase):
    """Tests for calculate_file_hash."""

    def test_same_content_produces_same_hash(self) -> None:
        """Test that identical file bytes yield the same digest."""
        content = b"date,value\n2024-01-01,1\n"
        hash_a = calculate_file_hash(BytesIO(content))
        hash_b = calculate_file_hash(BytesIO(content))
        self.assertEqual(hash_a, hash_b)
        self.assertEqual(len(hash_a), 64)

    def test_different_content_produces_different_hash(self) -> None:
        """Test that different file bytes yield different digests."""
        hash_a = calculate_file_hash(BytesIO(b"a,b\n1,2\n"))
        hash_b = calculate_file_hash(BytesIO(b"a,b\n3,4\n"))
        self.assertNotEqual(hash_a, hash_b)

    def test_uploaded_file_resets_read_position(self) -> None:
        """Test that hashing an uploaded file leaves the read position at zero."""
        uploaded = SimpleUploadedFile("test.csv", b"a,b\n1,2\n", "text/csv")
        calculate_file_hash(uploaded)
        self.assertEqual(uploaded.tell(), 0)
