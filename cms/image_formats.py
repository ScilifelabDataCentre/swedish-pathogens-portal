"""Wagtail rich-text image formats (captioned ``<figure>`` plus WebP rendition)."""

from django.forms.utils import flatatt
from django.template.loader import render_to_string
from wagtail.images.formats import Format, register_image_format
from wagtail.images.models import Image


class CaptionedImageFormat(Format):
    """Rich-text image format that wraps the rendition in ``<figure>`` / ``<figcaption>``.

    The visible caption reuses the alt text supplied in the editor, or falls back to
    the image title when alt text is empty. Behaviour is otherwise defined by the
    registered ``Format`` (name, label, filter spec, classname).
    """

    def image_to_html(
        self, image: Image, alt_text: str, extra_attributes: dict | None = None
    ) -> str:
        """Render HTML for this format using the shared captioned image template.

        Args:
            image (Image): The Wagtail image instance to render.
            alt_text (str): The alt text provided in the rich text editor.
                Used both as the ``alt`` attribute and as the caption.
                Falls back to the image title if empty.
            extra_attributes (dict | None, optional): Additional HTML
                attributes to include on the <img> element (e.g. data-*
                attributes, inline styles). Defaults to None.

        Returns:
            str: Rendered HTML string containing a <figure> element with
            an <img> and optional <figcaption>.
        """
        image_rendition = image.get_rendition(f"{self.filter_spec}|format-webp")
        if "float_left" in self.name:
            alignment_class = "float-left"
        elif "float_right" in self.name:
            alignment_class = "float-right"
        else:
            alignment_class = "float-none"

        context = {
            "image": image_rendition,
            "source_image": image,
            "alt_text": alt_text or getattr(image, "title", "") or "",
            "alignment_class": alignment_class,
            "classname": self.classname or "richtext-image",
            "extra_attributes_flat": flatatt(extra_attributes or {}),
        }
        return render_to_string("cms/components/rich_text_captioned_image.html", context=context)


register_image_format(
    CaptionedImageFormat(
        "captioned_full_width", "Captioned full width", "richtext-image", "original"
    )
)

register_image_format(
    CaptionedImageFormat(
        "captioned_float_left", "Captioned float left", "richtext-image", "original"
    )
)

register_image_format(
    CaptionedImageFormat(
        "captioned_float_right", "Captioned float right", "richtext-image", "original"
    )
)
