"""Production settings.

These settings are intended for deployments.
"""

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False

# ADMIN
# ------------------------------------------------------------------------------
ADMIN_URL = env("ADMIN_URL").rstrip("/") + "/"
# ADMINS = [(Full name, email address)]
# MANAGERS = ADMINS


# WAGTAIL (Production)
# ------------------------------------------------------------------------------
WAGTAIL_SITE_NAME = "Swedish Pathogens Portal"
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


# EMAIL (Production via env; placeholders acceptable)
# ------------------------------------------------------------------------------
EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.smtp.EmailBackend",
)
DEFAULT_FROM_EMAIL = env(
    "DEFAULT_FROM_EMAIL",
    default="Pathogens Portal <no-reply@example.org>",
)
CONTACT_RECIPIENT_EMAIL = env(
    "CONTACT_RECIPIENT_EMAIL",
    default="pathogens@scilifelab.se",
)
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=10)
