# Migration files policy

**Decision to be made:** How to avoid migration conflicts during rapid development, then keep a stable history after launch?

**Logic:** Many parallel PRs producing migrations caused friction. The team wanted a clean baseline at cutover, then a normal append-only history.

**Status:** decision (with a **historical** phase and a **current** phase)

**Decision:**

1. **Pre-launch (historical):** ignore migration files during development, then replace with a single baseline migration at Wagtail cutover and stop gitignoring them.
2. **Post-launch (current):** `cms/migrations/` is **tracked**. After the shared DB has applied migrations, treat history as **append-only** — add new numbered migrations; do not rewrite applied files.

**Where can I find the outcome of this decision?**

- Confluence: [Migration files](https://scilifelab.atlassian.net/wiki/spaces/TE/pages/4436197377/Migration+files)
- Current practice: [operations — migrations](../operations.md#migrations), [dev-conventions — process](../dev-conventions.md#process-and-pull-requests)
