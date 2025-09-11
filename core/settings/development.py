"""
Development settings.

These settings are intended for local development.
"""

from .base import *  # noqa: F401,F403

DEBUG = True

ADMIN_URL = "admin/"


# DEVELOPMENT APPS
# ------------------------------------------------------------------------------
INSTALLED_APPS += [  # noqa: F405
    "django_extensions",
    "django_browser_reload",
]


# DEVELOPMENT MIDDLEWARE
# ------------------------------------------------------------------------------
MIDDLEWARE += [  # noqa: F405
    "django_browser_reload.middleware.BrowserReloadMiddleware",
]


# SECURITY
# ------------------------------------------------------------------------------
CSRF_TRUSTED_ORIGINS = ["http://localhost:8000", "http://127.0.0.1:8000"]


# MEDIA FILES (Development)
# ------------------------------------------------------------------------------
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "media/"


# LOGGING (https://django-extensions.readthedocs.io/en/latest/runserver_plus.html#configuration)
# ------------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "werkzeug": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": True,
        },
    },
}
