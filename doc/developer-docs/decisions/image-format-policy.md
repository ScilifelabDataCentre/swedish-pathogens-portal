# Image format policy in Wagtail

**Decision to be made:** Which upload formats to allow, and how to serve images for performance/SEO?

**Logic:** Format and size affect load time. A shared image policy should keep admin uploads predictable and renditions efficient.

**Status:** decision

**Decision:** Accept **JPEG / JPG, PNG, and WebP** uploads. Convert renditions to **WebP** via Wagtail format conversions.

**Where can I find the outcome of this decision?**

- Confluence: [Image format policy in Wagtail](https://scilifelab.atlassian.net/wiki/spaces/TE/pages/4416438273/Image+format+policy+in+Wagtail)
- Content image policy: [CDP2 Image policy](https://scilifelab.atlassian.net/wiki/spaces/CDP2/pages/4414406678/Image+policy)
- Code: `WAGTAILIMAGES_EXTENSIONS` and `WAGTAILIMAGES_FORMAT_CONVERSIONS` in `core/settings/base.py`; `cms/image_formats.py`
- Jira: [FREYA-2289](https://scilifelab.atlassian.net/browse/FREYA-2289)
