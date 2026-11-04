# Which files to include in the GitHub repository

**Decision to be made:** What belongs in the shared repo vs local-only developer tooling?

**Logic:** Files that are not needed to recreate the software, or that only one developer uses locally, add noise and can conflict. Team-wide tools are fine to share.

**Status:** decision

**Decision:** Do not commit files that are unnecessary to recreate the software or that are personal local tooling. Put those patterns in `.gitignore`. Shared team tooling (used by everyone) may live in the repo.

**Where can I find the outcome of this decision?**

- Confluence: [Which files to include in the GitHub repository](https://scilifelab.atlassian.net/wiki/spaces/TE/pages/3809116234/Which+files+to+include+in+the+GitHub+repository)
- Examples in this repo: `.vscode/` is gitignored; optional editor settings are documented in [getting started](../getting-started.md#optional-vs-code--cursor--ruff)
