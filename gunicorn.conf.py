"""Gunicorn settings, loaded by prod-entrypoint.sh."""

from core.settings.base import LOGGING as DJANGO_LOGGING

# Log gunicorn's error log (startup, worker boots, errors) as JSON instead of gunicorn's
# default plain text. Reuses Django's json_formatter so both log in the same format.
logconfig_dict = {
    "formatters": {"json": DJANGO_LOGGING["formatters"]["json_formatter"]},
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "stream": "ext://sys.stderr",
        },
    },
    "root": {"level": "INFO", "handlers": ["console"]},
    "loggers": {
        "gunicorn.error": {"handlers": ["console"], "propagate": False},
        # Django returns a body for HEAD requests which gunicorn drops before sending to client.
        # gunicorn.http.wsgi warns about this for every HEAD request it receives,
        # this would mean a log warning for every HEAD request to /healthz/ (noisy).
        "gunicorn.http.wsgi": {"level": "ERROR"},
    },
}
