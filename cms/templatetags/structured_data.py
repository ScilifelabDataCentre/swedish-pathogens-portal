"""Template tag emitting Schema.org structured data (JSON-LD) for the current page."""

from __future__ import annotations

import json
import mimetypes
from typing import TYPE_CHECKING, Any, Protocol

import structlog
from django import template
from django.utils.safestring import SafeString, mark_safe
from wagtail.models import Site

from cms.pages.dashboard import DashboardPage
from cms.pages.dashboard_index import DashboardIndexPage
from cms.pages.highlights_and_editorials import HighlightsAndEditorialsPage
from cms.pages.home import HomePage
from cms.pages.news import NewsPage
from cms.pages.slu_dashboard import SLUDashboardPage
from cms.snippets.dashboard_data import DashboardData

if TYPE_CHECKING:
    from datetime import date, datetime

    from wagtail.images.models import AbstractImage
    from wagtail.models import Page


class MediaFile(Protocol):
    """Anything exposing a media ``url``: a model file field or an image rendition."""

    @property
    def url(self) -> str:
        """Return the media URL, which may be relative to the site root."""
        ...


register = template.Library()

LOGGER = structlog.get_logger(__name__)

SCHEMA_CONTEXT = "https://schema.org"

DEFAULT_SITE_NAME = "Swedish Pathogens Portal"
SITE_ALTERNATE_NAME = "The Swedish Pathogens Portal"

ORGANIZATION: dict[str, Any] = {
    "@type": "Organization",
    "name": "SciLifeLab Data Centre",
    "url": "https://www.scilifelab.se/",
    "sameAs": [
        "https://x.com/scilifelab_DC",
        "https://www.linkedin.com/company/scilifelab-data-centre/",
        "https://github.com/ScilifelabDataCentre/swedish-pathogens-portal",
    ],
}

# The SLU wastewater dataset's DOI is also the visible citation in
# cms/templates/cms/pages/slu_wastewater/partials/dataset_info.html. Both copies
# must change together until an editable model field replaces them.
SLU_DATASET_DOI = "10.17044/scilifelab.14256317"
SLU_DATASET_DOI_URL = f"https://doi.org/{SLU_DATASET_DOI}"

# Matches the rendition the page head already generates for og:image, so the
# JSON-LD reuses that rendition instead of creating a second one.
_IMAGE_FILTER_SPEC = "format-jpeg|fill-900x450"


def _site(page: Page) -> Site | None:
    """Return the page's site, or ``None`` when it cannot be resolved.

    ``Page.get_site`` reads the site id out of Wagtail's cached root paths and
    then loads that row, so a cache left stale by a site change raises instead of
    returning ``None``. Degrading to the portal defaults keeps the rest of the
    payload intact, rather than losing a page's whole description over its host.

    Args:
        page: The page whose site is resolved.

    Returns:
        Site | None: The site, or ``None`` if there is none to be had.
    """
    try:
        return page.get_site()
    except Site.DoesNotExist:
        LOGGER.warning("structured_data.site_unresolved", page_id=getattr(page, "id", None))
        return None


def _site_name(page: Page) -> str:
    """Return the site name the page head resolves, or the portal default."""
    return getattr(_site(page), "site_name", "") or DEFAULT_SITE_NAME


def _site_root_url(page: Page) -> str:
    """Return the page's site root URL without a trailing slash, or an empty string."""
    return (getattr(_site(page), "root_url", "") or "").rstrip("/")


def _description(page: Page) -> str:
    """Return the page description, preferring the SEO override like the head does."""
    return getattr(page, "search_description", "") or getattr(page, "description", "") or ""


def _iso(value: datetime | date | None) -> str:
    """Return an ISO 8601 representation of a date or datetime, or an empty string."""
    return value.isoformat() if value else ""


def _absolute_media_url(page: Page, media: MediaFile) -> str:
    """Return an absolute URL for a media file or image rendition.

    Resolved against the page's own site rather than ``WAGTAILADMIN_BASE_URL``,
    so every URL in one payload shares the host that ``page.full_url`` reports.

    Args:
        page: The page the media is advertised on, used to resolve the site root.
        media: The file field or rendition to build a URL for.

    Returns:
        str: An absolute URL, or an empty string when there is no file or the
            site root cannot be resolved.
    """
    try:
        url = media.url
    except ValueError:
        return ""

    if url.startswith(("http://", "https://")):
        return url

    root = _site_root_url(page)
    return f"{root}{url}" if root else ""


def _image_url(page: Page) -> str:
    """Return an absolute URL for the page's card image.

    Reuses the rendition the page head already generates for ``og:image``, so
    this adds no second rendition. Rendition generation touches the image file,
    so a missing or unreadable original yields no image rather than breaking the
    page it is embedded in.

    Args:
        page: The page whose ``image`` field is read, if it has one.

    Returns:
        str: The absolute rendition URL, or an empty string when the page has no
            image or the rendition cannot be generated.
    """
    image: AbstractImage | None = getattr(page, "image", None)
    if image is None:
        return ""

    try:
        rendition = image.get_rendition(_IMAGE_FILTER_SPEC)
    except Exception:
        LOGGER.warning("structured_data.image_rendition_failed", page_id=getattr(page, "id", None))
        return ""

    return _absolute_media_url(page, rendition)


def _website(page: Page) -> dict[str, Any]:
    """Build the ``WebSite`` node describing the portal as a whole."""
    payload: dict[str, Any] = {
        "@type": "WebSite",
        "name": _site_name(page),
        "alternateName": SITE_ALTERNATE_NAME,
    }
    _set_if(payload, "url", _site_root_url(page))
    return payload


def _set_if(payload: dict[str, Any], key: str, value: object) -> None:
    """Assign ``key`` only when ``value`` is non-empty, so no null or "" is emitted."""
    if value:
        payload[key] = value


def _creative_work(page: Page, schema_type: str) -> dict[str, Any]:
    """Build the properties ``Article`` and ``NewsArticle`` share.

    Deliberately reads no keyword field: ``NewsPage`` has no keyword source, and
    a shared lookup here would silently give it an ``Article``'s ``keywords``.

    Args:
        page: The article page.
        schema_type: ``"Article"`` or ``"NewsArticle"``.

    Returns:
        dict[str, Any]: The common node, empty-valued keys omitted.
    """
    payload: dict[str, Any] = {"@type": schema_type, "headline": page.title}
    _set_if(payload, "description", _description(page))
    _set_if(payload, "url", page.full_url)
    _set_if(payload, "image", _image_url(page))
    _set_if(payload, "datePublished", _iso(page.first_published_at))
    _set_if(payload, "dateModified", _iso(page.last_published_at))
    return payload


def _article(page: HighlightsAndEditorialsPage) -> dict[str, Any]:
    """Build the ``Article`` node for a highlight or editorial.

    A ``Person`` author is claimed only for an editorial that names one: data
    highlights describe work published elsewhere, so the free-text ``author``
    field on them is not this article's author.
    """
    payload = _creative_work(page, "Article")
    _set_if(payload, "keywords", page.keyword_list)
    payload["publisher"] = ORGANIZATION

    if page.article_type == "editorial" and page.author:
        payload["author"] = {"@type": "Person", "name": page.author}

    return payload


def _news_article(page: NewsPage) -> dict[str, Any]:
    """Build the ``NewsArticle`` node for a news page.

    The portal itself writes the news, so the Organization is both author and
    publisher. No ``keywords`` key is emitted: ``NewsPage`` has no keyword field.
    """
    payload = _creative_work(page, "NewsArticle")
    payload["author"] = ORGANIZATION
    payload["publisher"] = ORGANIZATION
    return payload


def _data_catalog(page: Page) -> dict[str, Any]:
    """Build the ``DataCatalog`` node for the dashboards index this page sits under.

    Args:
        page: The dashboard page whose ancestors are searched.

    Returns:
        dict[str, Any]: The catalog node, or an empty dict when the page has no
            ``DashboardIndexPage`` ancestor.
    """
    index = page.get_ancestors().type(DashboardIndexPage).specific().first()
    if index is None:
        return {}

    payload: dict[str, Any] = {"@type": "DataCatalog", "name": index.title}
    _set_if(payload, "url", index.full_url)
    return payload


def _distribution(page: Page, data_row: DashboardData) -> list[dict[str, Any]]:
    """Build the ``DataDownload`` list advertising the dashboard's source file.

    The file is advertised whenever one is uploaded. It is served from
    ``MEDIA_ROOT`` and is publicly fetchable whether or not a given dashboard
    renders a download link for it, so claiming it is a true representation.

    Args:
        page: The dashboard page, used to resolve the site root.
        data_row: The dashboard's data row.

    Returns:
        list[dict[str, Any]]: One ``DataDownload``, or an empty list when no
            usable file URL could be built.
    """
    source_file = getattr(data_row, "source_file", None)
    if not source_file:
        return []

    url = _absolute_media_url(page, source_file)
    if not url:
        return []

    download: dict[str, Any] = {"@type": "DataDownload", "contentUrl": url}
    _set_if(download, "encodingFormat", mimetypes.guess_type(source_file.name)[0])
    return [download]


def _dataset(page: DashboardPage, data_row: DashboardData) -> dict[str, Any]:
    """Build the ``Dataset`` node for a dashboard backed by an uploaded data file."""
    payload: dict[str, Any] = {"@type": "Dataset", "name": page.title}
    _set_if(payload, "description", _description(page))
    _set_if(payload, "url", page.full_url)
    _set_if(payload, "keywords", page.keyword_list)
    _set_if(payload, "dateModified", _iso(page.dashboard_data_updated_at))
    _set_if(payload, "includedInDataCatalog", _data_catalog(page))
    _set_if(payload, "distribution", _distribution(page, data_row))
    payload["creator"] = ORGANIZATION

    if isinstance(page, SLUDashboardPage):
        payload["identifier"] = SLU_DATASET_DOI_URL
        payload["sameAs"] = SLU_DATASET_DOI_URL

    return payload


def _web_page(page: Page) -> dict[str, Any]:
    """Build the generic ``WebPage`` node used for every page with no richer type."""
    payload: dict[str, Any] = {"@type": "WebPage", "name": page.title}
    _set_if(payload, "description", _description(page))
    _set_if(payload, "url", page.full_url)
    payload["isPartOf"] = _website(page)
    return payload


def build_payload(page: Page) -> dict[str, Any]:
    """Build the JSON-LD payload describing one page.

    Dispatch order matters: ``SLUDashboardPage``, ``LiverResourceDashboardPage``
    and ``DrrDatasetPage`` all subclass ``DashboardPage``, so the dashboard
    branch is tested before the article types and decides on the data row's
    model rather than its truthiness. ``DrrDatasetPage.dashboard_data`` returns a
    truthy ``DrrDatasetData`` with no ``source_file``, which falls through to
    ``WebPage`` here instead of being described as a ``Dataset``.

    Args:
        page: The page in template context.

    Returns:
        dict[str, Any]: The payload, including its ``@context``.
    """
    if isinstance(page, HomePage):
        node = _website(page)
        node["publisher"] = ORGANIZATION
    elif isinstance(page, DashboardPage):
        data_row = page.dashboard_data
        node = _dataset(page, data_row) if isinstance(data_row, DashboardData) else _web_page(page)
    elif isinstance(page, HighlightsAndEditorialsPage):
        node = _article(page)
    elif isinstance(page, NewsPage):
        node = _news_article(page)
    else:
        node = _web_page(page)

    return {"@context": SCHEMA_CONTEXT, **node}


def encode_payload(payload: dict[str, Any]) -> str:
    """Serialise a payload for embedding in an HTML ``script`` element.

    ``django.utils.html.json_script`` cannot be used because it hardcodes
    ``type="application/json"``, so the characters that could end the script
    element early are escaped here instead.

    Args:
        payload: The JSON-LD payload.

    Returns:
        str: JSON with ``<``, ``>`` and ``&`` escaped as unicode sequences.
    """
    return (
        json.dumps(payload).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    )


@register.simple_tag(takes_context=True)
def structured_data(context: template.Context) -> SafeString | str:
    """Render the current page's Schema.org JSON-LD as a script element.

    Included from the page head on every template extending ``cms/base.html``,
    so a failure here would otherwise break every page. Any error is logged and
    yields no output, matching how ``breadcrumbs`` degrades. Renders nothing when
    there is no page in context, which is the case for the 404 template.

    Args:
        context: The template context.

    Returns:
        SafeString | str: The ``script`` element, or an empty string.
    """
    page = context.get("page")
    if page is None:
        return ""

    try:
        payload = encode_payload(build_payload(page))
    except Exception:
        LOGGER.exception("structured_data.build_failed", page_id=getattr(page, "id", None))
        return ""

    return mark_safe(f'<script type="application/ld+json">{payload}</script>')
