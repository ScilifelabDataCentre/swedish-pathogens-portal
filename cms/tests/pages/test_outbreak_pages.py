"""Tests for outbreak pages."""

from wagtail.models import Page, Site
from wagtail.test.utils import WagtailPageTestCase

from cms.pages import HomePage, OutbreakPage, OutbreaksIndexPage
from cms.tests.utils import create_test_image

#######################################################################
############# Helper classes and functions for testing ################
#######################################################################


class BasePageTestCase(WagtailPageTestCase):
    """Base test case for page tests, providing common setup and utilities."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a site setup with a home page and a outbreaks index page for testing."""

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

        cls.outbreaks_index = OutbreaksIndexPage(title="Outbreaks", slug="outbreaks")
        cls.home.add_child(instance=cls.outbreaks_index)
        cls.outbreaks_index.save_revision().publish()


######################################################################
############## Test suite for OutbreaksIndexPage model ###############
######################################################################


class TestOutbreaksIndexPage(BasePageTestCase):
    """Tests for the OutbreaksIndexPage model."""

    def test_max_count_set_on_model(self):
        """Test that only one instance of OutbreaksIndexPage can be created."""
        self.assertEqual(OutbreaksIndexPage.max_count, 1)

    def test_parent_page_type_restriction(self):
        """Test that only HomePage can be a parent of OutbreaksIndexPage."""
        self.assertEqual(OutbreaksIndexPage.parent_page_types, ["cms.HomePage"])

    def test_subpage_type_restriction(self):
        """Test that only OutbreakPage can be added as a child of OutbreaksIndexPage."""
        self.assertEqual(OutbreaksIndexPage.subpage_types, ["cms.OutbreakPage"])

    def test_get_context_includes_ongoing_outbreaks(self):
        """Test that the get_context method includes ongoing OutbreakPage instances."""
        image1 = create_test_image(title="Image 1", file_name="image1.jpg")
        outbreak1 = OutbreakPage(
            title="Outbreak 1",
            slug="outbreak-1",
            description="Description 1",
            image=image1,
            status="ongoing",
        )
        self.outbreaks_index.add_child(instance=outbreak1)
        outbreak1.save_revision().publish()

        request = self.client.get(self.outbreaks_index.url).wsgi_request
        context = self.outbreaks_index.get_context(request)

        self.assertIn("outbreaks", context)
        self.assertIn("ongoing", context["outbreaks"])
        self.assertNotIn("historical", context["outbreaks"])
        self.assertEqual(len(context["outbreaks"]["ongoing"]), 1)
        self.assertTrue(all(isinstance(o, OutbreakPage) for o in context["outbreaks"]["ongoing"]))
        self.assertEqual(context["outbreaks"]["ongoing"][0].title, "Outbreak 1")

    def test_get_context_includes_historical_outbreaks(self):
        """Test that the get_context method includes historical OutbreakPage instances."""
        image1 = create_test_image(title="Image 1", file_name="image1.jpg")
        outbreak1 = OutbreakPage(
            title="Outbreak 1",
            slug="outbreak-1",
            description="Description 1",
            image=image1,
            status="historical",
        )
        self.outbreaks_index.add_child(instance=outbreak1)
        outbreak1.save_revision().publish()

        request = self.client.get(self.outbreaks_index.url).wsgi_request
        context = self.outbreaks_index.get_context(request)

        self.assertIn("outbreaks", context)
        self.assertIn("historical", context["outbreaks"])
        self.assertNotIn("ongoing", context["outbreaks"])
        self.assertEqual(len(context["outbreaks"]["historical"]), 1)
        self.assertTrue(
            all(isinstance(o, OutbreakPage) for o in context["outbreaks"]["historical"])
        )
        self.assertEqual(context["outbreaks"]["historical"][0].title, "Outbreak 1")


######################################################################
################# Test suite for OutbreakPage model ##################
######################################################################


class TestOutbreakPage(BasePageTestCase):
    """Tests for the OutbreakPage model."""

    def test_parent_page_type_restriction(self):
        """Test that only OutbreaksIndexPage can be a parent of OutbreakPage."""
        self.assertEqual(OutbreakPage.parent_page_types, ["cms.OutbreaksIndexPage"])

    def test_subpage_type_restriction(self):
        """Test that OutbreakPage cannot have any child pages."""
        self.assertEqual(OutbreakPage.subpage_types, [])

    def test_image_field_is_required_by_model_constraint(self):
        """Test that the image field is required based on the model definition."""
        field = OutbreakPage._meta.get_field("image")
        self.assertFalse(field.blank)

    def test_description_is_required_by_model_constraint(self):
        """Test that the description field is required based on the model definition."""
        field = OutbreakPage._meta.get_field("description")
        self.assertFalse(field.blank)

    def test_status_field_is_required_by_model_constraint(self):
        """Test that the status field is required based on the model definition."""
        field = OutbreakPage._meta.get_field("status")
        self.assertFalse(field.blank)

    def test_status_field_has_correct_choices(self):
        """Test that the status field has the correct choices defined."""
        field = OutbreakPage._meta.get_field("status")
        expected_choices = [("ongoing", "Ongoing"), ("historical", "Historical")]
        self.assertEqual(field.choices, expected_choices)

    def test_status_field_has_correct_default(self):
        """Test that the status field has the correct default value."""
        field = OutbreakPage._meta.get_field("status")
        self.assertEqual(field.default, "ongoing")

    def test_outbreak_page_can_be_created_under_index(self):
        """Test that an OutbreakPage can be created under an OutbreaksIndexPage."""
        image = create_test_image(title="Test Image", file_name="test_image.jpg")
        outbreak_page = OutbreakPage(
            title="Test Outbreak",
            slug="test-outbreak",
            description="A test outbreak page.",
            image=image,
        )
        self.outbreaks_index.add_child(instance=outbreak_page)
        outbreak_page.save_revision().publish()

        self.assertTrue(OutbreakPage.objects.filter(id=outbreak_page.id).exists())
        self.assertEqual(outbreak_page.get_parent().specific, self.outbreaks_index)
