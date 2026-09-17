"""Build the public EBI catalogue JSON from env envelope and dashboard pages."""

from __future__ import annotations

from datetime import date
from typing import Any

from django.conf import settings
from django.db.models import Q

from cms.pages.dashboard import DashboardPage

COUNTRY = "Sweden"


def _json_field(name: str, value: str) -> dict[str, str]:
    """Return one EBI Search `{name, value}` object."""
    return {"name": name, "value": value}


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
    """Return the EBI catalogue envelope plus computed entries.

    Envelope `name` is fixed. `release` and `release_date` come from Django
    settings (env / image bake). Entries are live dashboards with EBI fields.
    """
    entries = [
        {"fields": entry_fields(page, number)}
        for number, page in enumerate(catalogue_pages(), start=1)
    ]
    return {
        "name": settings.EBI_INDEX_NAME,
        "release": settings.EBI_RELEASE,
        "release_date": settings.EBI_RELEASE_DATE,
        "entry_count": len(entries),
        "entries": entries,
    }
