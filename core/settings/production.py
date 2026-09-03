"""Production settings.

These settings are intended for deployments.
"""

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False

# ADMIN
# ------------------------------------------------------------------------------
INCLUDE_DJANGO_ADMIN = env.bool("INCLUDE_DJANGO_ADMIN", default=False)

if INCLUDE_DJANGO_ADMIN:
    # Required to set DJANGO_ADMIN_URL if INCLUDE_DJANGO_ADMIN is True.
    DJANGO_ADMIN_URL = env("DJANGO_ADMIN_URL").rstrip("/") + "/"
# ADMINS = [(Full name, email address)]
# MANAGERS = ADMINS


# WAGTAIL (Production)
# ------------------------------------------------------------------------------
WAGTAILADMIN_URL = env("WAGTAILADMIN_URL").rstrip("/") + "/"
WAGTAILADMIN_BASE_URL = env("WAGTAILADMIN_BASE_URL").rstrip("/")


# MEDIA FILES (Production)
# ------------------------------------------------------------------------------
MEDIA_ROOT = env("MEDIA_ROOT")
MEDIA_URL = env("MEDIA_URL", default="media").rstrip("/") + "/"

# Private visitor DE session payloads — must NOT be under MEDIA_ROOT /media.
# Mount a writable volume at the parent path (e.g. /app/private) on the spp pod;
# do not mount it into the media-proxy nginx container.
LIVER_SESSION_ROOT = env(
    "LIVER_SESSION_ROOT",
    default="/app/private/liver_resource_sessions",
)

# Must match Gateway ClientSettingsPolicy (50m) and liver MAX_TOTAL_UPLOAD_BYTES.
# This is the hard cap on the whole request body (multi-file POST). Below this size
# Django accepts the body; app validators then enforce per-file / total rules.
DATA_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024
# Individual files larger than this are spooled to NamedTemporaryFile under /tmp
# (emptyDir on the spp pod). Django deletes those temp files when the request ends.
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024


# PRODUCTION STATIC FILE SETTINGS
# ------------------------------------------------------------------------------
MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")  # noqa: F405
STORAGES = {
    # Default storage for uploaded files (media)
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {
            "location": MEDIA_ROOT,  # points to writable PVC
        },
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        "OPTIONS": {
            "location": STATIC_ROOT,  # noqa: F405 (import from base.py)
        },
    },
}


# SECURITY
# ------------------------------------------------------------------------------
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True

# REVIEW: Maybe needed given our K8s setup for production
# https://docs.djangoproject.com/en/5.2/ref/settings/#secure-proxy-ssl-header
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# REVIEW: Investigate HTTP Strict Transport Security related following settings
# https://docs.djangoproject.com/en/5.2/ref/settings/#secure-hsts-seconds
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)


# EMAIL (Production via Google Workspace SMTP Relay)
# ------------------------------------------------------------------------------
# Server-to-server transactional mail via smtp-relay.gmail.com. Auth at the
# relay side is IP allowlist (the cluster's egress NAT sits in
# 130.237.255.0/24) plus required TLS, so no credential travels in env.
#
# Django 6.1 replaced the EMAIL_* settings with MAILERS; the old names are
# removed in Django 7.0. Defining any deprecated EMAIL_* name alongside MAILERS
# raises ImproperlyConfigured, so this module must not reintroduce one.
#
# BACKEND is a pinned literal, never env-driven, so a misconfigured deployment
# cannot silently swap transports. The OPTIONS below stay env-overridable to
# support staging or a future relay swap without a code change; username and
# password are read with empty defaults so ticking "Require SMTP
# Authentication" on the relay is an env change, not a code change.
MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "OPTIONS": {
            "host": env("EMAIL_HOST", default="smtp-relay.gmail.com"),
            "port": env.int("EMAIL_PORT", default=587),
            "use_tls": env.bool("EMAIL_USE_TLS", default=True),
            "username": env("EMAIL_HOST_USER", default=""),
            "password": env("EMAIL_HOST_PASSWORD", default=""),
            "timeout": env.int("EMAIL_TIMEOUT", default=10),
        },
    },
}
# Not deprecated by the MAILERS migration, and required: a missing sender fails
# at settings load rather than at the first send. The relay rejects any From:
# outside the Workspace domain, so this must be an @scilifelab.se address.
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL")
# Required, no default: where contact-form submissions are delivered. Read with
# no fallback so a deployment that forgets it fails at settings load instead of
# silently mailing the live pathogens@scilifelab.se inbox (staging points this
# at a test recipient). The deployment secret MUST define it.
CONTACT_RECIPIENT_EMAIL = env("CONTACT_RECIPIENT_EMAIL")

# LOGGING
# REVIEW: Currently logs are not aggregated, only written to stdout.
# We write to stdout using the plain_console formatter.
# When ready, we can uncomment out the below line and switch to json_formatter in production
# NOTE: prod-entrypoint.sh sets '--access-logfile -', which writes non JSON format logs to STDOUT.
# This either needs to be removed or configured seperately
# to ensure all logs are written in JSON format to STDOUT.
# https://gunicorn.org/guides/docker/?h=json#logging
# LOGGING["handlers"]["console"]["formatter"] = "json_formatter"  # noqa: F405
