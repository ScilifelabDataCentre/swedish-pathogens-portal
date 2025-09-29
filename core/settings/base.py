"""
Base Django settings for Pathogens Portal project.

This file is shared by all environments and is environment-agnostic.
Environment-specific overrides should live in `development.py` and `production.py`.

For more information on Django settings, see:
https://docs.djangoproject.com/en/5.2/topics/settings/

For a full list of settings and their values, see:
https://docs.djangoproject.com/en/5.2/ref/settings/
"""

from pathlib import Path
import environ


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
]

THIRD_PARTY_APPS = []

LOCAL_APPS = [
    "pages.citation",
    "pages.dashboards",
    "pages.data_management",
    "pages.home",
    "pages.privacy",
    "pages.topics",
]


INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS


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
STATICFILES_DIRS = [BASE_DIR / "core" / "static"]
