"""Tests for AI image alt text."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.utils import timezone
from wagtail.images import get_image_model

from cms.blocks.static_figure import StaticFigureBlock
from cms.image_ai import GenerationStatus, ImageAIDisclosure, PictureLike
from cms.pages import NewsPage
from cms.templatetags.ai_images import FULLY_AI_ALT_PREFIX, ai_image_alt, with_file_version
from cms.tests.pages.test_news_pages import BasePageTestCase
from cms.tests.utils import create_test_image, use_temp_media_root


def confirmed(status: str, picture: str = PictureLike.YES) -> ImageAIDisclosure:
    """Return an unsaved disclosure that counts as reviewed."""
    return ImageAIDisclosure(
        generation_status=status,
        picture_like=picture,
        reviewed_by_id=1,
        reviewed_at=datetime(2026, 9, 29, tzinfo=UTC),
    )


class TestAIImageAlt(SimpleTestCase):
    """Rules for the alt-text helper."""

    def test_fully_ai_uses_the_description(self):
        """A confirmed fully AI picture is prefixed with its description."""
        image = SimpleNamespace(
            description="An elderly person inside a protective dome",
            ai_disclosure=confirmed(GenerationStatus.FULLY_AI),
        )

        self.assertEqual(
            ai_image_alt(image, "Page title"),
            "AI-generated image: An elderly person inside a protective dome",
        )

    def test_partially_ai_uses_a_different_prefix(self):
        """A confirmed partial AI picture uses the modified-image prefix."""
        image = SimpleNamespace(
            description="",
            ai_disclosure=confirmed(GenerationStatus.PARTIALLY_AI),
        )

        self.assertEqual(
            ai_image_alt(image, "A chart with an added marker"),
            "AI-modified image: A chart with an added marker",
        )

    def test_unreviewed_suggestion_keeps_the_fallback(self):
        """A seeded suggestion is not announced until an editor confirms it."""
        image = SimpleNamespace(
            description="Suggested picture",
            ai_disclosure=ImageAIDisclosure(
                generation_status=GenerationStatus.FULLY_AI,
                picture_like=PictureLike.YES,
            ),
        )

        self.assertEqual(ai_image_alt(image, "Säbo"), "Säbo")

    def test_non_picture_and_not_ai_keep_the_fallback(self):
        """Out-of-scope images keep the alt text the template already used."""
        logo = SimpleNamespace(
            description="Portal logo",
            ai_disclosure=confirmed(GenerationStatus.FULLY_AI, PictureLike.NO),
        )
        photo = SimpleNamespace(
            description="A laboratory",
            ai_disclosure=confirmed(GenerationStatus.NOT_AI),
        )

        self.assertEqual(ai_image_alt(logo, "Logo card"), "Logo card")
        self.assertEqual(ai_image_alt(photo, "Photo card"), "Photo card")
        self.assertEqual(ai_image_alt(SimpleNamespace(), "Plain card"), "Plain card")

    def test_does_not_use_the_file_name_or_repeat_the_prefix(self):
        """Empty descriptions stay empty of file names, and prefixes are not doubled."""
        image = SimpleNamespace(
            description="",
            file=SimpleNamespace(name="original_images/photo.jpg"),
            ai_disclosure=confirmed(GenerationStatus.FULLY_AI),
        )
        already = SimpleNamespace(
            description=f"{FULLY_AI_ALT_PREFIX} A dome",
            ai_disclosure=confirmed(GenerationStatus.FULLY_AI),
        )

        self.assertEqual(ai_image_alt(image, ""), FULLY_AI_ALT_PREFIX)
        self.assertEqual(ai_image_alt(image, "photo.jpg"), FULLY_AI_ALT_PREFIX)
        self.assertEqual(ai_image_alt(already, "Fallback"), f"{FULLY_AI_ALT_PREFIX} A dome")
        self.assertEqual(
            ai_image_alt("AI-modified image: Kept", "Ignored"),
            "AI-modified image: Kept",
        )
        self.assertEqual(ai_image_alt(None, "Fallback"), "Fallback")
        self.assertEqual(ai_image_alt("", "Fallback"), "Fallback")


class TestFileVersion(SimpleTestCase):
    """The rendition address changes when the source checksum changes."""

    def test_checksum_is_added_once(self):
        """A plain address gains the checksum, and an addressed one keeps its query."""
        image = SimpleNamespace(file_hash="abc123")

        self.assertEqual(
            with_file_version("/media/images/photo.format-webp.webp", image),
            "/media/images/photo.format-webp.webp?v=abc123",
        )
        self.assertEqual(
            with_file_version("/media/images/photo.webp?width=10", image),
            "/media/images/photo.webp?width=10&v=abc123",
        )
        self.assertEqual(
            with_file_version("/media/images/photo.webp", None),
            "/media/images/photo.webp",
        )


class TestAIImageAltTemplates(BasePageTestCase):
    """Rendered card, detail, social, and static-figure alt text."""

    def setUp(self):
        """Keep generated files out of the development media directory."""
        super().setUp()
        use_temp_media_root(self)
        # The rendition cache outlives the test transaction, and SQLite reuses
        # image ids, so a later test can be served an earlier image's file.
        get_image_model().get_rendition_model().cache_backend.clear()
        self.reviewer = get_user_model().objects.create(username="alt-reviewer")

    def _confirm(self, image: object, status: str) -> None:
        ImageAIDisclosure.objects.create(
            image=image,
            generation_status=status,
            picture_like=PictureLike.YES,
            reviewed_by=self.reviewer,
            reviewed_at=timezone.now(),
        )

    def test_card_announces_a_confirmed_ai_image(self):
        """The card announces the image and does not add a separate icon."""
        image = create_test_image(title="Dome image", file_name="dome-card.jpg")
        image.description = "An elderly person inside a protective dome"
        image.file_hash = "abc123"
        image.save(update_fields=["description", "file_hash"])
        self._confirm(image, GenerationStatus.FULLY_AI)

        html = render_to_string(
            "cms/components/content_card.html#content_card",
            {
                "url": "/dome/",
                "image": image,
                "title": "Dome study",
                "description": "Card text",
            },
        )

        self.assertIn(
            'alt="AI-generated image: An elderly person inside a protective dome"',
            html,
        )
        label = "AI-generated image: An elderly person inside a protective dome. Dome study"
        self.assertIn(f'aria-label="{label}"', html)
        stem = Path(image.file.name).stem
        self.assertIn(f"{stem}.format-webp.webp?v=abc123", html)
        self.assertNotIn("ai_labels", html)
        self.assertIn("w-full h-40 object-cover object-right-top origin-top-right", html)
        self.assertIn("group-hover:scale-105", html)

    def test_card_without_ai_keeps_the_title(self):
        """A normal card still uses the title as its image alt."""
        image = create_test_image(title="Plain image", file_name="plain-card.jpg")

        html = render_to_string(
            "cms/components/content_card.html#content_card",
            {
                "url": "/plain/",
                "image": image,
                "title": "Plain study",
                "description": "Card text",
            },
        )

        self.assertIn('alt="Plain study"', html)
        self.assertIn('aria-label="Plain study"', html)
        stem = Path(image.file.name).stem
        self.assertIn(f"{stem}.format-webp.webp", html)
        self.assertNotIn("AI-generated image:", html)
        self.assertIn("object-cover", html)
        self.assertIn("group-hover:scale-105", html)
        self.assertNotIn("object-right-top", html)

        empty = render_to_string(
            "cms/components/content_card.html#content_card",
            {
                "url": "/empty/",
                "image": "",
                "title": "Empty study",
                "description": "Card text",
            },
        )
        self.assertNotIn("<img", empty)

    def test_news_detail_card_and_social_alt(self):
        """A published news page discloses a confirmed AI image in every alt."""
        image = create_test_image(title="Dome image", file_name="dome.jpg")
        image.description = "An elderly person inside a protective dome"
        image.file_hash = "abc123"
        image.save(update_fields=["description", "file_hash"])
        self._confirm(image, GenerationStatus.FULLY_AI)
        news = NewsPage(
            title="Dome study",
            slug="dome-study",
            description="Card text",
            image=image,
        )
        self.news_index.add_child(instance=news)
        news.save_revision().publish()

        detail = self.client.get(news.url)
        listing = self.client.get(self.news_index.url)
        expected = "AI-generated image: An elderly person inside a protective dome"

        self.assertContains(detail, f'alt="{expected}"')
        self.assertContains(detail, "object-right-top")
        self.assertContains(detail, "?v=abc123")
        self.assertContains(detail, f'property="og:image:alt" content="{expected}"')
        self.assertContains(listing, f'alt="{expected}"')

    def test_news_without_confirmation_keeps_the_title(self):
        """An ordinary news image keeps the page title as its alt text."""
        image = create_test_image(title="Lab image", file_name="lab.jpg")
        news = NewsPage(
            title="Lab study",
            slug="lab-study",
            description="Card text",
            image=image,
        )
        self.news_index.add_child(instance=news)
        news.save_revision().publish()

        detail = self.client.get(news.url)

        self.assertContains(detail, 'alt="Lab study"')
        self.assertNotContains(detail, "object-right-top")
        self.assertNotContains(detail, "AI-generated image:")
        self.assertNotContains(detail, "AI-modified image:")

    def test_static_figure_prefixes_a_managed_image(self):
        """A static figure uses the helper for a Wagtail image and not for a URL."""
        image = create_test_image(title="Figure image", file_name="figure.jpg")
        image.description = "A pathogen under glass"
        image.save(update_fields=["description"])
        self._confirm(image, GenerationStatus.PARTIALLY_AI)
        block = StaticFigureBlock()
        value = block.to_python(
            {
                "image": image.pk,
                "alt_text": "Editor description",
                "caption": "Figure 1",
            }
        )

        html = block.render(value)

        self.assertIn("AI-modified image: A pathogen under glass", html)
        self.assertIn("Figure 1", html)

        external = block.to_python(
            {
                "image_url": "https://example.com/chart.svg",
                "alt_text": "External chart",
            }
        )
        external_html = block.render(external)
        self.assertIn('alt="External chart"', external_html)
        self.assertNotIn("AI-modified image:", external_html)
