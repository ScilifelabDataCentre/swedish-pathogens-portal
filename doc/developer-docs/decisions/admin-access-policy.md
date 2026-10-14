# Admin access and permissions

**Decision to be made:** How to grant admin access securely (especially around launch / migration)?

**Logic:** Shared superuser accounts are insecure. Superuser count should stay low until MFA and finer permissions are in place. Editors should not create users or approve their own changes without controls.

**Status:** decision

**Decision:** Prefer **Wagtail admin** for editorial work; keep Django admin off unless explicitly enabled for ops. Minimise superusers; use editor (and other role) accounts for day-to-day work. Evaluate any shared superuser carefully (credentials only in the team password store). Prefer MFA and tighter permissions before expanding superuser access. Production toggles include `DISABLE_DIRECT_PUBLISH` and `DISABLE_SELF_APPROVAL` (see `.env.example`).

**Where can I find the outcome of this decision?**

- Confluence: [Access to the site during migration](https://scilifelab.atlassian.net/wiki/spaces/TE/pages/4910415873/Access+to+the+site+during+migration+user+permissions)
- Auth ADR: [ADR-0011](../../architecture/decisions/0011-django-allauth-for-authentication.md)
- Related: [disable page copy](disable-page-copy.md), [dashboard uploads](../dashboard_uploads.md)
