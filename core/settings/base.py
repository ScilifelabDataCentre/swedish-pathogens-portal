"""Base Django settings for Pathogens Portal project.

This file is shared by all environments and is environment-agnostic.
Environment-specific overrides should live in `development.py` and `production.py`.

For more information on Django settings, see:
https://docs.djangoproject.com/en/5.2/topics/settings/

For a full list of settings and their values, see:
https://docs.djangoproject.com/en/5.2/ref/settings/
"""

from pathlib import Path

import environ
import structlog

# ENVIRONMENT
# ------------------------------------------------------------------------------
# Project root (build paths like this: BASE_DIR / "subdir")
BASE_DIR = Path(__file__).resolve().parents[2]

# Initialise environment variables
env = environ.Env()

# Read environment variables from .env file
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")

# INTERNATIONALISATION (https://docs.djangoproject.com/en/5.2/topics/i18n/)
# ------------------------------------------------------------------------------
LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Europe/Stockholm"
USE_I18N = True
USE_TZ = True


# APPS (https://docs.djangoproject.com/en/5.2/ref/settings/#installed-apps)
# ------------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",  # intcomma and other number/date filters
    "django.contrib.sitemaps",  # provides sitemap class and sitemap view
    "django.contrib.postgres",
]

WAGTAIL_APPS = [
    "wagtail.contrib.forms",
    "wagtail.contrib.redirects",
    "wagtail.contrib.routable_page",
    "wagtail.contrib.typed_table_block",
    "wagtail.embeds",
    "wagtail.sites",
    "wagtail.users",
    "wagtail.snippets",
    "wagtail.documents",
    "wagtail.images",
    "wagtail.search",
    "wagtail.admin",
    "wagtail",
    "modelcluster",
    "taggit",
]

THIRD_PARTY_APPS = [
    "django_htmx",
    "django_structlog",
]

LOCAL_APPS = ["cms", "portal_data.apps.PortalDataConfig"]

INSTALLED_APPS = DJANGO_APPS + WAGTAIL_APPS + THIRD_PARTY_APPS + LOCAL_APPS


# MIDDLEWARE (https://docs.djangoproject.com/en/5.2/ref/settings/#middleware)
# ------------------------------------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "django_structlog.middlewares.RequestMiddleware",
    "wagtail.contrib.redirects.middleware.RedirectMiddleware",
]


# URLS
# ------------------------------------------------------------------------------
ROOT_URLCONF = "core.urls"
WSGI_APPLICATION = "core.wsgi.application"


# TEMPLATES (https://docs.djangoproject.com/en/5.2/ref/settings/#templates)
# ------------------------------------------------------------------------------
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "core" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


# DATABASES (https://docs.djangoproject.com/en/5.2/ref/settings/#databases)
# ------------------------------------------------------------------------------
DATABASES = {
    "default": {
        **env.db("DATABASE_URL"),
        "CONN_MAX_AGE": env.int("DB_CONN_MAX_AGE", default=0),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# DATASETS ROOT variable used for portal data storage
DATASETS_ROOT = env("DATASETS_ROOT", default="/datasets")


# PASSWORDS (https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators)
# ------------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# STATIC FILES (https://docs.djangoproject.com/en/5.2/ref/settings/#static-files)
# ------------------------------------------------------------------------------
# REVIEW: These will depend on our static file serving strategy
STATIC_ROOT = BASE_DIR / "staticfiles"
STATIC_URL = "static/"


# WAGTAIL BASE SETTINGS
# ------------------------------------------------------------------------------
# Allowed image formats for upload via Wagtail admin.
WAGTAILIMAGES_EXTENSIONS = ["jpeg", "jpg", "png", "webp"]
# Default image format conversions of images during rendition.
WAGTAILIMAGES_FORMAT_CONVERSIONS = {
    "jpeg": "webp",
    "jpg": "webp",
    "png": "webp",
    "webp": "webp",
}


# Logging
# -----------------------------------------------------------------------------------------------
#
# This project uses django-structlog for structured logging.
# https://django-structlog.readthedocs.io/
#
# Usage in app code (module level logger):
#   LOGGER = structlog.get_logger(__name__)
#   LOGGER.info("Example of an info level log")

LOG_DIR = Path(env("LOG_DIR", default=BASE_DIR / "logs"))

LOGGING = {
    # --------------------------------------------------------------------------------------------
    # General config
    #
    # - Version is required, but only version 1 is supported
    # - disable_existing_loggers: False keeps the default Django loggers alive
    # --------------------------------------------------------------------------------------------
    "version": 1,
    "disable_existing_loggers": False,
    # --------------------------------------------------------------------------------------------
    # Formatters
    #
    # Define how the logs should be formatted.
    # This config defines two formatters: one for console output and one for JSON
    #
    # - "()" specifies a callable that returns a formatter instance
    # - ProcessorFormatter is used to integrate structlog with standard logging
    #   Without it: different formats for structlog and django/lib logs
    # - ConsoleRenderer produces structured logs as easily readable for console
    # - JSONRenderer produces structured logs as JSON
    # --------------------------------------------------------------------------------------------
    "formatters": {
        "plain_console": {
            "()": structlog.stdlib.ProcessorFormatter,
            "processor": structlog.dev.ConsoleRenderer(),
        },
        "json_formatter": {
            "()": structlog.stdlib.ProcessorFormatter,
            "processor": structlog.processors.JSONRenderer(),
        },
    },
    # --------------------------------------------------------------------------------------------
    # Handlers
    #
    # Define what happens to the log messages
    # This config defines two handlers: one to output to console and one to write
    # to a JSON file.
    #
    # - StreamHandler writes logs to stdout
    # - TimedRotatingFileHandler writes logs to a file
    #     > New file created every (interval 1) Monday (W0)
    #     > Total 11 files kept: 10 old (backupCount 10) and current
    #     > Delay=False means file is opened immediately, not on first write
    # --------------------------------------------------------------------------------------------
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "plain_console",
        },
        "json_file": {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "formatter": "json_formatter",
            "filename": str(LOG_DIR / "spp_structlog.jsonl"),
            "when": "W0",
            "interval": 1,
            "backupCount": 10,
            "delay": False,
        },
    },
    # --------------------------------------------------------------------------------------------
    # Loggers
    #
    # Different parts of the application log to different loggers.
    #
    # - The "root" logger is the default logger (entire application)
    #     > Placement of root key is required - inside loggers key not allowed
    # - django_structlog and werkzeug loggers are used by the packages called
    #   exactly that
    # - propagate set as False to prevent logs from being passed to parent loggers
    # - werkzeug logger produces access logs
    #     > only uses the console handler to avoid excessive logging and duplicates
    #     > propagate being False avoids werkzeug logs also going to root (--> json file)
    # --------------------------------------------------------------------------------------------
    "root": {
        "handlers": ["console", "json_file"],
        "level": "INFO",
    },
    "loggers": {
        "django_structlog": {
            "handlers": ["console", "json_file"],
            "level": "INFO",
            "propagate": False,
        },
        "werkzeug": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

# ------------------------------------------------------------------------------------------------
# Structlog configuration
#
# Processors:
# - structlog.contextvars.merge_contextvars pulls request context from middleware
# - structlog.stdlib.filter_by_level ignores logs below the logger's level
# - structlog.processors.TimeStamper(fmt="iso") gives human readable timestamps
#     example: YYYY-MM-DDTHH:MM:SS.sssZ instead of e.g. 1770289147.3015254
# - structlog.stdlib.add_logger_name includes the logger's name
# - structlog.stdlib.add_log_level includes the log level
# - structlog.stdlib.PositionalArgumentsFormatter() allows %-style formatting in logging
# - structlog.processors.StackInfoRenderer() allows stack_info=True in logging calls and
#     could potentially be used for debugging
# - structlog.processors.format_exc_info formats exception info if exc_info=True is used
# - structlog.processors.UnicodeDecoder decodes all byte strings to unicode
# - structlog.stdlib.ProcessorFormatter.wrap_for_formatter is needed when using ProcessorFormatter
#
# logger_factory:
# - structlog.stdlib.LoggerFactory() is needed so that structlog.get_logger(...) returns a logger
#     that is backed by Python’s standard logging system.
# ------------------------------------------------------------------------------------------------
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)
