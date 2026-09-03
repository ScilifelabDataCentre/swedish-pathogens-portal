"""Development settings.

These settings are intended for local development.
"""

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = True

# Include Django Admin in development environment
INCLUDE_DJANGO_ADMIN = True

# Development settings for Wagtail.
# ------------------------------------------------------------------------------
WAGTAIL_SITE_NAME = "Swedish Pathogens Portal (Dev)"
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
# Mailpit is the default: a local SMTP catcher listening on 127.0.0.1:1025 with
# a web UI at http://127.0.0.1:8025/. It is preferred over the console backend
# because it exercises the real SMTP client path — EHLO, envelope, headers —
# which is what production actually does against the Workspace relay. The
# console backend cannot show you a wrong From: or a dropped Reply-To; mailpit
# can, and it has an HTTP API you can assert against.
#
# Start it with `devbox run hub-up` (devbox) or `docker compose up mailpit`
# (Docker). For fast iteration with no service at all, override the backend:
#
#     EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
#
# Use EMAIL_HOST=mailpit instead of 127.0.0.1 when running inside Docker
# Compose, where the service name resolves on the network.
#
# Django 6.1 replaced the EMAIL_* settings with MAILERS; defining any
# deprecated EMAIL_* name alongside MAILERS raises ImproperlyConfigured. The
# env var names below are unchanged, so existing local overrides keep working.
# OPTIONS are validated against the chosen backend: a mailer built from MAILERS
# raises InvalidMailer on keys the backend does not accept, and the console
# backend accepts none of the SMTP ones. So only hand them over when the
# backend is actually SMTP. Lowercase names are not Django settings, so these
# two helpers stay private to this module.
_EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.smtp.EmailBackend",
)
_SMTP_OPTIONS = {
    "host": env("EMAIL_HOST", default="127.0.0.1"),
    "port": env.int("EMAIL_PORT", default=1025),
    "use_tls": env.bool("EMAIL_USE_TLS", default=False),
    "timeout": env.int("EMAIL_TIMEOUT", default=10),
}
MAILERS = {
    "default": {
        "BACKEND": _EMAIL_BACKEND,
        "OPTIONS": _SMTP_OPTIONS if _EMAIL_BACKEND.endswith("smtp.EmailBackend") else {},
    },
}
DEFAULT_FROM_EMAIL = env(
    "DEFAULT_FROM_EMAIL",
    default="Pathogens Portal <no-reply@example.org>",
)
# Kept at a black-hole address so a misconfigured backend cannot reach a real
# inbox: end-to-end checks read the message out of mailpit, not out of a mailbox.
CONTACT_RECIPIENT_EMAIL = env(
    "CONTACT_RECIPIENT_EMAIL",
    default="dev-null@example.org",
)
