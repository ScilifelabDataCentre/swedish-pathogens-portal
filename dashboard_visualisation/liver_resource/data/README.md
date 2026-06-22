# DINA Liver Resource — bundled reference data

Static reference model for the Liver Resource dashboard. Loaded server-side only; not served as public static files.

## Source

| File | Origin |
|------|--------|
| `tln_graph.json` | One-time export from `TLNgraph.RDS` via `ITA_Liver_resource/phase-3-investigation/t3_1_data_loading/export_rds_to_json.R` |
| `TLN.EdgeList.csv.cyjs` | `ITA_Liver_resource/DINA-Liver-Clean/data/` |
| `hsapiens.SYMBOL.txt` | `ITA_Liver_resource/DINA-Liver-Clean/data/` |
| `ITA.Liver.ModNames.2025.txt` | `ITA_Liver_resource/DINA-Liver-Clean/data/` |
| `modules/Module.*.txt` | `ITA_Liver_resource/DINA-Liver-Clean/data/Modules/` (105 files) |
| `examples/*.txt` | `ITA_Liver_resource/DINA-Liver-Clean/example-DE-files/` (3 curated datasets) |
| `DE_upload_template.txt` | Header + sample rows from HCC-Control example |

## Expected counts

- TLN vertices: 209 (105 leaf modules + 104 internal tree nodes)
- TLN edges: 208
- Modules: 105

## Updating

When researchers deliver a new data package:

1. Re-export `tln_graph.json` from the new `TLNgraph.RDS`
2. Replace cyjs, modules, and symbol files from the new package
3. Re-run parity tests against R reference outputs
4. Update this README with the package version/date

## Configuration

Override the data root in development or tests via `LIVER_RESOURCE_DATA_ROOT` in settings or environment.
