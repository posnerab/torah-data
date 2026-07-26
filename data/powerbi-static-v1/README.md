# Power BI static compatibility data

`powerbi-static-v1` is the immutable, exact imported-column snapshot for six
small curated tables in the `T-Projects` semantic model:

| Table | Rows | Imported columns |
| --- | ---: | ---: |
| `Holidays` | 98 | 15 |
| `Pasukim` | 5,863 | 22 |
| `Parashiyos` | 61 | 13 |
| `Fast Days` | 14 | 7 |
| `Haftaros` | 78 | 16 |
| `Parasha-Mitzvos` | 781 | 29 |

The six Parquet files contain 6,895 rows and 102 imported columns in total.
They preserve the values already loaded in the validated Power BI Desktop
model, including nulls, empty strings, data types, and duplicates. This is a
semantic-model compatibility boundary, not a replacement canonical source for
the underlying Torah or holiday domains.

`manifest.json` binds every file to the live-model export contract and records
complete `EXCEPT ALL` validation in both directions. `provenance.json` keeps
the timestamped build metadata separate from the deterministic content
manifest.

These files are loaded once and excluded from ordinary semantic-model refresh.
Do not edit, replace, or regenerate this directory. A corrected source,
transformation, or imported-column contract creates `powerbi-static-v2`.
Changes limited to DAX, relationships, or report visuals do not require a new
data version.

See
[`scripts/hebcal/OPERATIONS.md`](../../scripts/hebcal/OPERATIONS.md)
for relocation and recovery, and
[`scripts/powerbi/README.md`](../../scripts/powerbi/README.md)
for the one-time export and materialization workflow.
