"""Settings for scrubbing personal data from a copy of the db with django-scrubber.

Only allowed to run ``scrub_data`` against a *copy* of a db, with db name needing
to end in ``_scrub``.

This module defines what gets scrubbed, logic for how to scrub it is in ``core.scrubbing``.

To run it:

    export DJANGO_SETTINGS_MODULE=core.settings.scrub
    python manage.py migrate django_scrubber          # table for generated fake data
    python manage.py scrub_data --remove-fake-data
    python manage.py migrate django_scrubber zero     # drop it again before dumping
    # migrate leaves django_scrubber's content type and permissions; remove them
    python manage.py shell -c "from django.contrib.contenttypes.models import ContentType; \
        ContentType.objects.filter(app_label='django_scrubber').delete()"
"""

from django.db import models
from django_scrubber import scrubbers

from .base import *  # noqa: F401,F403

# django-scrubber refuses to run unless DEBUG is on. This only affects the
# process running scrub_data, never a deployed site.
DEBUG = True

# Apps
# ------------------------------------------------------------------------------
INSTALLED_APPS += ["django_scrubber"]  # noqa: F405

# URLS
# ------------------------------------------------------------------------------
# Scrubbing serves no requests, so no URLs.
ROOT_URLCONF = __name__
urlpatterns = []

# Never used, as scrubbing builds no admin URLs; set only to silence Wagtail's
# W003 warning on every manage.py command
WAGTAILADMIN_BASE_URL = "http://localhost"


SCRUBBER_SERVICE_CLASS = "core.scrubbing.PortalScrubberService"


# Field names to scrub in whatever model they appear in.
# ------------------------------------------------------------------------------
SCRUBBER_GLOBAL_SCRUBBERS = {
    "username": scrubbers.Faker("user_name"),
    "first_name": scrubbers.Faker("first_name"),
    "last_name": scrubbers.Faker("last_name"),
    "uploaded_by": scrubbers.Faker("user_name"),
    models.EmailField: scrubbers.Faker("email"),
    models.GenericIPAddressField: scrubbers.Null,
}


# PER-MODEL RULES (fields whose name alone doesn't say they're personal)
# ------------------------------------------------------------------------------
SCRUBBER_MAPPING = {
    "auth.User": "core.scrubbing.UserScrubbers",
    "wagtailcore.Comment": "core.scrubbing.CommentScrubbers",
    "wagtailcore.CommentReply": "core.scrubbing.CommentScrubbers",
    "wagtailcore.TaskState": "core.scrubbing.TaskStateScrubbers",
    "wagtailcore.PageViewRestriction": "core.scrubbing.ViewRestrictionScrubbers",
    "wagtailcore.CollectionViewRestriction": "core.scrubbing.ViewRestrictionScrubbers",
}


# Tables where all rows are deleted, not scrubbed/anonymized.
# ------------------------------------------------------------------------------
# Sessions are auto deleted by django-scrubber itself
SCRUB_TABLES_TO_EMPTY = [
    "wagtailcore_apitoken",
    "wagtailusers_userprofile",
    "wagtailcore_pagesubscription",
    "wagtailadmin_editingsession",
    "wagtailadmin_formstate",  # unsaved form input
    "wagtailforms_formsubmission",  # whatever visitors typed into forms
    # django-allauth tables
    "account_emailconfirmation",
    "socialaccount_socialtoken",  # identity provider access/refresh tokens
    "socialaccount_socialaccount",  # identity provider subject ID and raw claims
    "mfa_authenticator",  # TOTP secrets, recovery codes, passkeys
    "usersessions_usersession",  # IP addresses, user agents
    # Django admin stuff
    "django_admin_log",
    # Search index gets rebuilt when site is redeployed
    "wagtailsearch_indexentry",
]


# LEFTOVER CHECK
# ------------------------------------------------------------------------------
# Former usernames or emails not searched for, because they also match
# ordinary content. Every other value is still searched for in every column.
SCRUB_LEFTOVER_CHECK_IGNORED_VALUES = {
    # Common (local) usernames that also appear as ordinary content, e.g.
    # Wagtail's root page and collection ("Root")
    "root",
    "admin",
}
