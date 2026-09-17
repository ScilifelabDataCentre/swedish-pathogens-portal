# 11. Dashboard data-flow strategy

**Date**: 2026-09-16

## Status

Proposed

## Related ADRs

- [0004 – Visualisation tool for dashboards](0004-visualisation-tool-for-dashboards.md)
- [0007 – Data hosting architecture](0007-data-hosting-architecture.md)

## Context

Portal dashboards turn research-supplied data into Plotly figures that a page can show (ADR-0004). How that data *enters* the portal is a separate concern from how figures are drawn, and from how the portal discovers or hosts unit data bundles (ADR-0007).

In practice, dashboards do not share one ingestion shape:

- Most updating dashboards are fed by an editor with a single, modest source file. Figures can be produced as part of that editorial save and stored for later page views.
- Some dashboards are visitor-driven: the person viewing the page supplies the analysis file, and figures are computed for that session rather than once for everyone.
- Some historic dashboards no longer have a live generator. Their figures are stored as finished visualisation data and are not rebuilt from a source file on each edit.
- A smaller set of resource-style dashboards are fed by several large inputs, produce a large derived artefact set for download as well as figures, and cannot reasonably be absorbed or processed inside an editorial request.

A single “upload one file, generate figures in the same request, store only figures” path therefore cannot cover every dashboard we already operate. At the same time, visitors still meet dashboards in one place, and pages still expect a stable way to obtain figure data for a given dashboard.

This record describes the strategy we have already adopted, so that future dashboards can be placed on an existing path instead of inventing a new one by default.

## Decision

We use **several write paths** for getting data into dashboards, and **one read path** for serving figures on the public page.

### Write paths

Which write path a dashboard uses follows from the shape of its data, not from a preference for one pipeline.

**Editorial upload.** One source file, small enough to validate and parse during an admin save, whose useful output is figure JSON (and optionally that same file for visitor download). Generation runs as part of the save. Format may vary (for example a spreadsheet export, a zip of named workbooks, or a text table) as long as the “one file, request-sized, figures only” assumptions still hold.

**Offline preparation.** Several inputs, files too large for an editorial request, or a derived artefact set that must live on disk and be downloaded as files—not only as figures. Preparation is a deliberate, repeatable batch step. The page then reads the prepared figures and points downloads at the prepared artefacts.

**Visitor-time computation.** The chart depends on a file the visitor provides. Reference material may be bundled with the application; the visitor’s file is session-scoped and is not the editorial source of record for the dashboard.

**Authored figures.** There is no live generation step. Editors store finished figure data. Used for historic or frozen visualisations.

A dashboard may combine paths where the roles differ—for example a visitor-time analysis on the page, plus an editorial upload that only seeds curated examples.

### Read path

Regardless of how figures were produced, a public dashboard page resolves figure data by the page’s identity (its slug). It expects stored Plotly figure JSON, a public “data updated” date when we have one, and a digest of the inputs that produced the figures so caches and downloads can stay consistent.

Write paths that cannot share the editorial upload record still honour this read contract, so the page and figure blocks do not need a second rendering architecture.

### Placing a new dashboard

| Situation | Write path |
|-----------|------------|
| One file that fits an editorial save; output is figures | Editorial upload |
| Multiple large inputs and/or downloadable derived artefacts | Offline preparation |
| Each visitor’s file drives the chart | Visitor-time computation |
| Frozen visualisations, no generator | Authored figures |

Stretch the editorial-upload path only while its assumptions remain true. When they break, use another path rather than forcing the new shape through the same save cycle.

Large unit data bundles and repository-style discovery remain ADR-0007. They are not a substitute for dashboard figure ingestion.

## Consequences

### Positive

- Existing dashboards keep the ingestion model they already need, instead of being retrofitted onto a path that cannot carry their data.
- Public rendering stays uniform: pages look up figures the same way whether those figures came from an editor save, a batch preparation, or authored JSON.
- Future work has an explicit test: if the data still looks like “one modest file → figures”, extend editorial upload; if not, pick the matching path above.
- Operational cost stays where the data is small (synchronous editorial saves) and is accepted where the data is large (offline preparation).

### Negative

- There is more than one way to get data into a dashboard, so contributors must choose a path rather than always using the upload form.
- Offline preparation is a manual, operator-run step; it is not hidden behind the same editorial workflow as a CSV upload.
- The early dashboard plan’s assumption of a single synchronous upload path is no longer complete.

### Mitigation

- The table in this decision is the default placement guide; new dashboards should name their write path when they are designed.
- If many dashboards later need offline preparation, we can revisit automation (scheduled jobs, object storage for artefacts) without changing the read contract.
- ADR-0007 continues to cover hosting and discovery of large research bundles that are not dashboard visualisations.
