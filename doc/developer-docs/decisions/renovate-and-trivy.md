# Renovate and Trivy operations

**Decision to be made:** How to run dependency updates and container/security scans without drowning the team in noise?

**Logic:** Too many Renovate PRs and broad Trivy branch failures blocked progress. Prefer timely security fixes and quieter routine updates/scans.

**Status:** decision

**Decision:**

- **Renovate:** security updates promptly; other dependency updates in a **bulk PR once per sprint** (target: first Tuesday of the sprint) so there is time to review.
- **Trivy:** keep scheduled scans; **narrow branch scans** so failures relate to the branch change set rather than unrelated findings.

**Where can I find the outcome of this decision?**

- Confluence: [What to do with renovate](https://scilifelab.atlassian.net/wiki/spaces/TE/pages/4331962369/What+to+do+with+renovate), [What to do with trivy](https://scilifelab.atlassian.net/wiki/spaces/TE/pages/4364533987/What+to+do+with+trivy)
- Workflows: `.github/workflows/trivy-*.yaml`; Renovate config in the repo / org settings
- Ops summary: [operations — CI](../operations.md#ci-and-quality)
