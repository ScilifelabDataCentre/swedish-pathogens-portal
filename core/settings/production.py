"""
Production settings.

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
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False
)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)
