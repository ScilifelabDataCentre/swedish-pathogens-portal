"""Tests for the PLP category snippet."""

from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import reverse
from wagtail.admin.panels import ObjectList
from wagtail.models import Page, Site
from wagtail.test.utils import WagtailTestUtils

from cms.pages import HomePage, PlpIndexPage, PlpProjectPage
from cms.snippets import PlpCategory
from cms.tests.utils import create_test_image


class PlpCategoryModelTests(TestCase):
    """Tests for the ``PlpCategory`` snippet model."""

    def test_slug_auto_generated_from_title(self) -> None:
        """An empty slug is filled in by ``save`` based on the title."""
        category = PlpCategory.objects.create(
            title="PLP Round One",
            slug="",
            group_label="Pandemic Laboratory Preparedness Capabilities round 1",
        )

        self.assertEqual(category.slug, "plp-round-one")

    def test_slug_preserved_when_provided(self) -> None:
        """An explicit slug is not overwritten by ``save``."""
        category = PlpCategory.objects.create(
            title="PLP Round Two",
            slug="custom-plp2",
            group_label="Pandemic Laboratory Preparedness Capabilities round 2 2022",
        )

        self.assertEqual(category.slug, "custom-plp2")

    def test_default_ordering_by_order_then_title(self) -> None:
        """Default queryset ordering is ``(order, title)``."""
        plp1 = PlpCategory.objects.create(
            title="PLP1",
            slug="plp1",
            group_label="Pandemic Laboratory Preparedness Capabilities round 1",
            order=2,
        )
        tdp = PlpCategory.objects.create(
            title="TDP",
            slug="tdp",
            group_label="Technology Development Projects",
            order=1,
        )
        plp2_alpha = PlpCategory.objects.create(
            title="Alpha",
            slug="alpha",
            group_label="Alpha group",
            order=2,
        )

        ordered = list(PlpCategory.objects.all())

        self.assertEqual(ordered, [tdp, plp2_alpha, plp1])

    def test_admin_form_accepts_blank_slug_and_save_generates_it(self) -> None:
        """Snippet model form validates with an empty slug; save stores a slug."""
        handler = ObjectList(PlpCategory.panels).bind_to_model(PlpCategory)
        form_class = handler.get_form_class()
        form = form_class(
            data={
                "title": "Admin Category",
                "slug": "",
                "group_label": "Public heading",
                "order": "0",
            }
        )

        self.assertTrue(form.is_valid(), msg=str(form.errors))
        instance = form.save()
        self.assertEqual(instance.slug, "admin-category")


class PlpCategoryChooserTests(WagtailTestUtils, TestCase):
    """Chooser modal wiring for ``PlpCategory`` (custom results + create link)."""

    def test_chooser_results_include_create_link_when_categories_exist(self) -> None:
        """Non-empty chooser listing still exposes the snippet add URL (regression: F-001)."""
        self.login()
        PlpCategory.objects.create(
            title="Existing category",
            slug="existing-category",
            group_label="Public heading",
            order=1,
        )
        chooser_viewset = PlpCategory.snippet_viewset.chooser_viewset
        results_url = reverse(chooser_viewset.get_url_name("choose_results"))
        response = self.client.get(results_url)

        self.assertEqual(response.status_code, 200)
        add_url = reverse(PlpCategory.snippet_viewset.get_url_name("add"))
        self.assertContains(response, add_url)


class PlpCategoryProtectOnDeleteTests(TestCase):
    """``PlpCategory`` is referenced by ``PlpProjectPage.category`` with PROTECT."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Build a minimal site tree with one PLP project referencing a category."""
        root = Page.get_first_root_node()
        for child in root.get_children():
            child.delete()
        root = Page.get_first_root_node()
        cls.home = HomePage(title="Home", slug="home")
        root.add_child(instance=cls.home)
        Site.objects.update_or_create(
            is_default_site=True,
            defaults={"hostname": "testserver", "root_page": cls.home},
        )

        cls.index = PlpIndexPage(title="PLP Program", slug="plp-program")
        cls.home.add_child(instance=cls.index)
        cls.index.save_revision().publish()

        cls.category = PlpCategory.objects.create(
            title="PLP1",
            slug="plp1",
            group_label="Pandemic Laboratory Preparedness Capabilities round 1",
            order=1,
        )

        image = create_test_image(title="Test image", file_name="test.jpg")
        cls.project = PlpProjectPage(
            title="BSL3 Capability",
            slug="bsl3",
            image=image,
            category=cls.category,
        )
        cls.index.add_child(instance=cls.project)
        cls.project.save_revision().publish()

    def test_delete_referenced_category_raises_protected_error(self) -> None:
        """Deleting a category that a project FKs to must raise ``ProtectedError``."""
        with self.assertRaises(ProtectedError):
            self.category.delete()

        self.assertTrue(PlpCategory.objects.filter(pk=self.category.pk).exists())
