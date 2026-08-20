"""Template tags for generating a table of contents."""

import structlog
from bs4 import BeautifulSoup
from django import template
from django.core.cache import cache
from django.utils.safestring import mark_safe
from django.utils.text import slugify
from wagtail.fields import StreamField

register = template.Library()

LOGGER = structlog.get_logger(__name__)

CACHE_TIMEOUT = 60 * 60 * 24  # 24 hour


def get_toc_and_updated_content(content_html: str) -> dict[str, str | list[dict[str, str]]]:
    """Parse content HTML to extract headings and generate a table of contents.

    Args:
        content_html: The rendered HTML of the content.

    Returns:
        A dictionary with 'toc' as a list of heading dicts and 'content' as
        the updated HTML with heading IDs.
    """

    soup = BeautifulSoup(content_html, "html.parser")
    headings = soup.find_all(["h2", "h3"])

    if not headings:
        LOGGER.info("No headings found in content; skipping TOC generation.")
        return {"toc": [], "content": mark_safe(str(soup))}

    toc: list[dict[str, str]] = []
    used_ids: set[str] = set()
    for heading in headings:
        if heading.has_attr("data-ignore-in-toc"):
            continue

        heading_text = heading.get_text().strip()
        if not heading_text:
            continue

        base_id = heading.get("id") or slugify(heading_text)
        heading_id = base_id
        counter = 1
        while heading_id in used_ids:
            heading_id = f"{base_id}-{counter}"
            counter += 1
        used_ids.add(heading_id)
        heading["id"] = heading_id

        toc.append({"id": heading_id, "text": heading_text, "level": heading.name})

    return {"toc": toc, "content": mark_safe(str(soup))}


@register.inclusion_tag("cms/components/content_with_toc.html", takes_context=True)
def content_with_toc(
    context: template.Context, content: StreamField
) -> dict[str, str | list[dict[str, str]]]:
    """Generate and inject table of contents into content.

    Args:
        context: Template context, passed to the renderer.
        content: StreamField content to render.
    """

    if not getattr(content, "render_as_block", False):
        LOGGER.warning("Content is not a StreamField block.")
        return {"toc": [], "content": content}

    request = context.get("request")
    is_preview = request and getattr(request, "is_preview", False)

    page = context.get("page")
    published = (
        page.last_published_at.strftime("%Y%m%d%H%M%S%f")
        if page and page.last_published_at
        else None
    )
    # This tag caches the full StreamField HTML, including Plotly charts.
    # Dashboard Data uploads do not change last_published_at, so a new source
    # file would otherwise keep showing the previous charts until republish.
    # Append source_file_hash when present (DashboardPage / DrrDatasetPage).
    # Topic and basic pages have no hash, so they keep toc:{id}:{published}
    # and are not affected.
    cache_key = f"toc:{page.id}:{published}" if page and published else None
    file_hash = context.get("source_file_hash") or ""
    if cache_key and file_hash:
        cache_key = f"{cache_key}:{file_hash}"

    # Only use cache if we have a valid page and we're not in preview mode
    if cache_key and not is_preview:
        cached = cache.get(cache_key)
        if cached is not None:
            LOGGER.info(f"Using cached TOC for page '{page.title}' (ID: {page.id}).")
            return cached

    content_html = content.render_as_block(context.flatten())
    result = get_toc_and_updated_content(content_html)

    if cache_key and not is_preview:
        cache.set(cache_key, result, CACHE_TIMEOUT)
    return result
