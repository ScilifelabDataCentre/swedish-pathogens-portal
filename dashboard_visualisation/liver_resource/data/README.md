# DINA Liver Resource — bundled reference data

Static reference model for the Liver Resource dashboard. Loaded server-side only; not served as public static files.

## Source (102-module network — 24 June 2026 / Multi-DE active package)

| File | Origin |
|------|--------|
| `tln_graph.json` | Export from `ITA_Liver_resource/DINA-Liver-Clean/data/TLNgraph_102.RDS` via `export_rds_to_json.R` |
| `TLN.EdgeList.csv.cyjs` | `DINA-Liver-Clean/data/TLN.EdgeList_102.csv.cyjs` (filename kept) |
| `hsapiens.SYMBOL.txt` | `DINA-Liver-Clean/data/` |
| `ITA.Liver.ModNames.2025.txt` | Contents from `ITA.Liver.ModNames_102.txt` (filename kept for code compatibility) |
| `modules/Module.*.txt` | `DINA-Liver-Clean/data/Modules_102/` (**directory name stays `modules/`**) |
| `examples/*.txt` | `DINA-Liver-Clean/example-DE-files/` |
| `DE_upload_template.txt` | Header + sample rows from HCC-Control example |

## Expected counts

- TLN vertices: **203** (102 leaf modules + 101 internal tree nodes)
- TLN edges: **202**
- Modules: **102**

Note: the 102 RDS stores raw gene counts in `Ngenes` and `size` as √Ngenes (R plot convention). Plotly uses `Ngenes` when present for marker size / hover.

## Updating

When researchers deliver a new data package:

1. Re-export `tln_graph.json` from the new `TLNgraph*.RDS`
2. Replace cyjs + `modules/` contents (keep the `modules/` directory name)
3. Re-run parity tests against R reference outputs
4. Update expected counts in `reference_data.py` and this README
5. Re-save Wagtail `DashboardData` (`liver-resource`) so base/example figures regenerate

## Configuration

Override the data root in development or tests via `LIVER_RESOURCE_DATA_ROOT` in settings or environment.
