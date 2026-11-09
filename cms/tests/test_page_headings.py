"""Every public page should have one <h1>, containing the page's title.

The <h1> is rendered by cms/templates/cms/base.html from the template context.
Templates in ``H1_ALLOWED_TEMPLATES`` write their own <h1> instead.

Relates to WCAG 2.2 success criteria 1.3.1 (Info and Relationships) and 2.4.6 (Headings and Labels).
"""

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

# Templates allowed to contain a literal <h1>
H1_ALLOWED_TEMPLATES = {
    "cms/base.html",  # all pages use this template's <h1>, except for the templates below...
    "cms/pages/home.html",  # No banner on home page, the hero section has a <h1>
    "404.html",  # not a Wagtail page. Writes its own <h1>
}


class NoHandWrittenH1Test(SimpleTestCase):
    """Only the templates in ``H1_ALLOWED_TEMPLATES`` may write an <h1>."""

    def test_templates_do_not_write_their_own_h1(self):
        """Simple text search for <h1> in templates that are not allowed to write their own."""
        offenders = []
        for path in Path(settings.BASE_DIR).glob("*/templates/**/*.html"):
            rel = path.as_posix().split("/templates/", 1)[1]
            if rel.startswith("wagtailadmin/") or rel in H1_ALLOWED_TEMPLATES:
                continue
            if "<h1" in path.read_text(encoding="utf-8").lower():
                offenders.append(rel)

        self.assertEqual(
            offenders,
            [],
            "These templates write their own <h1>, but base.html already renders one. "
            "Either remove the <h1> from the template, or add it to H1_ALLOWED_TEMPLATES. "
            "You can customise the page's <h1> by setting in the context "
            "(1) 'page_title' (H1 text) and/or (2) 'page_heading' (banner label).",
        )
