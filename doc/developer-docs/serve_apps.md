# Models and apps page (SciLifeLab Serve)

The Models and apps page (`ServeAppsPage`) lists the pathogen-related public apps and models
hosted on [SciLifeLab Serve](https://serve.scilifelab.se/), with a search box, facets and
sorting styled like the Genomic data page.

## Data source

Serve's open API returns every public app and model in one response:
`GET https://serve.scilifelab.se/openapi/v1/public-apps` (see the
[Serve API documentation](https://serve.scilifelab.se/docs/api-documentation/)). Models are
listed in the same endpoint as apps; there is no separate models endpoint.

The parsed list is cached for an hour (`portal_data.serve_apps.CACHE_TTL_SECONDS`). Failed
fetches are not cached, and the page shows an error message instead of the listing.

Items are skipped if they have no ID, name or http(s) URL, are not public, or have the status
`Deleted`.

## Which apps are shown

An app is shown when its name or description matches a keyword in
`portal_data/metabolights/pathogen_infectious_disease_keywords_just_keywords.csv`, the same
list the MetaboLights publication search uses. As there, short all-caps abbreviations (e.g.
`AMR`) match case-sensitively, and a match on a weak keyword alone (`host`, `strain`, ...)
doesn't count.

Editors can adjust the result in the page's **Serve apps** block, by Serve app ID:

- **Always show**: apps the keywords miss.
- **Never show**: false positives. This wins if an ID is in both lists.

Each app card shows its Serve ID.

## Code layout

```text
portal_data/serve_apps.py          Fetching, parsing, keyword matching, caching
cms/services/serve_apps.py         Request state, search, facets, sorting, template context
cms/blocks/serve_apps.py           ServeAppsBlock (editor include/exclude lists)
cms/pages/serve_apps.py            ServeAppsPage (full page, or the listing for HTMX requests)
cms/templates/cms/blocks/serve_apps.html
cms/templates/cms/pages/serve_apps/partials/serve_listing.html
```

Searching, filtering and sorting happen in Python on the cached list, as the whole catalogue
is only a few hundred items. Facet values within a facet are OR-ed, facets are AND-ed, and
each facet's counts are computed without its own selection.
