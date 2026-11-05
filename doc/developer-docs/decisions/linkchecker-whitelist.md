# Broken link checker operations

**Decision to be made:** How to handle false positives (e.g. Cloudflare 403, bot-blocked DOI links) in the link checker?

**Logic:** Many “broken” links are not broken for humans; failing CI on those is noise.

**Status:** decision

**Decision:** **Whitelist** known false positives (e.g. `doi.org` persistent identifiers that block automated clients) in the linkchecker GitHub Action configuration.

**Where can I find the outcome of this decision?**

- Confluence: [Operations of broken link checker](https://scilifelab.atlassian.net/wiki/spaces/TE/pages/5004755034/Operations+of+broken+link+checker+pathogens)
- Workflow: [`.github/workflows/linkchecker.yaml`](../../../.github/workflows/linkchecker.yaml)
- Ops summary: [operations — CI](../operations.md#ci-and-quality)
