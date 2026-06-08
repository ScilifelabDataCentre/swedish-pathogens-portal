# Getting started (editors)

Use the **Wagtail admin** to edit pages, images, and site-wide snippets for the Swedish Pathogens Portal.

**Developers** setting up a local environment: [developer getting started](../developer-guide/01-getting-started.md).

---

## Log in

**Local URL:** http://localhost:8000/wagtail/

You need a user account with access to the admin. On a fresh install, a developer creates one:

```bash
docker compose exec web python manage.py createsuperuser
```

(Or the uv equivalent — see [Docker](../developer-guide/docker-development.md) / [local](../developer-guide/local-development.md) guides.)

Sign in with the username and password you were given.

---

## Main admin areas

| Area | Use for |
|------|---------|
| **Pages** | Site content — page tree, edit copy, StreamField blocks, publish |
| **Images** | Upload and manage images used in pages |
| **Documents** | PDFs and other files linked from content |
| **Snippets** | Reusable data outside the page tree (navigation menus, site banner, dashboard data upload, PLP categories) |

Most day-to-day editing is under **Pages**.

---

## Page tree (short)

The site has one **Home** page at the root. Sections are added as **child pages** under Home or under an **index** page (for example a news index with news articles as children).

When you add a page, Wagtail only shows **allowed** page types for the parent you selected — you cannot pick a type that is not permitted there.

More detail: [editor guide — page patterns](README.md#page-patterns-not-per-type-manuals).

---

## Draft, preview, and publish

| State | Meaning |
|-------|---------|
| **Draft** | Saved in admin; not visible on the public site (or shown only in preview) |
| **Live** | Published — visitors can see it at its URL |

Typical workflow:

1. Open **Pages** → select a page → **Edit**.
2. Change fields or StreamField blocks.
3. **Save draft** to keep working without publishing.
4. Use **Preview** to check how the page will look.
5. **Publish** when the content is ready to go live.

Unpublishing or reverting to draft is available from the same page actions menu if you need to hide content again.

---

## Where to edit common items

| Task | Go to |
|------|--------|
| Page body, blocks, title | **Pages** → page → Edit |
| Header / footer links | **Snippets** → Navigation menus |
| Site-wide notice banner | **Snippets** → Site announcements |
| Dashboard data file | **Snippets** → Dashboard data |
| Replace an image | **Images** |

---

## Next steps

- [Editor guide index](README.md) — page patterns and further topics
- [Developer guide](../developer-guide/README.md) — technical documentation
