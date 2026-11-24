"""Gunicorn settings, loaded by prod-entrypoint.sh."""

import structlog

# Log gunicorn's error log (startup, worker boots, errors) as JSON, matching Django's
# json_formatter in core/settings/base.py. Configuring gunicorn.error replaces gunicorn's
# own plain text handler.
logconfig_dict = {
    "formatters": {
        "json": {
            "()": structlog.stdlib.ProcessorFormatter,
            "processor": structlog.processors.JSONRenderer(),
            "foreign_pre_chain": [
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.format_exc_info,
            ],
        },
    },
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
