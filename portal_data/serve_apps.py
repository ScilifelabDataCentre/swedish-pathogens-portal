"""Fetch the public apps and models on SciLifeLab Serve, and find the pathogen-related ones.

Serve's open API lists every public app and model in one response (newest first):
https://serve.scilifelab.se/docs/api-documentation/

Relevance is decided with the same pathogen/infectious disease keyword list as the
MetaboLights publication search (see ``portal_data.metabolights.europepmc``), matched
against each app's name and description. As there, an app matched only on a weak
keyword (e.g. "host" or "strain") doesn't count. Editors can add apps the keywords
miss, or remove false positives, by Serve app ID (see ``relevant_apps``).
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog
from django.utils.dateparse import parse_datetime

from cms.services.api_client import fetch_json
from cms.services.caching import cache_get_or_set
from portal_data.metabolights import europepmc

LOGGER = structlog.get_logger(__name__)

SERVE_URL = "https://serve.scilifelab.se/"
SERVE_PUBLIC_APPS_URL = "https://serve.scilifelab.se/openapi/v1/public-apps"
# The whole catalogue comes in one response, which can take a while to build.
SERVE_TIMEOUT_SECONDS = 30
CACHE_KEY = "serve_apps:public_apps"
CACHE_TTL_SECONDS = 60 * 60
# App states (lower case) meaning the app is gone from Serve, so it is never listed.
UNAVAILABLE_STATUSES = frozenset({"deleted"})


@dataclass(frozen=True)
class ServeApp:
    """A public app or model on Serve.

    Attributes:
        id (int): Serve's ID for the app.
        name (str): The app's name.
        description (str): The app's description (may be empty).
        url (str): Where the app runs (always an http(s) URL).
        app_type (str): The kind of app, e.g. "Shiny App" or "Custom App".
        created_on (datetime | None): When the app was created on Serve.
        updated_on (datetime | None): When the app was last updated on Serve.
        keywords (tuple[str, ...]): Pathogen keywords found in the name or
            description, in the keyword list's spelling, in order of appearance.
    """

    id: int
    name: str
    description: str
    url: str
    app_type: str
    created_on: datetime | None
    updated_on: datetime | None
    keywords: tuple[str, ...] = ()

    @property
    def is_pathogen_related(self) -> bool:
        """Return True if at least one matched keyword is not a weak one."""
        return europepmc.has_strong_match(list(self.keywords))

    @classmethod
    def from_api(cls, item: dict[str, Any]) -> ServeApp | None:
        """Build a ServeApp from one item of the public-apps list.

        Returns None for items that can't or shouldn't be listed: no ID, name or
        http(s) URL, not public, or deleted.
        """
        app_id = item.get("id")
        name = (item.get("name") or "").strip()
        url = (item.get("url") or "").strip()
        if not isinstance(app_id, int) or not name or not re.match(r"https?://", url, re.I):
            return None
        if (item.get("access") or "public").lower() != "public":
            return None
        statuses = {
            str(item.get(field) or "").lower() for field in ("app_status", "k8s_user_app_status")
        }
        if statuses & UNAVAILABLE_STATUSES:
            return None

        description = (item.get("description") or "").strip()
        return cls(
            id=app_id,
            name=name,
            description=description,
            url=url,
            app_type=(item.get("app_type") or "").strip() or "Other",
            created_on=_parse_date(item.get("created_on")),
            updated_on=_parse_date(item.get("updated_on")),
            # app names are often identifiers like "malaria_crispr2024", where "_" would
            # stop the keyword matching on word boundaries
            keywords=find_keywords(f"{name}\n{description}".replace("_", " ")),
        )


def _parse_date(value: Any) -> datetime | None:  # noqa: ANN401
    """Parse an ISO 8601 timestamp, or return None if missing or invalid."""
    if not isinstance(value, str):
        return None
    try:
        return parse_datetime(value)
    except ValueError:
        return None


@functools.cache
def _keyword_matcher() -> tuple[re.Pattern[str], dict[str, str]]:
    """Return the keyword regex and a lower case -> list spelling lookup (built once)."""
    keywords = europepmc.load_keywords(europepmc.DEFAULT_KEYWORDS_CSV)
    spelling = {keyword.lower(): keyword for keyword in keywords}
    return europepmc.build_keyword_pattern(keywords), spelling


def find_keywords(text: str) -> tuple[str, ...]:
    """Return the pathogen keywords in ``text``, in the keyword list's spelling.

    E.g. "Malaria" and "malaria" both give "malaria", so they make one facet value.
    """
    pattern, spelling = _keyword_matcher()
    matches = europepmc.find_keyword_matches(text, pattern)
    return tuple(spelling.get(match.lower(), match) for match in matches)


def fetch_public_apps() -> list[ServeApp] | None:
    """Fetch every listable public app and model on Serve, cached for an hour.

    Returns None if Serve can't be reached or answers with something unexpected
    (failures are not cached, so the next request tries again).
    """

    def compute() -> list[ServeApp] | None:
        """Fetch and parse the public-apps list (called on a cache miss)."""
        data = fetch_json(SERVE_PUBLIC_APPS_URL, timeout=SERVE_TIMEOUT_SECONDS)
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            if data is not None:
                LOGGER.error("serve_apps.unexpected_response", keys=list(data)[:10])
            return None
        apps = [
            app for item in items if isinstance(item, dict) and (app := ServeApp.from_api(item))
        ]
        LOGGER.info("serve_apps.fetched", items=len(items), listable=len(apps))
        return apps

    return cache_get_or_set(key=CACHE_KEY, timeout=CACHE_TTL_SECONDS, compute=compute)


def relevant_apps(
    apps: list[ServeApp],
    include_ids: frozenset[int] = frozenset(),
    exclude_ids: frozenset[int] = frozenset(),
) -> list[ServeApp]:
    """Keep the pathogen-related apps, plus those in ``include_ids``, minus ``exclude_ids``.

    The exclusions win if an ID is in both. Order is kept.
    """
    return [
        app
        for app in apps
        if app.id not in exclude_ids and (app.id in include_ids or app.is_pathogen_related)
    ]
