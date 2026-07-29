"""CMS project page for the Pandemic Laboratory Preparedness (PLP) program."""

from __future__ import annotations

from typing import Any

from django.db import models
from django.http import HttpRequest
from wagtail.admin.panels import FieldPanel
from wagtail.blocks import RichTextBlock
from wagtail.fields import StreamField
from wagtail.images import get_image_model_string
from wagtail.models import Page
from wagtail.search import index
from wagtail.snippets.widgets import AdminSnippetChooser

from cms.blocks import AlertBlock, CardBlock, CardGridBlock, DataTableBlock
from cms.forms import PlpProjectPageCopyForm, PlpProjectPageForm
from cms.snippets import PlpCategory


class PlpProjectPage(Page):
    """A PLP capability project page (top-level or one-deep subproject).

    The same model represents both top-level capability projects (children of
    :class:`cms.pages.plp_index.PlpIndexPage`) and their immediate subprojects
    (children of another ``PlpProjectPage``). Exactly one level of subproject
    is supported; the depth-1 invariant is enforced via :meth:`can_create_at`
    and :meth:`can_move_to`, both admin-scoped hooks. Programmatic
    ``add_child`` / ``move`` calls bypass these gates by design (see the spec
    Risks section).

    The ``category`` foreign key stays ``null=True, blank=True`` so the admin
    form widget accepts an empty value for subprojects; the
    :class:`PlpProjectPageForm` enforces the "required for top-level only"
    rule, and :meth:`can_move_to` keeps that invariant alive on the move path.

    Attributes:
        image (ForeignKey): Card thumbnail image (required, ``PROTECT`` on
            image delete to mirror :class:`cms.pages.outbreaks.OutbreakPage`).
        category (ForeignKey): Optional :class:`cms.snippets.PlpCategory`;
            required for top-level projects (enforced by the admin form).
        content (StreamField): Editor-managed body of the detail page.
    """

    template = "cms/pages/plp_project.html"
    parent_page_types = ["cms.PlpIndexPage", "cms.PlpProjectPage"]
    subpage_types = ["cms.PlpProjectPage"]

    image = models.ForeignKey(
        get_image_model_string(),
        null=True,
        blank=False,
        on_delete=models.PROTECT,
        related_name="+",
    )
    category = models.ForeignKey(
        "cms.PlpCategory",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="projects",
        help_text="Required for top-level projects only; leave blank for subprojects.",
    )
    content = StreamField(
        [
            ("text", RichTextBlock()),
            ("alert", AlertBlock()),
            ("data_table", DataTableBlock()),
            ("card", CardBlock()),
            ("card_grid", CardGridBlock()),
        ],
        blank=False,
    )

    search_fields = Page.search_fields + [
        index.SearchField("content"),
        index.AutocompleteField("title"),
    ]

    content_panels = Page.content_panels + [
        FieldPanel("image"),
        FieldPanel("category", widget=AdminSnippetChooser(PlpCategory)),
        FieldPanel("content"),
    ]

    base_form_class = PlpProjectPageForm
    copy_form_class = PlpProjectPageCopyForm

    class Meta:
        """Display name for the PLP project page type in the admin."""

        verbose_name = "PLP project page"
        verbose_name_plural = "PLP project pages"

    @classmethod
    def can_create_at(cls, parent: Page) -> bool:
        """Reject admin "Add child page" of a third-level descendant.

        The admin offers ``PlpProjectPage`` under :class:`PlpIndexPage` and
        under top-level ``PlpProjectPage`` parents only. If the prospective
        ``parent`` is itself a subproject (its parent is a ``PlpProjectPage``),
        creating another child would produce a depth-3 grandchild and is
        rejected.
        """
        if not super().can_create_at(parent):
            return False
        parent_specific = parent.specific
        if isinstance(parent_specific, PlpProjectPage):
            grandparent = parent_specific.get_parent().specific
            if isinstance(grandparent, PlpProjectPage):
                return False
        return True

    def can_move_to(self, parent: Page) -> bool:
        """Reject admin moves that would break the depth-1 or category invariants.

        Three rules apply on top of Wagtail's default checks:

        * The destination cannot itself be a subproject (``parent`` is a
          ``PlpProjectPage`` whose parent is also a ``PlpProjectPage``).
        * If ``self`` already has any ``PlpProjectPage`` descendants, it
          cannot move under another ``PlpProjectPage`` (would create depth-3
          grandchildren).
        * If the destination is :class:`PlpIndexPage` (promotion to
          top-level), ``self.category_id`` must be set so the index grouping
          invariant survives.
        """
        from cms.pages.plp_index import PlpIndexPage

        if not super().can_move_to(parent):
            return False
        parent_specific = parent.specific
        if isinstance(parent_specific, PlpProjectPage):
            grandparent = parent_specific.get_parent().specific
            if isinstance(grandparent, PlpProjectPage):
                return False
            if self.get_descendants().type(PlpProjectPage).exists():
                return False
        return not (isinstance(parent_specific, PlpIndexPage) and self.category_id is None)

    def get_context(self, request: HttpRequest) -> dict[str, Any]:
        """Expose ``subprojects``, ``parent_title``, ``parent_is_index``, and ``page_heading``.

        ``page_heading`` is the PLP program index title so the site base banner shows the
        program name while the project template keeps ``<h3>{{ page.title }}</h3>``.
        """
        from cms.pages.plp_index import PlpIndexPage

        context = super().get_context(request)
        plp_index = self.get_ancestors().type(PlpIndexPage).specific().first()
        if plp_index is not None:
            context["page_heading"] = plp_index.title
        context["subprojects"] = self.get_children().type(PlpProjectPage).live().specific()
        parent_specific = self.get_parent().specific
        context["parent_title"] = parent_specific.title
        context["parent_is_index"] = isinstance(parent_specific, PlpIndexPage)
        return context
