# Truncation and rich text in cards

**Decision to be made:** Keep CSS truncation on cards? Allow rich text (links, italics) in card descriptions?

**Logic:** Long titles/descriptions hit two-line / three-line clamps. Older content had hyperlinks in descriptions; species names need italics.

**Status:** decision

**Decision:** Keep truncation in the UI, but shorten card copy so content fits without relying on the clamp. Card descriptions may use **italics** (e.g. species names) but **not hyperlinks**.

**Where can I find the outcome of this decision?**

- Confluence: [Truncation and rich text in cards](https://scilifelab.atlassian.net/wiki/spaces/TE/pages/4973691171/Truncation+and+rich+text+in+cards)
- Jira: [FREYA-2970](https://scilifelab.atlassian.net/browse/FREYA-2970)
- Convention summary: [dev-conventions — Wagtail content](../dev-conventions.md#wagtail-content-models)
