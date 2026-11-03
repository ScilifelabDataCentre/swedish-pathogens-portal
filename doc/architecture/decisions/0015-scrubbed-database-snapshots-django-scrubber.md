# 15. Scrubbed database snapshots for non-production instances

**Date**: 2026-11-02

## Status

Proposed

## Related ADRs

- [0006 – Adopt Wagtail as CMS](0006-adopt-wagtail-as-cms.md)
- [0011 – django-allauth for authentication](0011-django-allauth-for-authentication.md)

## Context

Staging, personal dev instances and local setups need realistic data. The production instance has but also holds personal and private data such as user accounts (names, emails, password hashes), comments, workflow review comments, sessions, API tokens, history entries (and more). That personal data should not leave production.

Wagtail stores all content in the database. Pages, revisions, image and document records, snippets and history are rows in the database. Files (media and datasets) are stored on persistent volumes. Copying over the site's content therefore means copying the database and the content on the persistent volumes.

Taking a subset of tables (aka ignoring user tables) does not work as pages, revisions, images, documents and history all reference users, so a `pg_dump` without the users tables won't `pg_restore`.


## Decision

Make a **scrubbed database dump inside the source instance's namespace** (normally production). Restore this scrubbed database dump into the destination.
The destination can be a deployed instance (e.g. staging or a personal dev instance, in the same or a different k8s cluster) or a local dev environment running docker compose.

A management command (`manage.py scrub_data` from [`django-scrubber`](https://github.com/RegioHelden/django-scrubber), run with a dedicated settings module) anonymises all users and personal data. The command only runs on a database whose name ends in "_scrub" to prevent accidentally scrubbing a real database instance.

The full syncing process can be run by a helper shell script stored in the private `argocd-freya` repository.
The script will allow the user to specify the source and destination. The source is normally production, but any deployed instance can be used (e.g. staging).


### How the scrub operation works

The scrub operation **anonymises all users and personal data**. It runs as a k8s Job in the source's namespace.

**The Job**:

1. Runs in the source's namespace. It dumps (with `pg_dump`) the database into a fresh Postgres instance inside the Job's own pod.
2. It scrubs that **copy of the database** and dumps the scrubbed database with `pg_dump`.
3. The scrubbed database dump is downloaded locally and used by the script to restore into the destination database.

It also copies media (without avatars) and datasets.
The script can create accounts for each developer afterwards or they can manually do it with a django managment command.

**The scrubbing process**:

- **Anonymises all users.** Usernames, names and emails are replaced with fake values, and accounts are made inactive with unusable passwords. Group memberships, permissions and user references on content (page owners, image uploaders, revisions) are kept.
- **Removes or replaces other private data:** sessions, API tokens, profiles, subscriptions, form submissions and the Django admin log are deleted. Comments get placeholder text and [Private page passwords](https://docs.wagtail.org/en/latest/advanced_topics/privacy.html#private-pages) are replaced.
- **Fakes copies inside revisions and history:** `uploaded_by`, comment text and usernames in history labels get the same fake values as their rows.
- **A leftover check runs at the end.** It fails the scrub if any former username or email is still a whole value in any text or JSON column.

## Consequences

### Positive

- Personal/private data never leaves the source's namespace, as the database dump copied over has already been scrubbed.
- Provides a more realistic copy of production (as oppposed to deleting users) as fewer entries are removed. Users, permissions and page history are retained.
- The admin panel pages are more realistic: page owners, revisions, comments and site history show consistent fake users.

### Negative

- Adds a dependency (`django-scrubber`, with `Faker`) and a separate settings module.
- Tables to empty are listed by hand, and keeping copies in revisions and history consistent needs custom code.
- New fields holding personal data are only caught if they copy a username or email exactly. Anything else would need adding to the scrub settings by hand.
- (Related to the point above) the scrubbing process will need to be checked once django-allauth is implemented to ensure those newly added tables are correctly scrubbed.
- After every sync, developers will need to reconnect their accounts to the new instance, as scrubbed users can't log in. This can be partially automated by recreating each developer's account with Django but each dev would still need to reset their password.

## Alternatives considered

**Delete users with a management command (`manage.py scrub_personal_data`) instead of anonymising them.** Users are deleted through Django, which removes or empties the rows that reference them, and private data not linked to users is removed by the command. It has been tested and does work on the staging instance's current data.

- ✅ No new dependency and no need for an extra core/settings module (when compared to using `django-scrubber`).
- ✅ Relying on Django's internal cascade after a user deletion event means Django is responsible for finding some of the tables to scrub.
- ❌ Restored instances have no history, comments or user references. 
- ❌ Related to above, the destination's database end up being less realistic than one created using `django-scrubber`. 

**Copy everything, then scrub on the destination.** This approach means personal/private data leaves the production cluster in the dump. 

**Restore from backups (CNPG/Barman).** Same problem as above, plus it wouldn't work for local dev (docker compose) setups.

**Leave user tables out of the dump.** Doesn't work as many tables reference users by foreign key.

**https://github.com/wagtail/wagtail-transfer** It hasn't been updated in a while (~1 year at time of writing) and has not been tested on Wagtail 8. 

**Synthetic data.** Too much maintenance required here as will need to be updated for new page and content types which is exactly what we are trying to avoid. 
