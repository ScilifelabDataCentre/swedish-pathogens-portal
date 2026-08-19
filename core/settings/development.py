"""Development settings.

These settings are intended for local development.
"""

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = True

ADMIN_URL = "admin/"

# WAGTAIL (Development)
# ------------------------------------------------------------------------------
WAGTAIL_SITE_NAME = "Swedish Pathogens Portal (Dev)"
WAGTAILADMIN_URL = "wagtail/"
WAGTAILADMIN_BASE_URL = "http://localhost:8000"


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
MEDIA_ROOT = BASE_DIR / "media"  # noqa: F405
MEDIA_URL = "media/"

# Private visitor DE session payloads (not served under MEDIA_URL).
LIVER_SESSION_ROOT = BASE_DIR / "private" / "liver_resource_sessions"  # noqa: F405


# EMAIL (Development defaults, override via .env if needed)
# ------------------------------------------------------------------------------
EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)
DEFAULT_FROM_EMAIL = env(
    "DEFAULT_FROM_EMAIL",
    default="Pathogens Portal <no-reply@example.org>",
)
CONTACT_RECIPIENT_EMAIL = env(
    "CONTACT_RECIPIENT_EMAIL",
    default="dev-null@example.org",
)
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=10)

# LOGGING (Development defaults)
# ------------------------------------------------------------------------------
# Create log directory if it doesn't exist

LOG_DIR.mkdir(parents=True, exist_ok=True)  # noqa: F405
