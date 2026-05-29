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
# Two backends are available locally:
#
# 1. Console (default) — outgoing mail is printed to the runserver stdout.
#    Fastest iteration, no external service. Good enough when you only need
#    to confirm message body and headers.
#
# 2. Mailpit — a local SMTP catcher with a web UI at http://127.0.0.1:8025/.
#    Captures every outbound message so you can inspect the envelope the way
#    a real MTA would receive it (From, To, Reply-To, multipart parts).
#
# To route the dev server through mailpit, add to your local .env:
#
#     EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
#     EMAIL_HOST=localhost      # or `mailpit` when running via docker compose
#     EMAIL_PORT=1025
#     EMAIL_USE_TLS=False
#
# Start mailpit with `docker compose up mailpit`. End-to-end test the contact form:
# GET /contact/, submit a valid message, then either watch the runserver
# output (console) or open http://127.0.0.1:8025/ (mailpit) to inspect the
# delivered message. CONTACT_RECIPIENT_EMAIL stays `dev-null@example.org` by
# default so a misconfigured backend cannot accidentally reach a real inbox.
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
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=25)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=10)
