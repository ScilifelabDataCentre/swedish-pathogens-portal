# Inline type hinting at empty init

**Decision to be made:** Should empty object initialisation in Python use inline type hints?

**Logic:** Several developers prefer inline annotations at collection init sites (not only on “complex” functions). A single rule keeps the codebase consistent and makes empty `{}` / `[]` intent obvious under stricter typing (Ruff ANN, [ADR-0003](../../architecture/decisions/0003-formatting-rules.md)).

**Status:** decision

**Decision:** Yes — annotate the variable when initiating an empty object.

```python
foo_list: list[str] = []
foo_dict: dict[str, str] = {}
foo_tuple: tuple[int, ...] = ()
foo_set: set[str] = set()
```

Use correct element and key types (e.g. `dict[str, PageQuerySet]`, not `dict[str, list[PageQuerySet]]` when values are querysets).

**Where can I find the outcome of this decision?**

- Code: e.g. `cms/pages/catalogue.py`, `cms/pages/dashboard_index.py`, `cms/services/validators.py`
- PR: [#49](https://github.com/ScilifelabDataCentre/spp-wagtail/pull/49)
- Convention summary: [Typing](../dev-conventions.md#typing)
