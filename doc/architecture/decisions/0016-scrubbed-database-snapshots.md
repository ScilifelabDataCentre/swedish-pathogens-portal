# 16. Scrubbed database snapshots for non-production instances

**Date**: 2026-11-02

## Status

Proposed

## Related ADRs

- [0006 – Adopt Wagtail as CMS](0006-adopt-wagtail-as-cms.md)
- [0011 – django-allauth for authentication](0011-django-allauth-for-authentication.md)
- [0015 – Implement django-allauth for authentication (Phase 1)](0015-implement-django-allauth-for-authentication.md)

## Context

Staging, personal dev instances and local setups need realistic data. The production instance has this data but also holds personal and private data such as user accounts (names, emails, password hashes), sessions, API tokens, django-allauth email addresses and page view-restriction passwords. That data should not leave production. Comments, workflow review comments and page history entries are allowed to leave production and do not need to be scrubbed/modified. It is okay for a real username to be linked to a comment/page history entry. The site itself is public, so any public content can be copied over as is. Accounts are only created by administrators in the Wagtail admin, so the general public/users of the service do not have accounts. A scrubbed copy of the database is not publicly available, it is only available to developers with production cluster access. 

Wagtail stores all content in the database. Pages, revisions, image and document records, snippets and history are rows in the database. Files (media and datasets) are stored on persistent volumes. Copying over the site's content therefore means copying the database and the contents of the persistent volumes.

Taking a subset of tables (aka ignoring user tables) does not work as pages, revisions, images, documents and history all reference users, so a `pg_dump` without the users tables won't `pg_restore`.

## Decision

Restore the latest production backup (using CNPG/Barman) into a temporary CNPG cluster and make a **scrubbed database dump inside the production instance's namespace**. Restore this scrubbed database dump into the destination. 
The destination can be a deployed instance (e.g. staging or a personal dev instance, in the same or a different k8s cluster) or a local dev environment running docker compose. 

A management command (e.g. `manage.py scrub_personal_data`) deletes all users and personal data.

The full syncing process is run by a helper shell script (see below). In this way, the unscrubbed copy of the database never leaves the production instance's namespace. 


### How the scrub operation works

The scrub operation **deletes all users and personal data**. It is called by a script from the developer's local machine. 

**The script does**:

1. Creates a temporary CNPG cluster (`spp-unscrubbed-copy`) in the production namespace from the latest production backup. The Barman plugin restores the latest base backup from S3 onto the copy's PVC. The copy then replays production's archived write-ahead log (WAL), so it matches production up to the last archived WAL, which is normally a few minutes old.
2. Creates a new database inside the temporary CNPG cluster (`CREATE DATABASE spp_scrub TEMPLATE spp OWNER app`). The scrub only runs on `spp_scrub`, so the restored `spp` database in the copy is never modified. (This is also an extra layer of protection, as the scrubbing job refuses to run on any database not named `*_scrub`.)
3. Creates a k8s Job, using the same app image as production. This job performs the scrubbing (using a django management command). 
4. (The script) creates a dump of the scrubbed database (with `pg_dump`) and copies this dumped file from the production instance to the developer's machine. 
5. Deletes everything it temporarily created in the production namespace. This also happens if the script fails partway through. 
6. Restores the dump into the destination database with `pg_restore`. 
7. Updates the Wagtail `Site` records (hostname and port) to match the destination, as the restored database has production's.

The copy cluster has read-only access to the backup bucket, the k8s Job has no access to the backups or the live production database.


**The script has the following properties**:

- Is stored in the private `argocd-freya` repository.
- Lets the user specify the `destination`. The `source` is always production, as it is the only instance with backups configured.
- Refuses to run if the `destination` is the production instance.
- Works for both deployed k8s instances and local dev instances (e.g. via docker compose).
- Copies media (without avatars) and datasets from production's persistent volumes to the destination (optional flag to skip this as sometimes not required).
- Can optionally create accounts for each developer after completion.

**The scrubbing process**:

1. **Deletes all users through Django.** `on_delete` removes the rows that only exist for a user (password hashes, profiles, API tokens, django-allauth email addresses, page subscriptions, editing sessions, comments and comment replies) and empties user references on content (page owners, image uploaders, revisions, workflow states). The content itself is kept.
2. **Removes private data that isn't linked to users by foreign key:** sessions, form submissions and view-restriction passwords.
3. **A leftover check runs at the end.** It fails the scrub if the user, session, API token or django-allauth email address tables are not empty, or if any view-restriction password is still set.

History entries, workflow review comments, revisions (including any comments inside the revision) and `uploaded_by` on dashboard data (a username stored as text) are left as they are.

## Consequences

### Positive

- User accounts, passwords and sessions never leave the production instance's namespace, as the database dump copied over has already been scrubbed. 
- The Job never touches the live production database.
- No new dependency and no need for an extra core/settings module (as compared to when using django-scrubber).
- Relying on Django's internal cascade after a user deletion event means Django automatically handles scrubbing most of the tables for us.
- The scrubbing logic is smaller and more maintainable, as history, revisions and workflow review comments don't need to be modified.

### Negative

- History entries and revisions are kept but no longer linked to a user in the restored instance.
- Only production can be used as the source, as it is the only instance with backups.
- Restoring from backups is slower than dumping the live database.
- The temporary copy cluster needs a read only key to production's backup bucket, stored in the production namespace.
- New tables holding personal/private data need to be checked when added. This relates primarily to the coming django-allauth MFA implementation and other potential sign in methods. 
- After every sync, developers will need to reconnect their accounts to the new instance. This can be partially automated by recreating each developer's account with Django but each dev would still need to reset their password.  

## Alternatives considered

- **Anonymise with [`django-scrubber`](https://github.com/RegioHelden/django-scrubber) instead of deleting.** Users are kept but given fake names and emails, and values copied into revisions and history get the same fake values. It has been tested and does work on the staging instance's current data.

    - ✅ Provides a more realistic copy of production as fewer entries are removed, users and different permission levels are retained. 
    - ✅ The admin panel pages are more realistic: page owners, revisions, comments and site history show consistent fake users.
    - ❌ Adds a dependency (`django-scrubber`, with `Faker`) and a separate settings module.
    - ❌ Needs more custom code than just deleting the users (but deleting the users also needs custom code as it does not cover all instances of personal/private data).

    This option was ultimately decided against because it adds complexity and we don't think we will make use of this more realistic copy. It's the content that we want, not things like "who did what" or the site's history.

- **Delete users with [`django-scrubber`](https://github.com/RegioHelden/django-scrubber).**

    - ❌ The package only clears or fakes field values (it doesn't delete rows apart from sessions), so deleting users would still be custom code.
    - ❌ Adds a dependency and a settings module without removing any of the custom code.
    - ❌ Its check for unscrubbed fields (`scrub_validation`) needs every model with text fields to be whitelisted, which is too much maintenance work.

- **Copy everything, then scrub on the destination.** This approach means personal/private data leaves the production cluster in the dump. 

- **Dump the live production database instead of restoring a backup.** The same process, but the temporary database is filled with a `pg_dump` of the live production database instead of being restored from the Barman backups.

    - ✅ Works from any deployed instance, not only where there are backups. This would mean staging or a deployed dev instance could be set as the `source`. 
    - ✅ No need for a read only S3 key to the backup bucket. 
    - ❌ The process needs credentials for the live production database.

    Restoring from backups was preferred as the Job never needs access to the live production database.

- **Leave user tables out of the dump.** Doesn't work as many tables reference users by foreign key.

- **[Wagtail Transfer](https://github.com/wagtail/wagtail-transfer).** Better suited to selective content imports and updates. It hasn't been updated in a while (~1 year at time of writing), is not tested on Wagtail 8 and we have not tested it, so it is unclear how much work it would need.

- **[PostgreSQL Anonymizer](https://postgresql-anonymizer.readthedocs.io/en/stable/anonymous_dumps/).** A Postgres extension that can make a masked `pg_dump` export directly. It needs the extension installed in production's CNPG cluster and a masking rule for every column with personal data, which we'd have to maintain ourselves instead of relying on Django's cascade.

- **Synthetic data.** Too much maintenance required here as will need to be updated for new page and content types which is exactly what we are trying to avoid. 
