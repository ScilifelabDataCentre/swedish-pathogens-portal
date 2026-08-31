"""Build the public EBI catalogue JSON from settings and dashboard pages."""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import structlog
from django.db.models import Q

from cms.pages.dashboard import DashboardPage
from cms.settings.ebi_index import EbiIndexSettings

LOGGER = structlog.get_logger(__name__)

COUNTRY = "Sweden"
GITHUB_FETCH_TIMEOUT_SECONDS = 10.0
GITHUB_USER_AGENT = "swedish-pathogens-portal"


def _json_field(name: str, value: str) -> dict[str, str]:
    """Return one EBI Search `{name, value}` object."""
    return {"name": name, "value": value}


def fetch_github_latest_release(url: str) -> dict[str, Any] | None:
    """GET a GitHub `releases/latest` URL and return the JSON object, or None."""
    try:
        response = httpx.get(
            url,
            timeout=GITHUB_FETCH_TIMEOUT_SECONDS,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": GITHUB_USER_AGENT,
            },
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        LOGGER.error("ebi_index.github_fetch_error", url=url, error=str(exc), exc_info=True)
        return None
    except ValueError as exc:
        LOGGER.error("ebi_index.github_invalid_json", url=url, error=str(exc), exc_info=True)
        return None
    if not isinstance(payload, dict):
        LOGGER.error("ebi_index.github_unexpected_payload", url=url)
        return None
    return payload


def resolve_envelope(settings: EbiIndexSettings) -> tuple[str, str]:
    """Return `(release, release_date)`, overlaying GitHub when the URL fetch succeeds."""
    release = settings.release
    release_date = settings.release_date
    url = settings.github_releases_latest_url.strip()
    if not url:
        return release, release_date

    payload = fetch_github_latest_release(url)
    if payload is None:
        return release, release_date

    tag_name = payload.get("tag_name")
    if isinstance(tag_name, str) and tag_name:
        release = tag_name

    published_at = payload.get("published_at")
    if isinstance(published_at, str) and len(published_at) >= 10:
        release_date = published_at[:10]

    return release, release_date


def _has_ebi_catalogue_values() -> Q:
    """Match dashboards whose EBI panel is filled."""
    return (
        Q(ebi_data_type__gt="")
        | Q(ebi_data_source__gt="")
        | Q(ebi_type_of_pathogens__ebi_type_of_pathogen__gt="")
    )


def catalogue_pages() -> list[DashboardPage]:
    """Live public dashboard pages with EBI fields, newest `dashboard_data_updated_at` first."""
    pages = list(
        DashboardPage.objects.live()
        .public()
        .filter(_has_ebi_catalogue_values())
        .distinct()
        .prefetch_related("ebi_type_of_pathogens")
        .specific()
    )
    pages.sort(
        key=lambda page: page.dashboard_data_updated_at or date.min,
        reverse=True,
    )
    return pages


def _format_updated_date(page: DashboardPage) -> str | None:
    """Return `yy-mm-dd` from the page date chain, or None if the page has no date."""
    updated = page.dashboard_data_updated_at
    if updated is None:
        return None
    return updated.strftime("%y-%m-%d")


def entry_fields(page: DashboardPage, dataset_number: int) -> list[dict[str, str]]:
    """Build the EBI `fields` array for one dashboard (no `methods`)."""
    fields = [
        _json_field("id", f"dataset{dataset_number}"),
        _json_field("name", page.title),
        _json_field("description", page.description or ""),
    ]
    updated_date = _format_updated_date(page)
    if updated_date is not None:
        fields.append(_json_field("updated_date", updated_date))
    fields.append(_json_field("country", COUNTRY))
    fields.append(_json_field("data_type", page.ebi_data_type or ""))

    pathogens = [
        rel.ebi_type_of_pathogen
        for rel in page.ebi_type_of_pathogens.all()
        if rel.ebi_type_of_pathogen
    ]
    if pathogens:
        fields.extend(_json_field("type_of_pathogen", value) for value in pathogens)
    else:
        fields.append(_json_field("type_of_pathogen", ""))

    fields.append(_json_field("data_source", page.ebi_data_source or ""))
    fields.append(_json_field("source_page", page.full_url or ""))
    return fields


def build_index() -> dict[str, Any]:
    """Return the EBI catalogue envelope plus computed entries."""
    settings = EbiIndexSettings.load()
    release, release_date = resolve_envelope(settings)
    entries = [
        {"fields": entry_fields(page, number)}
        for number, page in enumerate(catalogue_pages(), start=1)
    ]
    return {
        "name": settings.name,
        "release": release,
        "release_date": release_date,
        "entry_count": len(entries),
        "entries": entries,
    }
