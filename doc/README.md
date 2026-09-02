# Documentation

Developer documentation and architecture decisions for `spp-wagtail`.

| Start here | |
|------------|---|
| **Developer docs** (setup, layout, how-tos) | [developer-docs/](developer-docs/README.md) |
| **Conventions** (rules + sources) | [dev-conventions.md](developer-docs/dev-conventions.md) |
| **Team decisions** (process, coding choices) | [decisions/](developer-docs/decisions/) |
| **Testing** | [testing.md](developer-docs/testing.md) |
| **Operations** (CI, migrations) | [operations.md](developer-docs/operations.md) |
| **Troubleshooting** | [troubleshooting.md](developer-docs/troubleshooting.md) |
| **Architecture decisions** (stack, system design) | [ADRs](architecture/decisions/) |
| **Quick clone / run** | [Project README](../README.md) |

---

## Architecture Decision Records

| ADR | Title |
|-----|--------|
| [0001](architecture/decisions/0001-record-architecture-decisions.md) | Record architecture decisions |
| [0002](architecture/decisions/0002-project-migration-from-hugo-to-python.md) | Hugo → Python migration |
| [0003](architecture/decisions/0003-formatting-rules.md) | Formatting rules |
| [0004](architecture/decisions/0004-visualisation-tool-for-dashboards.md) | Dashboard visualisation (Plotly) |
| [0005](architecture/decisions/0005-adopt-daisy-ui-for-ui-components.md) | DaisyUI |
| [0006](architecture/decisions/0006-adopt-wagtail-as-cms.md) | Wagtail as CMS |
| [0007](architecture/decisions/0007-data-hosting-architecture.md) | Data hosting |
| [0008](architecture/decisions/0008-use-django-structlog-for-logging.md) | Logging (structlog) |

Guides explain *how*; [team decisions](developer-docs/decisions/) record agreed choices; [ADRs](architecture/decisions/) record architecture. Link instead of copying bodies.

**Wagtail admin (editors):** use the [official Wagtail documentation](https://docs.wagtail.org/).

---

## References

- [Wagtail docs](https://docs.wagtail.org/)
- [Learn Wagtail — Best practices](https://learnwagtail.com/docs/best-practices/)
