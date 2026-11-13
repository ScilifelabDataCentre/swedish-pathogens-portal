"""Utility functions for testing."""

import io
import re
import tempfile
from collections.abc import Iterator
from pathlib import Path

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.base import Node, NodeList
from django.template.defaulttags import URLNode
from django.template.loader import get_template
from django.test import SimpleTestCase, TestCase, override_settings
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


def create_test_image(
    *,
    title: str = "Test image",
    file_name: str = "test.jpg",
    image_id: int | None = None,
):
    """Create and save a minimal test image for use in tests.

    Args:
        title (str): The title for the image.
        file_name (str): The file name for the image.
        image_id (int | None): Optional primary key, used when a test needs a
            specific existing-library id.

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
    kwargs = {}
    if image_id is not None:
        kwargs["id"] = image_id
    return Image.objects.create(
        title=title,
        file=SimpleUploadedFile(
            name=file_name,
            content=file_obj.read(),
            content_type="image/jpeg",
        ),
        **kwargs,
    )


def find_nodes(nodelist: NodeList, node_type: type[Node]) -> Iterator[Node]:
    """Find template nodes recursively.

    In a Django template, nodes can be nested within other nodes. This function
    recursively searches through a given nodelist and yields all nodes of the
    specified type.

    Args:
        nodelist: The list of nodes to search through.
        node_type: The type of node to look for.

    Yields:
        Node: The nodes of the specified type found in the nodelist.

    Example usage:
        from django.template.loader_tags import ExtendsNode
        some_template = get_template("some_template.html")
        extends_node = next(find_nodes(some_template.template.nodelist, ExtendsNode))
    """
    for node in nodelist:
        if isinstance(node, node_type):
            yield node

        if hasattr(node, "nodelist"):
            yield from find_nodes(node.nodelist, node_type)


def get_url_names_from_template(template_name: str) -> set[str]:
    """Get all URL names used in a template.

    This function loads a Django template by name, finds all URLNode instances i.e. `{% url %}` in
    the template's nodelist, and returns a set of the view names used in those URLNodes.

    Args:
        template_name: The name of the template to inspect.

    Returns:
        set[str]: A set of view names used in the template's URLNodes.

    Example usage:
        url_names = get_url_names_from_template("my_template.html")
    """
    template = get_template(template_name)
    url_nodes = find_nodes(template.template.nodelist, URLNode)
    return {node.view_name.var for node in url_nodes}


def get_url_from_email(
    test_case: TestCase | SimpleTestCase, recipient: str, email_index: int = 0
) -> str:
    """Get a URL from an outgoing email sent to a specific recipient.

    This function searches the Django test email outbox for emails sent to a specific recipient,
    retrieves the email at the specified index, and extracts the first URL found in the email body.

    Args:
        test_case: The test case instance, used for assertions.
        recipient: The email address of the recipient to search for in the outbox.
        email_index: The index of the email to retrieve for the specified recipient (default is 0).

    Returns:
        str: The first URL found in the email body.

    Raises:
        AssertionError: If no email is found for the recipient or if no URL is found in the email.

    Example usage:
        # Intended to be used in a test case
        url = get_url_from_email(self, "test@example.com")
    """
    matching_emails = [email for email in mail.outbox if recipient in email.to]

    test_case.assertGreater(
        len(matching_emails), email_index, f"No email found for recipient {recipient}."
    )

    email_body = matching_emails[email_index].body
    match = re.search(r"https?://[^\s<>]+", email_body)

    test_case.assertIsNotNone(match, f"No URL found in email to {recipient}.")

    return match.group(0)
