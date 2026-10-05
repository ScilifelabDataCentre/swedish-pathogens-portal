"""Accessible alt text for confirmed AI-generated images."""

from django import template
from django.core.exceptions import ObjectDoesNotExist

from cms.image_ai import GenerationStatus, ImageAIDisclosure

register = template.Library()

FULLY_AI_ALT_PREFIX = "AI-generated image:"
PARTIALLY_AI_ALT_PREFIX = "AI-modified image:"
_PREFIXES = (FULLY_AI_ALT_PREFIX, PARTIALLY_AI_ALT_PREFIX)


def _disclosure(image: object) -> ImageAIDisclosure | None:
    """Return a saved disclosure row, ignoring missing and stand-in objects."""
    try:
        disclosure = getattr(image, "ai_disclosure", None)
    except ObjectDoesNotExist:
        return None
    if not isinstance(disclosure, ImageAIDisclosure):
        return None
    return disclosure


def _prefix(disclosure: ImageAIDisclosure | None) -> str:
    """Return the alt prefix for a confirmed picture-like AI image."""
    if disclosure is None or not disclosure.is_ready_to_label:
        return ""
    if disclosure.generation_status == GenerationStatus.FULLY_AI:
        return FULLY_AI_ALT_PREFIX
    if disclosure.generation_status == GenerationStatus.PARTIALLY_AI:
        return PARTIALLY_AI_ALT_PREFIX
    return ""


def _file_name(image: object) -> str:
    """Return the image file's base name, which must not become alt text."""
    file = getattr(image, "file", None)
    name = str(getattr(file, "name", "") or "")
    return name.rsplit("/", 1)[-1]


def _semantic_text(image: object, fallback: str) -> str:
    """Prefer the image description, then the caller-supplied fallback."""
    description = getattr(image, "description", "") or ""
    description = str(description).strip()
    if description:
        return _without_prefix(description)
    if fallback and fallback != _file_name(image):
        return _without_prefix(fallback)
    return ""


def _without_prefix(text: str) -> str:
    """Remove a disclosure prefix so it is not applied twice."""
    stripped = text.strip()
    for prefix in _PREFIXES:
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip()
    return stripped


@register.simple_tag(takes_context=True, name="ai_card_alt")
def ai_card_alt(context: template.Context, fallback: str = "") -> str:
    """Return card alt text from an optional image without requiring every variable.

    ``firstof`` stringifies the image before a filter can read its disclosure,
    so the card calls this tag instead.

    Args:
        context: Template context. ``image`` may be empty, and ``image_alt`` overrides it.
        fallback: Alt text used when the image is not a confirmed AI picture.

    Returns:
        Alt text for the card image and its link name.
    """
    explicit = context.get("image_alt")
    if explicit:
        return str(explicit)
    return ai_image_alt(context.get("image"), fallback)


@register.simple_tag(takes_context=True, name="ai_card_icon_corner")
def ai_card_icon_corner(context: template.Context) -> bool:
    """Return whether a card should keep the embedded icon in frame.

    A confirmed picture-like AI image carries the EU icon in its top-right
    corner. The card stays the same height as other cards and crops from
    that corner. It does not add a second icon on top of the picture.

    Args:
        context: Template context. ``image`` may be empty.

    Returns:
        True for a confirmed picture-like AI image.
    """
    return ai_icon_corner(context.get("image"))


@register.filter(name="with_file_version")
def with_file_version(url: object, image: object) -> str:
    """Append the file checksum so a replaced image is not served from an old address.

    Rendition filenames stay the same when the source file changes. The checksum
    changes with the file, so the browser requests the new bytes.

    Args:
        url: Rendition or media address.
        image: Wagtail image whose ``file_hash`` versions that address.

    Returns:
        The address, with ``?v=`` added when both the address and checksum exist.
    """
    address = str(url or "")
    file_hash = str(getattr(image, "file_hash", "") or "")
    if not address or not file_hash:
        return address
    separator = "&" if "?" in address else "?"
    return f"{address}{separator}v={file_hash}"


@register.filter(name="ai_icon_corner")
def ai_icon_corner(image: object) -> bool:
    """Return whether a cropped image should keep its top-right corner.

    Args:
        image: Wagtail image, or anything that is not an image record.

    Returns:
        True for a confirmed picture-like AI image.
    """
    disclosure = _disclosure(image) if image is not None else None
    return bool(disclosure and disclosure.is_ready_to_label)


@register.filter(name="ai_image_alt")
def ai_image_alt(image: object, fallback: str = "") -> str:
    """Build alt text from a Wagtail image and a fallback description.

    Confirmed picture-like AI images are prefixed. Unreviewed suggestions,
    images that are not pictures, and images that are not AI keep the fallback
    exactly, so existing cards do not change. The file name is never used.

    Args:
        image: Wagtail image, or alt text that is already computed.
        fallback: Description used when the image has none, usually a title.

    Returns:
        Alt text for an ``img`` or ``og:image:alt``.
    """
    fallback_text = str(fallback or "").strip()
    if image is None or isinstance(image, str):
        return image if isinstance(image, str) and image else fallback_text

    disclosure = _disclosure(image)
    prefix = _prefix(disclosure)
    if not prefix:
        return fallback_text

    semantic = _semantic_text(image, fallback_text)
    if not semantic:
        return prefix
    return f"{prefix} {semantic}"
