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

Taking a subset of tables (aka ignoring user tables) does not work as pages, revisions, images, documents and history all reference users, so a `pg_dump` without the users tables won't `pg_restore`

## Decision

Make a **scrubbed database dump inside the source instance's namespace** (normally production). Restore this scrubbed database dump into the destination. 
The destination can be a deployed instance (e.g. staging or a personal dev instance, in the same or a different k8s cluster) or a local dev environment running docker compose. 

A management command (e.g. `manage.py scrub_personal_data`) deletes all users and personal data. The command only runs on a database whose name ends in "_scrub" to prevent accidentally scrubbing a real database instance. 

The full syncing process can be run by a helper shell script stored in the private `argocd-freya` repository. 
The script will allow the user to specify the source and destination. The source is normally production, but any deployed instance can be used (e.g. staging). 


### How the scrub operation works

The scrub operation **deletes all users and personal data**. It runs as a k8s Job in the source's namespace.

**The Job**:

1. Runs in the source's namespace. It dumps (with `pg_dump`) the database into a fresh Postgres instance inside the Job's own pod.
2. It scrubs that **copy of the database** and dumps the scrubbed database with `pg_dump`. 
3. The scrubbed database dump is downloaded locally and used by the script to restore into the destination database. 

It also copies media (without avatars) and datasets. 
The script can create accounts for each developer afterwards or they can manually do it with a django managment command.

**The scrubbing process**:

- **Deletes all users through Django.** `on_delete` removes the rows that only exist for a user (profiles, API tokens, subscriptions, comments, editing sessions) and empties user references on content (page owners, image uploaders, revisions). Content itself is kept.
- **Removes private data that isn't linked to users by foreign key:** history entries, sessions, form submissions, `uploaded_by` on dashboard data, workflow review comments and view-restriction passwords.
- **Clears copies inside revisions:** user IDs, `uploaded_by` and saved comments.
- **A leftover check runs at the end.** It fails the scrub if any former username or email is still a whole value in any text or JSON column.

## Consequences

### Positive

- Personal/private data never leaves the source's namespace, as the database dump copied over has already been scrubbed. 
- No new dependency and no need for an extra core/settings module (as compared to when using django-scrubber).
- Relying on Django's internal cascade after a user deletion event means Django is responsible for finding the tables to scrub.

### Negative

- Restored instances have no history, comments or user references: the admin panel pages don't show who did what in the synced instances.
- The scrubbing process will need to be checked once django-allauth is implemented to ensure those newly added tables are correctly scrubbed. 
- After every sync, developers will need to reconnect their accounts to the new instance. This can be partially automated by recreating each developer's account with Django but each dev would still need to reset their password.  

## Alternatives considered

**Anonymise with [`django-scrubber`](https://github.com/RegioHelden/django-scrubber) instead of deleting.** Users are kept but given fake names and emails, and values copied into revisions and history get the same fake values. It has been tested and does work on the staging instance's current data.

- ✅ Provides a more realistic copy of production as fewer entries are removed, users and different permission levels are retained. 
- ✅ The admin panel pages are more realistic: page owners, revisions, comments and site history show consistent fake users.
- ❌ Adds a dependency (`django-scrubber`, with `Faker`) and a separate settings module.
- ❌ Needs more custom code than just deleting the users (but deleting the users also needs custom code as does not cover all instances of personal/private data).

**Copy everything, then scrub on the destination.** This approach means personal/private data leaves the production cluster in the dump. 

**Restore from backups (CNPG/Barman).** Same problem as above, plus it wouldn't work for local dev (docker compose) setups.

**Leave user tables out of the dump.** Doesn't work as many tables reference users by foreign key.

**https://github.com/wagtail/wagtail-transfer** It hasn't been updated in a while (~1 year at time of writing) and has not been tested on Wagtail 8. 

**Synthetic data.** Too much maintenance required here as will need to be updated for new page and content types which is exactly what we are trying to avoid. 
