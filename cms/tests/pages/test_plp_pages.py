"""Page-tree tests for the PLP section.

Mirrors :mod:`cms.tests.test_outbreak_pages` (``WagtailPageTestCase`` +
``BasePageTestCase``) and exercises the spec's Done-When gates that live on
the page layer:

* tree shape (``max_count`` / ``parent_page_types`` / ``subpage_types``)
* index ``get_context`` grouping/ordering and subproject exclusion
* project ``get_context`` subproject surfacing + back-link metadata
* depth-1 invariant on the create path (``can_create_at``)
* depth-1 + category invariant on the move path (``can_move_to``)
* category-required-for-top-level via the admin form path (form class
  returned by ``PlpProjectPage.get_edit_handler().get_form_class()`` and a
  live POST to ``wagtailadmin_pages:add`` via ``WagtailPageTestCase.client``)
"""

from typing import Any

from django.contrib.auth.base_user import AbstractBaseUser
from django.http import HttpResponse
from django.urls import reverse
from wagtail.models import Page, Site
from wagtail.test.utils import WagtailPageTestCase
from wagtail.test.utils.form_data import nested_form_data, streamfield

from cms.forms import PlpProjectPageCopyForm, PlpProjectPageForm
from cms.pages import HomePage, PlpIndexPage, PlpProjectPage
from cms.snippets import PlpCategory
from cms.tests.utils import create_test_image

#######################################################################
##################### Form-data helper for tests ######################
#######################################################################


def _empty_admin_post_data() -> dict[str, str]:
    """Build a sparsely populated admin POST body with a parseable StreamField.

    The Wagtail admin form widget for ``StreamField`` reads ``content-count``
    from the POST data; a missing key raises ``KeyError`` before any form
    validation runs. Submitting ``content`` as an empty stream is enough to
    let the form bind and surface field-level errors on ``category`` (the
    only field these tests care about). Other required fields (image,
    publish-time slug uniqueness, …) may still produce errors — that's fine,
    the assertions check ``"category"`` membership only.
    """
    return {
        "title": "Probe",
        "slug": "probe",
        "category": "",
        **nested_form_data({"content": streamfield([])}),
    }


#######################################################################
############# Helper classes and functions for testing ################
#######################################################################


class BasePlpPageTestCase(WagtailPageTestCase):
    """Build a minimal site tree shared by every PLP page-tree test."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create ``HomePage`` -> ``PlpIndexPage`` plus a couple of categories."""
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

        cls.category_first = PlpCategory.objects.create(
            title="PLP1",
            slug="plp1",
            group_label="Pandemic Laboratory Preparedness Capabilities round 1",
            order=1,
        )
        cls.category_second = PlpCategory.objects.create(
            title="TDP",
            slug="tdp",
            group_label="Technology Development Projects",
            order=2,
        )

        cls.image_a = create_test_image(title="Image A", file_name="a.jpg")
        cls.image_b = create_test_image(title="Image B", file_name="b.jpg")
        cls.image_c = create_test_image(title="Image C", file_name="c.jpg")


######################################################################
############### Test suite for PlpIndexPage tree shape ###############
######################################################################


class TestPlpIndexPageTreeShape(BasePlpPageTestCase):
    """Tree-shape constraints on :class:`PlpIndexPage`."""

    def test_max_count(self):
        """Only one ``PlpIndexPage`` can exist site-wide."""
        self.assertEqual(PlpIndexPage.max_count, 1)

    def test_parent_page_types(self):
        """``PlpIndexPage`` lives directly under ``HomePage``."""
        self.assertEqual(PlpIndexPage.parent_page_types, ["cms.HomePage"])

    def test_subpage_types(self):
        """Only ``PlpProjectPage`` can be added under the index."""
        self.assertEqual(PlpIndexPage.subpage_types, ["cms.PlpProjectPage"])


######################################################################
############### Test suite for PlpProjectPage tree shape #############
######################################################################


class TestPlpProjectPageTreeShape(BasePlpPageTestCase):
    """Tree-shape constraints on :class:`PlpProjectPage`."""

    def test_parent_page_types(self):
        """Projects can be created under the index or another project (subproject)."""
        self.assertEqual(
            PlpProjectPage.parent_page_types,
            ["cms.PlpIndexPage", "cms.PlpProjectPage"],
        )

    def test_subpage_types(self):
        """Self-nesting allows the depth-1 subproject layer."""
        self.assertEqual(PlpProjectPage.subpage_types, ["cms.PlpProjectPage"])


######################################################################
########## Test suite for PlpIndexPage.get_context grouping ##########
######################################################################


class TestPlpIndexCategoryGrouping(BasePlpPageTestCase):
    """``get_context`` groups projects by category and preserves admin tree order."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Add three top-level projects across two categories plus one subproject."""
        super().setUpTestData()

        cls.beta_tdp = PlpProjectPage(
            title="Beta TDP",
            slug="beta-tdp",
            image=cls.image_a,
            category=cls.category_second,
        )
        cls.index.add_child(instance=cls.beta_tdp)
        cls.beta_tdp.save_revision().publish()

        cls.alpha_plp = PlpProjectPage(
            title="Alpha PLP",
            slug="alpha-plp",
            image=cls.image_b,
            category=cls.category_first,
        )
        cls.index.add_child(instance=cls.alpha_plp)
        cls.alpha_plp.save_revision().publish()

        cls.charlie_plp = PlpProjectPage(
            title="Charlie PLP",
            slug="charlie-plp",
            image=cls.image_c,
            category=cls.category_first,
        )
        cls.index.add_child(instance=cls.charlie_plp)
        cls.charlie_plp.save_revision().publish()

        cls.alpha_sub = PlpProjectPage(
            title="Alpha Sub",
            slug="alpha-sub",
            image=cls.image_a,
            category=None,
        )
        cls.alpha_plp.add_child(instance=cls.alpha_sub)
        cls.alpha_sub.save_revision().publish()

    def _category_groups(self) -> list[dict]:
        """Render the index and return the ``category_groups`` list from context."""
        request = self.client.get(self.index.url).wsgi_request
        return self.index.get_context(request)["category_groups"]

    def test_category_groups_sorted_by_order_then_title(self):
        """Groups iterate in ``PlpCategory.Meta.ordering`` (``order``, ``title``)."""
        labels = [group["label"] for group in self._category_groups()]

        self.assertEqual(
            labels,
            [
                self.category_first.group_label,
                self.category_second.group_label,
            ],
        )

    def test_intra_category_uses_wagtail_tree_order(self):
        """Within a category, projects appear in Wagtail child-page tree order."""
        groups = {group["value"]: group for group in self._category_groups()}
        plp1 = groups[self.category_first.slug]

        titles = [project.title for project in plp1["projects"]]

        self.assertEqual(titles, ["Alpha PLP", "Charlie PLP"])

    def test_subprojects_excluded_from_index(self):
        """Subprojects (children of another project) are never listed on the index."""
        all_titles = [
            project.title for group in self._category_groups() for project in group["projects"]
        ]

        self.assertNotIn("Alpha Sub", all_titles)

    def test_empty_category_section_omitted(self):
        """Categories with no live top-level projects are not emitted."""
        empty_category = PlpCategory.objects.create(
            title="Empty",
            slug="empty",
            group_label="Empty group",
            order=99,
        )

        slugs = [group["value"] for group in self._category_groups()]

        self.assertNotIn(empty_category.slug, slugs)


######################################################################
########### Test suite for PlpProjectPage.get_context detail #########
######################################################################


class TestPlpProjectSubprojectSurfacing(BasePlpPageTestCase):
    """Project detail context surfaces subprojects and back-link metadata."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Add one parent project with two subprojects plus a lonely sibling."""
        super().setUpTestData()

        cls.parent_project = PlpProjectPage(
            title="BSL3",
            slug="bsl3",
            image=cls.image_a,
            category=cls.category_first,
        )
        cls.index.add_child(instance=cls.parent_project)
        cls.parent_project.save_revision().publish()

        cls.sub_a = PlpProjectPage(
            title="BSL3 Facility",
            slug="bsl3-facility",
            image=cls.image_b,
            category=None,
        )
        cls.parent_project.add_child(instance=cls.sub_a)
        cls.sub_a.save_revision().publish()

        cls.sub_b = PlpProjectPage(
            title="BSL3 Network",
            slug="bsl3-network",
            image=cls.image_c,
            category=None,
        )
        cls.parent_project.add_child(instance=cls.sub_b)
        cls.sub_b.save_revision().publish()

        cls.lonely_project = PlpProjectPage(
            title="Lonely",
            slug="lonely",
            image=cls.image_a,
            category=cls.category_first,
        )
        cls.index.add_child(instance=cls.lonely_project)
        cls.lonely_project.save_revision().publish()

    def _context_for(self, page: PlpProjectPage) -> dict:
        """Render ``page`` and return its template context."""
        request = self.client.get(page.url).wsgi_request
        return page.get_context(request)

    def test_subprojects_present_on_parent_detail(self):
        """The parent's context exposes its child projects."""
        context = self._context_for(self.parent_project)

        titles = sorted(child.title for child in context["subprojects"])

        self.assertEqual(titles, ["BSL3 Facility", "BSL3 Network"])

    def test_top_level_project_back_link_targets_index(self):
        """A top-level project is rendered with the ``parent_is_index`` flag set."""
        context = self._context_for(self.parent_project)

        self.assertTrue(context["parent_is_index"])
        self.assertEqual(context["parent_title"], self.index.title)

    def test_subprojects_absent_when_no_children(self):
        """Lonely top-level projects emit an empty ``subprojects`` queryset."""
        context = self._context_for(self.lonely_project)

        self.assertFalse(list(context["subprojects"]))

    def test_subproject_back_link_uses_parent_project_title(self):
        """A subproject's context surfaces its non-index parent project."""
        context = self._context_for(self.sub_a)

        self.assertFalse(context["parent_is_index"])
        self.assertEqual(context["parent_title"], self.parent_project.title)

    def test_detail_template_renders_and_omits_subprojects_section(self):
        """HTML shows Subprojects only when child projects exist."""
        parent_response = self.client.get(self.parent_project.url)
        self.assertEqual(parent_response.status_code, 200)
        self.assertContains(parent_response, "Subprojects")
        self.assertContains(parent_response, "BSL3 Facility")
        self.assertContains(parent_response, "BSL3 Network")

        lonely_response = self.client.get(self.lonely_project.url)
        self.assertEqual(lonely_response.status_code, 200)
        self.assertNotContains(lonely_response, "Subprojects")


######################################################################
############ Test suite for PlpProjectPage banner heading ############
######################################################################


class TestPlpProjectPageHeading(BasePlpPageTestCase):
    """Published project HTML uses the PLP index title in the banner and page title in-body."""

    @classmethod
    def setUpTestData(cls) -> None:
        """One top-level project and one subproject under it."""
        super().setUpTestData()

        cls.parent_project = PlpProjectPage(
            title="BSL3",
            slug="bsl3",
            image=cls.image_a,
            category=cls.category_first,
        )
        cls.index.add_child(instance=cls.parent_project)
        cls.parent_project.save_revision().publish()

        cls.subproject = PlpProjectPage(
            title="BSL3 Facility",
            slug="bsl3-facility",
            image=cls.image_b,
            category=None,
        )
        cls.parent_project.add_child(instance=cls.subproject)
        cls.subproject.save_revision().publish()

    def test_top_level_project_banner_and_body_titles(self):
        """Banner ``h2`` shows the program index title; body ``h3`` shows the project."""
        response = self.client.get(self.parent_project.url)

        self.assertEqual(response.status_code, 200)
        banner_heading = f'<h2 class="my-4">{self.index.title}</h2>'
        self.assertContains(response, banner_heading, html=True)
        self.assertContains(response, "<h3>BSL3</h3>", html=True)

    def test_subproject_banner_and_body_titles(self):
        """Subprojects resolve the same PLP index ancestor for the banner."""
        response = self.client.get(self.subproject.url)

        self.assertEqual(response.status_code, 200)
        banner_heading = f'<h2 class="my-4">{self.index.title}</h2>'
        self.assertContains(response, banner_heading, html=True)
        self.assertContains(response, "<h3>BSL3 Facility</h3>", html=True)


######################################################################
######### Test suite for PlpProjectPage.can_create_at gate ###########
######################################################################


class TestPlpProjectCanCreateAt(BasePlpPageTestCase):
    """Depth-1 invariant on the admin "Add child page" path."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one top-level project with one subproject for the depth-1 cases."""
        super().setUpTestData()

        cls.toplevel = PlpProjectPage(
            title="Top",
            slug="top",
            image=cls.image_a,
            category=cls.category_first,
        )
        cls.index.add_child(instance=cls.toplevel)
        cls.toplevel.save_revision().publish()

        cls.subproject = PlpProjectPage(
            title="Sub",
            slug="sub",
            image=cls.image_b,
            category=None,
        )
        cls.toplevel.add_child(instance=cls.subproject)
        cls.subproject.save_revision().publish()

    def test_can_create_under_index(self):
        """Top-level projects can be created under the index."""
        self.assertTrue(PlpProjectPage.can_create_at(self.index))

    def test_can_create_subproject_under_top_level(self):
        """Subprojects can be created under a top-level project (depth-1 allowed)."""
        self.assertTrue(PlpProjectPage.can_create_at(self.toplevel))

    def test_cannot_create_under_subproject(self):
        """Sub-subprojects cannot be created (depth-1 rejected)."""
        self.assertFalse(PlpProjectPage.can_create_at(self.subproject))


######################################################################
########## Test suite for PlpProjectPage.can_move_to gate ############
######################################################################


class TestPlpProjectCanMoveTo(BasePlpPageTestCase):
    """Depth-1 + category-invariant rules on the admin "Move" path."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Two top-level projects, a subproject, and a parent owning subprojects."""
        super().setUpTestData()

        cls.toplevel_a = PlpProjectPage(
            title="A",
            slug="a",
            image=cls.image_a,
            category=cls.category_first,
        )
        cls.index.add_child(instance=cls.toplevel_a)
        cls.toplevel_a.save_revision().publish()

        cls.toplevel_b = PlpProjectPage(
            title="B",
            slug="b",
            image=cls.image_b,
            category=cls.category_first,
        )
        cls.index.add_child(instance=cls.toplevel_b)
        cls.toplevel_b.save_revision().publish()

        cls.subproject_under_b = PlpProjectPage(
            title="B Sub",
            slug="b-sub",
            image=cls.image_c,
            category=None,
        )
        cls.toplevel_b.add_child(instance=cls.subproject_under_b)
        cls.subproject_under_b.save_revision().publish()

        cls.toplevel_c = PlpProjectPage(
            title="C",
            slug="c",
            image=cls.image_a,
            category=cls.category_first,
        )
        cls.index.add_child(instance=cls.toplevel_c)
        cls.toplevel_c.save_revision().publish()

        cls.c_sub = PlpProjectPage(
            title="C Sub",
            slug="c-sub",
            image=cls.image_b,
            category=None,
        )
        cls.toplevel_c.add_child(instance=cls.c_sub)
        cls.c_sub.save_revision().publish()

    def test_cannot_move_under_subproject(self):
        """Destination is itself a subproject: would create depth-3."""
        self.assertFalse(self.toplevel_a.can_move_to(self.subproject_under_b))

    def test_cannot_move_project_with_subprojects_under_top_level(self):
        """Moving a project that owns subprojects under another top-level: depth-3."""
        self.assertFalse(self.toplevel_c.can_move_to(self.toplevel_a))

    def test_can_move_under_index(self):
        """A categorised, child-less top-level project can move under the index."""
        self.assertTrue(self.toplevel_a.can_move_to(self.index))

    def test_cannot_promote_category_less_subproject_under_index(self):
        """``can_move_to(PlpIndexPage)`` rejects a subproject saved with no category."""
        self.assertIsNone(self.subproject_under_b.category_id)

        self.assertFalse(self.subproject_under_b.can_move_to(self.index))

    def test_can_promote_subproject_once_category_set(self):
        """The same move is allowed once the editor sets ``category`` and saves."""
        self.subproject_under_b.category = self.category_first
        self.subproject_under_b.save()

        self.assertTrue(self.subproject_under_b.can_move_to(self.index))


######################################################################
##### Test suite for PlpProjectPageForm category-required rule ######
######################################################################


class TestPlpProjectFormCategoryRequired(BasePlpPageTestCase):
    """``PlpProjectPageForm`` enforces category-required-for-top-level only.

    Both the form class returned by ``get_edit_handler().get_form_class()`` and
    a live ``wagtailadmin_pages:add`` POST via ``WagtailPageTestCase.client``
    are exercised, mirroring the spec's two-pronged ask.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Add a top-level project so we can target it as a subproject parent."""
        super().setUpTestData()

        cls.toplevel = PlpProjectPage(
            title="Top",
            slug="top",
            image=cls.image_a,
            category=cls.category_first,
        )
        cls.index.add_child(instance=cls.toplevel)
        cls.toplevel.save_revision().publish()

    def _bind_form(self, parent: Page) -> PlpProjectPageForm:
        """Bind the live admin form class with empty data and the given parent."""
        form_class = PlpProjectPage.get_edit_handler().get_form_class()
        return form_class(
            data=_empty_admin_post_data(),
            instance=PlpProjectPage(),
            parent_page=parent,
        )

    def test_form_class_is_plp_project_page_form_subclass(self):
        """``base_form_class`` is honoured by the edit handler's generated class."""
        form_class = PlpProjectPage.get_edit_handler().get_form_class()

        self.assertTrue(issubclass(form_class, PlpProjectPageForm))

    def test_form_rejects_blank_category_under_index(self):
        """Top-level parent + blank ``category`` -> field-level validation error."""
        form = self._bind_form(self.index)

        self.assertFalse(form.is_valid())
        self.assertIn("category", form.errors)

    def test_form_accepts_blank_category_under_subproject_parent(self):
        """Subproject parent + blank ``category`` -> no ``category`` error."""
        form = self._bind_form(self.toplevel)

        form.is_valid()

        self.assertNotIn("category", form.errors)

    def _admin_add_post(self, parent: Page) -> HttpResponse:
        """POST a sparsely populated add-page form to ``wagtailadmin_pages:add``.

        Note: omitting ``action-publish`` from the body means Wagtail's create
        view runs the "save draft" branch, which calls
        ``form.defer_required_fields()`` before validation — so a top-level
        ``image`` / ``content`` value is not required for the bind. The only
        field-level error that can survive the bind is the one
        :class:`PlpProjectPageForm` raises in ``clean_category``.
        """
        self.login()
        url = reverse(
            "wagtailadmin_pages:add",
            args=[
                PlpProjectPage._meta.app_label,
                PlpProjectPage._meta.model_name,
                parent.pk,
            ],
        )
        return self.client.post(url, data=_empty_admin_post_data())

    def test_admin_post_top_level_parent_fails_on_category_field(self):
        """``wagtailadmin_pages:add`` under the index returns a ``category`` error."""
        response = self._admin_add_post(self.index)

        self.assertEqual(response.status_code, 200)
        self.assertIn("category", response.context["form"].errors)

    def test_admin_post_subproject_parent_does_not_fail_on_category_field(self):
        """``wagtailadmin_pages:add`` under a top-level project saves the subproject.

        Wagtail's "save draft" branch redirects (302) on success and the new
        subproject must therefore exist as a draft child of the top-level
        parent — proving no ``category`` validation rejected the POST.
        """
        response = self._admin_add_post(self.toplevel)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            PlpProjectPage.objects.descendant_of(self.toplevel).filter(slug="probe").exists()
        )


######################################################################
############# Test suite for PlpProjectPage copy form ##############
######################################################################


class TestPlpProjectCopyInvariants(BasePlpPageTestCase):
    """``PlpProjectPageCopyForm`` mirrors PLP depth-1 and top-level category rules."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Source tree with subprojects plus a destination top-level sibling."""
        super().setUpTestData()

        cls.toplevel_with_child = PlpProjectPage(
            title="Parent With Child",
            slug="parent-with-child",
            image=cls.image_a,
            category=cls.category_first,
        )
        cls.index.add_child(instance=cls.toplevel_with_child)
        cls.toplevel_with_child.save_revision().publish()

        cls.child_under_src = PlpProjectPage(
            title="Nested",
            slug="nested-under-src",
            image=cls.image_b,
            category=None,
        )
        cls.toplevel_with_child.add_child(instance=cls.child_under_src)
        cls.child_under_src.save_revision().publish()

        cls.toplevel_dest = PlpProjectPage(
            title="Destination Top",
            slug="destination-top",
            image=cls.image_c,
            category=cls.category_first,
        )
        cls.index.add_child(instance=cls.toplevel_dest)
        cls.toplevel_dest.save_revision().publish()

        cls.category_less_under_dest = PlpProjectPage(
            title="Category-less Sub",
            slug="category-less-sub",
            image=cls.image_a,
            category=None,
        )
        cls.toplevel_dest.add_child(instance=cls.category_less_under_dest)
        cls.category_less_under_dest.save_revision().publish()

    def _superuser(self) -> AbstractBaseUser:
        """Return the logged-in superuser (creates one on first call)."""
        return self.login()

    def _copy_form(
        self,
        page: Page,
        data: dict[str, Any],
        *,
        user: AbstractBaseUser | None = None,
    ) -> PlpProjectPageCopyForm:
        user = user or self._superuser()
        return PlpProjectPageCopyForm(
            data=data,
            user=user,
            page=page,
        )

    def test_recursive_copy_under_project_parent_is_rejected(self):
        """Recursive ``copy_subpages`` under ``PlpProjectPage`` must fail validation."""
        user = self._superuser()
        form = self._copy_form(
            self.toplevel_with_child,
            {
                "new_title": "Clone",
                "new_slug": "clone-under-dest",
                "new_parent_page": str(self.toplevel_dest.pk),
                "copy_subpages": True,
            },
            user=user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("copy_subpages", form.errors)

    def test_non_recursive_copy_under_subproject_parent_is_rejected(self):
        """Non-recursive copy onto a subproject must fail with a field-level error.

        Wagtail's data layer already blocks the copy via ``can_copy_to`` -> 403,
        but the form should surface a graceful ``new_parent_page`` error so the
        UX matches the recursive and category-less branches.
        """
        user = self._superuser()
        form = self._copy_form(
            self.toplevel_dest,
            {
                "new_title": "Clone",
                "new_slug": "clone-under-subproject",
                "new_parent_page": str(self.category_less_under_dest.pk),
                "copy_subpages": False,
            },
            user=user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("new_parent_page", form.errors)

    def test_category_less_copy_to_index_is_rejected(self):
        """Copying a category-less PLP page onto ``PlpIndexPage`` must fail."""
        user = self._superuser()
        form = self._copy_form(
            self.category_less_under_dest,
            {
                "new_title": "Promoted Copy",
                "new_slug": "promoted-to-index",
                "new_parent_page": str(self.index.pk),
            },
            user=user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("new_parent_page", form.errors)

    def test_recursive_copy_to_index_allowed_when_root_has_category(self):
        """Recursive copy to the PLP index is valid when the copied root has a category."""
        user = self._superuser()
        form = self._copy_form(
            self.toplevel_with_child,
            {
                "new_title": "Index Clone",
                "new_slug": "index-clone-unique",
                "new_parent_page": str(self.index.pk),
                "copy_subpages": True,
            },
            user=user,
        )

        self.assertTrue(form.is_valid(), msg=dict(form.errors))

    def test_page_model_registers_copy_form_class(self):
        """Admin copy view resolves ``PlpProjectPage.copy_form_class``."""
        self.assertIs(PlpProjectPage.copy_form_class, PlpProjectPageCopyForm)

    def test_admin_copy_post_recursive_under_project_surfaces_copy_error(self):
        """Live ``wagtailadmin_pages:copy`` POST rejects recursive copy under a project."""
        self.login()
        url = reverse("wagtailadmin_pages:copy", args=[self.toplevel_with_child.pk])
        response = self.client.post(
            url,
            {
                "new_title": "Clone",
                "new_slug": "clone-via-admin",
                "new_parent_page": self.toplevel_dest.pk,
                "copy_subpages": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].is_valid())
        self.assertIn("copy_subpages", response.context["form"].errors)

    def test_admin_copy_post_category_less_to_index_surfaces_parent_error(self):
        """Live copy POST to the index fails for a category-less source page."""
        self.login()
        url = reverse("wagtailadmin_pages:copy", args=[self.category_less_under_dest.pk])
        response = self.client.post(
            url,
            {
                "new_title": "Promoted",
                "new_slug": "promoted-via-admin",
                "new_parent_page": self.index.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].is_valid())
        self.assertIn("new_parent_page", response.context["form"].errors)
