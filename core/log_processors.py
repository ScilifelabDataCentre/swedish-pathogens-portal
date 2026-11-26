"""Custom structlog processors, registered in core/settings/base.py."""

import structlog
from structlog.types import EventDict, WrappedLogger


def drop_successful_health_checks(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """Drop django-structlog's request logs for successful health checks.

    For GET/HEAD requests to /healthz/:
        - `request_started` is always dropped,
        - `request_finished` is only dropped if the code is 200,
    so failing health checks are still logged.
    """
    if getattr(logger, "name", None) != "django_structlog.middlewares.request":
        return event_dict

    request = event_dict.get("request", "").partition("?")[0]
    if request not in ("GET /healthz/", "HEAD /healthz/"):
        return event_dict

    event = event_dict.get("event")

    if event == "request_started":
        raise structlog.DropEvent
    if event == "request_finished" and event_dict.get("code") == 200:
        raise structlog.DropEvent

    return event_dict
