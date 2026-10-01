"""Embed an official EU AI icon into a confirmed Wagtail image.

The service reads ``ImageAIDisclosure``. It does not inspect pixels, titles, or
filenames to decide whether an image is AI-generated. The Wagtail image form
calls ``label_image`` after a save that confirms the disclosure.
"""

from __future__ import annotations

import hashlib
import io
from enum import StrEnum
from pathlib import Path

import structlog
from django.conf import settings
from django.utils import timezone
from PIL import Image as PILImage
from PIL import ImageOps
from wagtail.images.models import AbstractImage, hash_filelike

from cms.image_ai import GenerationStatus, ImageAIDisclosure

LOGGER = structlog.get_logger(__name__)

# Placement profile. The Code of Practice names the top-right corner and requires
# the icon to stay visible against its background. It does not fix a pixel size.
LABEL_VERSION = "eu-2026-06-10-top-right-v1"
ICON_WIDTH_RATIO = 0.22
PADDING_RATIO = 0.02
MIN_PADDING_PX = 4
MIN_ICON_BOX_PX = 16
SUPPORTED_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})
ICON_DIR = Path(__file__).resolve().parents[1] / "static" / "cms" / "images" / "ai_labels"
STATUS_ICON_STEM = {
    GenerationStatus.FULLY_AI: "fully-ai-generated",
    GenerationStatus.PARTIALLY_AI: "partially-ai-modified",
}

# SHA-256 of the Commission files. A mismatch means the artwork is not the
# official icon and labelling must stop.
OFFICIAL_ICON_SHA256 = {
    "basic-black.svg": "58ffe859a4d74829d397f534a988081bcefb716849c7d3b84fa7a026dd1d257f",
    "basic-black-50.svg": "f8e20f1dde8c7d95940da08960b1063620812acc9b4ea96eb5ad051f80f67c21",
    "basic-white.svg": "5b3b94ae67fea55c4f2d013d0b8ed5b876c1533555ed0ed60e688f2f3ccf1a50",
    "basic-white-50.svg": "52d87cb3f6a191dba24796f745e1eeb80d342883acd1a2e6d856342ad853766c",
    "fully-ai-generated-black.svg": (
        "503af176b05fd725e68b0aa526977d31bcd657d74b15c6103a57ace81384940f"
    ),
    "fully-ai-generated-black-50.svg": (
        "63d28ab55916b4548edff21d5fbcac065a13e5fb936e9b304ff0bada45f2fac1"
    ),
    "fully-ai-generated-white.svg": (
        "10125cdef3fc60a351df72fe1266bb00ea046086921bd1bb20135f0f07b5ed36"
    ),
    "fully-ai-generated-white-50.svg": (
        "d19736f6da9d38af3cffce8ba08f3f7658b573e1794c173fcd8b55a5c200ed44"
    ),
    "partially-ai-modified-black.svg": (
        "2e7349e5eca4ee78eeef160dfef4545c31850932245373a07c5401e73e6599c0"
    ),
    "partially-ai-modified-black-50.svg": (
        "9ab09f54c1ccef01799af43794cd93a8af6607ba9ac6b9526fb90a02be8ddf3d"
    ),
    "partially-ai-modified-white.svg": (
        "0c72a7d569a1447e2982a843e156bd5f9cb2ab6f201943c6c68f988dc2f1bb6e"
    ),
    "partially-ai-modified-white-50.svg": (
        "7ccbce41f9f821a574007b32806ddb6d635ee8bbc5d753ccd05f66f5a3165845"
    ),
    "fully-ai-generated-black.png": (
        "8d0af57bc93ba3797042a4b56db757d85f924d9b0200b75b8842da7be5e402a2"
    ),
    "fully-ai-generated-white.png": (
        "f139d8de4b5173f47a777431e7e03d9258d8ea7ee1ee1a062febc7e9fff067fc"
    ),
    "partially-ai-modified-black.png": (
        "0f32e4afbe1459baaf425c78373ea541421ecdb61803438892e2fc07df67da8f"
    ),
    "partially-ai-modified-white.png": (
        "64241cf4f87eb0837bd234cb63716c7d78f4e9dbbb8866f40464ca4e6bfbfead"
    ),
}

_ICON_CACHE: dict[str, PILImage.Image] = {}


class LabelOutcome(StrEnum):
    """What the service did with one image."""

    LABELLED = "labelled"
    NOT_REQUIRED = "not_required"
    ALREADY_LABELLED = "already_labelled"


class LabelResult:
    """Outcome of one labelling call."""

    def __init__(self, outcome: LabelOutcome, file_hash: str) -> None:
        """Store the outcome and the SHA-256 of the public file.

        Args:
            outcome: Whether the file was stamped, skipped, or already current.
            file_hash: SHA-256 hex digest of the public file after the call.
        """
        self.outcome = outcome
        self.file_hash = file_hash


class AIImageLabellingError(Exception):
    """Labelling failed and the public file was left unchanged."""


class UnconfirmedDisclosureError(AIImageLabellingError):
    """The disclosure has no reviewer, so the file must not be changed."""


class UnsupportedImageError(AIImageLabellingError):
    """The file is animated, too small, or not a supported still image."""


def label_image(image: AbstractImage) -> LabelResult:
    """Embed the matching official icon when the disclosure is confirmed and in scope.

    Args:
        image: Saved Wagtail image whose disclosure row already exists.

    Returns:
        LabelResult: Whether the public file was stamped, left alone because no
        label is required, or already carried the current label.

    Raises:
        UnconfirmedDisclosureError: ``reviewed_by`` or ``reviewed_at`` is empty.
        UnsupportedImageError: The file is animated, too small, or unsupported.
        AIImageLabellingError: The disclosure, archive, or official icon is unusable.
    """
    disclosure = _disclosure_for(image)
    if not disclosure.is_reviewed:
        raise UnconfirmedDisclosureError("disclosure has no reviewer")
    if not disclosure.requires_label:
        LOGGER.info("ai_image.skipped", image_id=image.pk)
        return LabelResult(LabelOutcome.NOT_REQUIRED, "")

    public_path = _public_path(image)
    original = public_path.read_bytes()
    current_hash = hashlib.sha256(original).hexdigest()
    if disclosure.labelled_file_hash == current_hash:
        if disclosure.label_version != LABEL_VERSION:
            raise AIImageLabellingError(
                "labelled file uses another icon version; restore the pristine archive first"
            )
        return LabelResult(LabelOutcome.ALREADY_LABELLED, current_hash)

    labelled = _embed(original, disclosure.generation_status)
    _archive_pristine(image.pk, current_hash, public_path.suffix, original)
    _replace_public_file(public_path, labelled)
    labelled_hash = hashlib.sha256(labelled).hexdigest()
    _record_label(image, disclosure, labelled, labelled_hash)
    _clear_renditions(image)
    LOGGER.info(
        "ai_image.labelled",
        image_id=image.pk,
        generation_status=disclosure.generation_status,
        label_version=LABEL_VERSION,
    )
    return LabelResult(LabelOutcome.LABELLED, labelled_hash)


def ensure_image_can_be_labelled(data: bytes, generation_status: str) -> None:
    """Reject bytes that cannot take the official icon.

    Args:
        data: Image file bytes that would be labelled.
        generation_status: Confirmed ``fully_ai`` or ``partially_ai`` value.

    Raises:
        UnsupportedImageError: The file is animated, too small, or unsupported.
        PILImage.UnidentifiedImageError: Pillow cannot read the file.
    """
    with PILImage.open(io.BytesIO(data)) as opened:
        _require_supported(opened)
        oriented = ImageOps.exif_transpose(opened)
        size = oriented.size
    stem = STATUS_ICON_STEM[generation_status]
    reference = _load_icon(f"{stem}-black.png")
    _icon_box(size, reference.size)


def _disclosure_for(image: AbstractImage) -> ImageAIDisclosure:
    """Return the disclosure row for an image.

    Args:
        image: Saved Wagtail image.

    Returns:
        ImageAIDisclosure: The sidecar row.

    Raises:
        AIImageLabellingError: The image has no disclosure row.
    """
    try:
        return ImageAIDisclosure.objects.get(image_id=image.pk)
    except ImageAIDisclosure.DoesNotExist as exc:
        raise AIImageLabellingError("image has no disclosure row") from exc


def _public_path(image: AbstractImage) -> Path:
    """Return the local public file path.

    Args:
        image: Wagtail image stored on the local filesystem.

    Returns:
        Path: Absolute path of the public original.

    Raises:
        AIImageLabellingError: Storage has no local path, or the file is outside media.
    """
    try:
        path = Path(image.file.path).resolve()
    except NotImplementedError as exc:
        raise AIImageLabellingError("image storage has no local file path") from exc
    media_root = Path(settings.MEDIA_ROOT).resolve()
    if not path.is_relative_to(media_root):
        raise AIImageLabellingError("image file is outside MEDIA_ROOT")
    return path


def _embed(original: bytes, generation_status: str) -> bytes:
    """Return image bytes with the official icon composited into the top-right.

    Args:
        original: Untouched public file bytes.
        generation_status: Confirmed ``fully_ai`` or ``partially_ai`` value.

    Returns:
        Labelled file bytes in the same format as ``original``.

    Raises:
        UnsupportedImageError: The file cannot take a still-image icon.
        AIImageLabellingError: The official icon file failed its checksum.
    """
    with PILImage.open(io.BytesIO(original)) as opened:
        image_format = _require_supported(opened)
        oriented = ImageOps.exif_transpose(opened)
        base = oriented.convert("RGBA")

    stem = STATUS_ICON_STEM[generation_status]
    reference = _load_icon(f"{stem}-black.png")
    left, top, width, height = _icon_box(base.size, reference.size)
    background = _background_color(base, left, top, width, height)
    variant = _contrast_variant(background)
    icon = _load_icon(f"{stem}-{variant}.png").resize(
        (width, height),
        PILImage.Resampling.LANCZOS,
    )
    base.paste(icon, (left, top), icon)
    return _encode(base, image_format)


def _require_supported(image: PILImage.Image) -> str:
    """Reject animation and formats this profile does not embed.

    Args:
        image: Opened Pillow image.

    Returns:
        Pillow format name to use when saving.

    Raises:
        UnsupportedImageError: The image is animated or not JPEG, PNG, or WebP.
    """
    if getattr(image, "is_animated", False) or getattr(image, "n_frames", 1) > 1:
        raise UnsupportedImageError("animated images are out of scope")
    image_format = image.format or ""
    if image_format not in SUPPORTED_FORMATS:
        raise UnsupportedImageError(f"unsupported image format: {image_format}")
    return image_format


def _icon_box(image_size: tuple[int, int], icon_size: tuple[int, int]) -> tuple[int, int, int, int]:
    """Return the top-right destination box for the icon.

    Args:
        image_size: Width and height of the oriented image.
        icon_size: Width and height of the official icon.

    Returns:
        Left, top, width, and height of the icon box.

    Raises:
        UnsupportedImageError: The image cannot hold a visible icon and its padding.
    """
    image_width, image_height = image_size
    icon_width, icon_height = icon_size
    padding = max(MIN_PADDING_PX, round(min(image_width, image_height) * PADDING_RATIO))
    max_width = image_width - (padding * 2)
    max_height = image_height - (padding * 2)
    if max_width < MIN_ICON_BOX_PX or max_height < MIN_ICON_BOX_PX:
        raise UnsupportedImageError("image is too small for a visible icon")
    width = min(max_width, max(round(image_width * ICON_WIDTH_RATIO), 1))
    height = max(1, round(width * icon_height / icon_width))
    if height > max_height:
        height = max_height
        width = max(1, round(height * icon_width / icon_height))
    return image_width - padding - width, padding, width, height


def _background_color(
    image: PILImage.Image,
    left: int,
    top: int,
    width: int,
    height: int,
) -> tuple[int, int, int]:
    """Return the average colour of the rectangle the icon will cover.

    Args:
        image: Oriented image the icon will be pasted onto.
        left: Left edge of the icon box.
        top: Top edge of the icon box.
        width: Icon width.
        height: Icon height.

    Returns:
        Average red, green, and blue values.
    """
    sample = (
        image.convert("RGB")
        .crop((left, top, left + width, top + height))
        .resize((1, 1), PILImage.Resampling.BOX)
    )
    pixel = sample.getpixel((0, 0))
    return int(pixel[0]), int(pixel[1]), int(pixel[2])


def _contrast_variant(background: tuple[int, int, int]) -> str:
    """Choose the official black or white icon with the higher WCAG contrast.

    Args:
        background: Average colour behind the icon.

    Returns:
        ``black`` or ``white``.
    """
    luminance = _relative_luminance(background)
    black_contrast = _contrast_ratio(luminance, 0.0)
    white_contrast = _contrast_ratio(luminance, 1.0)
    if black_contrast >= white_contrast:
        return "black"
    return "white"


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    """Return the WCAG relative luminance of one colour.

    Args:
        rgb: Red, green, and blue channels from 0 to 255.

    Returns:
        Relative luminance from 0 to 1.
    """

    def channel(value: int) -> float:
        scaled = value / 255
        if scaled <= 0.04045:
            return scaled / 12.92
        return ((scaled + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(value) for value in rgb)
    return (0.2126 * red) + (0.7152 * green) + (0.0722 * blue)


def _contrast_ratio(first: float, second: float) -> float:
    """Return the WCAG contrast ratio of two relative-luminance values.

    Args:
        first: Relative luminance.
        second: Relative luminance.

    Returns:
        Contrast ratio from 1 to 21.
    """
    lighter = max(first, second)
    darker = min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def _load_icon(name: str) -> PILImage.Image:
    """Open one official PNG after checking its Commission checksum.

    Args:
        name: Filename inside the icon directory.

    Returns:
        A copy of the RGBA icon.

    Raises:
        AIImageLabellingError: The file is missing from the checksum list or was changed.
    """
    cached = _ICON_CACHE.get(name)
    if cached is not None:
        return cached.copy()
    expected = OFFICIAL_ICON_SHA256.get(name)
    if expected is None:
        raise AIImageLabellingError(f"official icon is not registered: {name}")
    data = (ICON_DIR / name).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected:
        raise AIImageLabellingError(f"official icon failed checksum: {name}")
    loaded = PILImage.open(io.BytesIO(data)).convert("RGBA")
    _ICON_CACHE[name] = loaded
    return loaded.copy()


def _encode(image: PILImage.Image, image_format: str) -> bytes:
    """Encode a labelled image in its original format.

    Args:
        image: Composited RGBA image.
        image_format: Pillow format name.

    Returns:
        Encoded file bytes.
    """
    buffer = io.BytesIO()
    if image_format == "JPEG":
        image.convert("RGB").save(buffer, format="JPEG", quality=95, optimize=True)
    elif image_format == "PNG":
        image.save(buffer, format="PNG")
    else:
        image.save(buffer, format="WEBP", quality=90)
    return buffer.getvalue()


def _archive_root() -> Path:
    """Return the private archive directory, creating it when needed.

    Returns:
        Path: Absolute archive root outside ``MEDIA_ROOT``.

    Raises:
        AIImageLabellingError: The archive is inside public media.
    """
    root = Path(settings.AI_IMAGE_ARCHIVE_ROOT).resolve()
    media_root = Path(settings.MEDIA_ROOT).resolve()
    if root == media_root or root.is_relative_to(media_root):
        raise AIImageLabellingError("pristine archive must stay outside MEDIA_ROOT")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _archive_pristine(image_id: int, digest: str, suffix: str, original: bytes) -> None:
    """Store the untouched file outside public media.

    Args:
        image_id: Wagtail image primary key.
        digest: SHA-256 of the untouched file.
        suffix: Original filename suffix, including the leading dot.
        original: Untouched file bytes.
    """
    destination = _archive_root() / str(image_id) / f"{digest}{suffix or '.bin'}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_bytes(original)
    temporary.replace(destination)


def _replace_public_file(path: Path, labelled: bytes) -> None:
    """Replace the public file only after the labelled bytes reopen as an image.

    Args:
        path: Public file path.
        labelled: Labelled file bytes.

    Raises:
        AIImageLabellingError: The labelled bytes are not a readable image.
    """
    temporary = path.with_name(f".{path.name}.ai-label")
    temporary.write_bytes(labelled)
    try:
        with PILImage.open(temporary) as checked:
            checked.load()
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _record_label(
    image: AbstractImage,
    disclosure: ImageAIDisclosure,
    labelled: bytes,
    labelled_hash: str,
) -> None:
    """Store the labelled checksum and refresh the Wagtail file metadata.

    Args:
        image: Wagtail image whose public file was just replaced.
        disclosure: Confirmed disclosure row.
        labelled: Labelled file bytes.
        labelled_hash: SHA-256 of those bytes.
    """
    with PILImage.open(io.BytesIO(labelled)) as stamped:
        image.width, image.height = stamped.size
    image.file_size = len(labelled)
    image.file_hash = hash_filelike(io.BytesIO(labelled))
    image.save(update_fields=["file_size", "width", "height", "file_hash"])
    disclosure.label_version = LABEL_VERSION
    disclosure.labelled_file_hash = labelled_hash
    disclosure.labelled_at = timezone.now()
    disclosure.save(update_fields=["label_version", "labelled_file_hash", "labelled_at"])


def _clear_renditions(image: AbstractImage) -> None:
    """Delete derived renditions so the next view rebuilds them from the labelled file.

    Args:
        image: Wagtail image that was just labelled.
    """
    for rendition in list(image.renditions.all()):
        rendition.file.delete(save=False)
        rendition.delete()
