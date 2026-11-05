# Disable page copy in Wagtail admin

**Decision to be made:** How to stop copied pages from being published without review?

**Logic:** Copy + publish bypassed the intended approval path. The team saw no strong use case for page copy (editors can create a new page of the same type and paste content).

**Status:** decision

**Decision:** Disable page copying in Wagtail admin. Prefer creating a new page of the correct type.

**Where can I find the outcome of this decision?**

- Confluence: [Pathogens Portal - copying pages](https://scilifelab.atlassian.net/wiki/spaces/TE/pages/4990566430/Pathogens+Portal+-+copying+pages)
- Code: `cms/wagtail_hooks.py` (`prevent_page_copy`, gated with `DISABLE_DIRECT_PUBLISH`)
- PR: [#111](https://github.com/ScilifelabDataCentre/swedish-pathogens-portal/pull/111)
- Convention summary: [dev-conventions — Wagtail content](../dev-conventions.md#wagtail-content-models)
