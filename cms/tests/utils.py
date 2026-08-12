"""Utility functions for testing."""

import io
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from PIL import Image as PILImage
from wagtail.images import get_image_model

from dashboard_visualisation.utils.uploads import CsvValidationResult, validate_csv

__all__ = [
    "CsvValidationResult",
    "create_test_image",
    "use_temp_media_root",
    "validate_csv",
]


def use_temp_media_root(test_case: SimpleTestCase) -> Path:
    """Point ``MEDIA_ROOT`` at a temporary directory for the duration of one test.

    Both the override and the directory are torn down via ``addCleanup``, so tests
    that write derived artefacts never touch the developer's ``media/`` tree.

    Args:
        test_case: The running test case, used to register the cleanups.

    Returns:
        Path: The temporary directory now serving as ``MEDIA_ROOT``.
    """
    tmp = tempfile.TemporaryDirectory()
    test_case.addCleanup(tmp.cleanup)

    override = override_settings(MEDIA_ROOT=tmp.name)
    override.enable()
    test_case.addCleanup(override.disable)

    return Path(tmp.name)


def create_test_image(*, title: str = "Test image", file_name: str = "test.jpg"):
    """Create and save a minimal test image for use in tests.

    Args:
        title (str): The title for the image.
        file_name (str): The file name for the image.

    Example usage:
        image = create_test_image(title="My Test Image", file_name="my_test_image.jpg")

    Returns:
        Image: A saved Wagtail Image model instance.
    """
    file_obj = io.BytesIO()

    image = PILImage.new("RGB", (1, 1), color="white")
    image.save(file_obj, format="JPEG")

    file_obj.seek(0)

    Image = get_image_model()  # noqa: N806
    return Image.objects.create(
        title=title,
        file=SimpleUploadedFile(
            name=file_name,
            content=file_obj.read(),
            content_type="image/jpeg",
        ),
    )
