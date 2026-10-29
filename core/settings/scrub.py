"""Settings for scrubbing personal data with django-scrubber.

Only used to run ``scrub_data`` against a *copy* of a database (a database
whose name ends with ``_scrub``), never to serve the site:

    export DJANGO_SETTINGS_MODULE=core.settings.scrub
    python manage.py migrate django_scrubber          # table for generated fake data
    python manage.py scrub_data --remove-fake-data
    python manage.py migrate django_scrubber zero     # drop it again before dumping
    # migrate leaves django_scrubber's content type and permissions; remove them
    python manage.py shell -c "from django.contrib.contenttypes.models import ContentType; \
        ContentType.objects.filter(app_label='django_scrubber').delete()"

What gets scrubbed is defined here; how (the hooks before and after, and the
leftover check) is in ``core.scrubbing``.
"""

from django.db import models
from django_scrubber import scrubbers

from .base import *  # noqa: F401,F403

# django-scrubber refuses to run unless DEBUG is on. This only affects the
# process running scrub_data, never a deployed site.
DEBUG = True

# Only installed here, so deployed instances never get django-scrubber's table
INSTALLED_APPS = [*INSTALLED_APPS, "django_scrubber"]  # noqa: F405

# Scrubbing serves no requests, so no URLs. core.urls adds dev-only URLs when
# DEBUG is on, which fail in the production image.
ROOT_URLCONF = __name__
urlpatterns = []

SCRUBBER_SERVICE_CLASS = "core.scrubbing.PortalScrubberService"


# VALUES REPLACED WHEREVER THEY APPEAR
# ------------------------------------------------------------------------------
# By field name: covers every model with a field of that name, now and in the
# future. Only names that are personal in every model using them; avoid broad
# names like "name" or "title" (collections, tags, page titles).
# By field type: only types that always hold personal data.
SCRUBBER_GLOBAL_SCRUBBERS = {
    "username": scrubbers.Faker("user_name"),  # auth_user
    "first_name": scrubbers.Faker("first_name"),  # auth_user
    "last_name": scrubbers.Faker("last_name"),  # auth_user
    "uploaded_by": scrubbers.Faker("user_name"),  # cms_dashboarddata (username stored as text)
    models.EmailField: scrubbers.Faker("email"),  # auth_user
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


# ROWS DELETED, NOT ANONYMISED
# ------------------------------------------------------------------------------
# Tables that only hold per-user data, secrets or logs, emptied before
# scrubbing. Nothing references them (except socialaccount_socialaccount, whose
# token table is emptied first). Tables that don't exist yet, e.g. before
# django-allauth is added, are skipped.
SCRUB_TABLES_TO_EMPTY = [
    "wagtailcore_apitoken",
    "wagtailusers_userprofile",
    "wagtailcore_pagesubscription",
    "wagtailadmin_editingsession",
    "wagtailadmin_formstate",  # unsaved form input
    "wagtailforms_formsubmission",  # whatever visitors typed into forms
    "wagtailcore_uploadedfile",  # temporary bulk-upload files
    # django-allauth
    "account_emailconfirmation",
    "socialaccount_socialtoken",  # identity provider access/refresh tokens
    "socialaccount_socialaccount",  # identity provider subject ID and raw claims
    "mfa_authenticator",  # TOTP secrets, recovery codes, passkeys
    "usersessions_usersession",  # IP addresses, user agents
    # Emptied here rather than by django-scrubber (SCRUBBER_CLEAR_DJANGO_ADMIN_LOG),
    # which would only clear it after the leftover check has run
    "django_admin_log",
    # Search index, holds copies of text; rebuilt by `update_index` when the
    # restored instance starts
    "wagtailsearch_indexentry",
]
# Sessions are always deleted by django-scrubber itself


# LEFTOVER CHECK
# ------------------------------------------------------------------------------
# Former usernames or emails not searched for, because they also match
# ordinary content. Every other value is still searched for in every column.
SCRUB_LEFTOVER_CHECK_IGNORED_VALUES = {
    # createsuperuser's default username in the dev container; matches
    # Wagtail's root page and collection ("Root")
    "root",
}
