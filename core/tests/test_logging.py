"""Tests for our custom request logging configuration where health checks are filtered out."""

import logging

from django.http import HttpRequest, JsonResponse
from django.test import TestCase, override_settings
from django.urls import path

REQUEST_LOGGER = "django_structlog.middlewares.request"


def failing_healthz(_request: HttpRequest) -> JsonResponse:
    """Make the `healthz` check fail."""
    return JsonResponse({"status": "error"}, status=503)


# Override the healthz url to make /healthz/ fail.
urlpatterns = [path("healthz/", failing_healthz)]


def logged_events(records: list[logging.LogRecord]) -> list[str]:
    """Return the event names of captured django-structlog records."""
    return [record.msg["event"] for record in records]


class RequestLoggingTests(TestCase):
    """Send requests through the middleware and check what django-structlog logs."""

    def test_successful_health_check_get_is_not_logged(self) -> None:
        """GET /healthz/ returning 200 logs nothing."""
        with self.assertNoLogs(REQUEST_LOGGER):
            self.client.get("/healthz/")

    def test_successful_health_check_head_is_not_logged(self) -> None:
        """HEAD /healthz/ returning 200 logs nothing."""
        with self.assertNoLogs(REQUEST_LOGGER):
            self.client.head("/healthz/")

    def test_successful_health_check_with_query_string_is_not_logged(self) -> None:
        """GET /healthz/?probe=1 returning 200 logs nothing."""
        with self.assertNoLogs(REQUEST_LOGGER):
            self.client.get("/healthz/?probe=1")

    @override_settings(ROOT_URLCONF=__name__)
    def test_failing_health_check_is_logged(self) -> None:
        """A failing health check logs `request_finished` with its status code."""
        with self.assertLogs(REQUEST_LOGGER) as logs:
            self.client.get("/healthz/")

        self.assertEqual(logged_events(logs.records), ["request_finished"])
        self.assertEqual(logs.records[0].msg["code"], 503)

    def test_other_requests_are_logged(self) -> None:
        """Other paths log both `request_started` and `request_finished`."""
        with self.assertLogs(REQUEST_LOGGER) as logs:
            self.client.get("/does-not-exist/")

        self.assertEqual(logged_events(logs.records), ["request_started", "request_finished"])
