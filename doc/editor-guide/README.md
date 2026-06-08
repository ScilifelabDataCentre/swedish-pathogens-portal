# Editor guide

For **Wagtail admin** users editing the Swedish Pathogens Portal.

**Developers:** [developer guide](../developer-guide/README.md)

**Start here:** [Getting started](01-getting-started.md) (log in, admin areas, publish workflow)

---

## Docs to write (in order)

| # | Topic | Files |
|---|--------|-------|
| 1 | **Getting started** | [01-getting-started.md](01-getting-started.md) |
| 2 | **Site structure** | Page tree, add/move/delete pages |
| 3 | **Working with pages** | One guide for page *patterns*, not every page type |
| 4 | **StreamField blocks** | What blocks do in the editor |
| 5 | **Snippets** | Navigation, announcements, dashboard data |

---

## Page patterns (not per-type manuals)

Most content follows the same ideas in Wagtail:

- **Home** — single site root; new top-level sections are added under it.
- **Index + detail** — list page (news, topics, outbreaks, …) with child pages for each item.
- **Standard content** — `StandardPage`: reorderable blocks (text, cards, tables, …).
- **Special sections** — catalogues (filters), PLP (categories), dashboards (charts), portal data — differ in *fields*, not in basic edit/publish flow.

One guide (`03-page-types/working-with-pages.md`) should explain these patterns and point to in-admin help text. Separate docs only where editors need extra steps (e.g. dashboard data upload snippet).

---

## Quick reference

| Task | Admin |
|------|--------|
| Edit page content | **Pages** → page → Edit |
| Navigation | **Snippets** → Navigation menus |
| Site banner | **Snippets** → Site announcements |
| Dashboard data file | **Snippets** → Dashboard data |
| Images | **Images** |

Wagtail only offers child page types allowed under the parent you pick.

---

## Related

- [Documentation index](../README.md)
- [Developer guide](../developer-guide/README.md)
