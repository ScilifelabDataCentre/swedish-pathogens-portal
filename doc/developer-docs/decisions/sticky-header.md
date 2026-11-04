# Header functionality (sticky / scroll)

**Decision to be made:** Should the site header be sticky, and how should it behave on scroll?

**Logic:** Sticky navigation helps orientation; collapsing on scroll (as on scilifelab.se) reduces clutter while reading.

**Status:** decision

**Decision:** Header is **sticky** and **hides on scroll down / reappears as appropriate** (implemented on the live site). Preserve this behaviour when changing header/nav templates or CSS.

**Where can I find the outcome of this decision?**

- Confluence: [Header functionality](https://scilifelab.atlassian.net/wiki/spaces/TE/pages/4245192706/Header+functionality)
- Code: header / navigation templates under `cms/templates/cms/`
