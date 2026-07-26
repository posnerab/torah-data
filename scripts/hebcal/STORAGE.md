# Static data storage strategy

## Decision

Materialize the model-ready tables before Power BI refresh and commit them as
small UTF-8 CSV snapshots. Keep the corresponding raw Hebcal responses as JSON
when provenance or reprocessing matters.

Use source-controlled Python and SQL under `scripts/` to regenerate those
snapshots. DuckDB may be used as a local, disposable build database for joins,
window functions, schema checks, and CSV exports. Its database file is ignored
because it must be reproducible from committed inputs and transformations.

Power BI should use Import mode with slim Power Query expressions:

1. download a model-ready CSV from the repository;
2. apply explicit column types;
3. load it without repeating workbook or API transformation logic.

## Why not PostgreSQL now

PostgreSQL is an excellent operational database, but this project currently
has small, effectively immutable datasets and no scheduled refresh
requirement. A server would introduce service lifecycle, credentials, backups,
network availability, and Power BI gateway configuration without removing the
need to materialize stable tables.

Adopt PostgreSQL later if the requirements change to include concurrent
writes, several applications querying the same live state, row-level
transactional updates, or unattended refresh from an always-on host.

## Why CSV at the Power BI boundary

- Power Query can read a repository-hosted CSV through its built-in web and CSV
  functions without an ODBC driver or custom connector.
- The data is small enough that CSV size and scan cost are negligible.
- Text diffs are reviewable, and agents can edit or regenerate individual
  tables.
- Explicit typing stays visible in the semantic model.

Parquet remains a good optional local interchange or archive format, but Power
Query's documented Parquet connector is designed around local files, Azure
Blob Storage, and Azure Data Lake Storage Gen2. Repository-hosted web files
therefore make CSV the less fragile boundary here.

## Intended repository layout

```text
data/
  hebcal/
    raw/             # deterministic API JSON snapshots
    model/           # model-ready CSV tables
scripts/
  hebcal/
    hebcal_api.py    # API client and focused CLI
    sql/             # future DuckDB transformation queries
```

Generated snapshots should enter `data/` only after their date range, schema,
row count, and comparison with the current semantic model have been verified.
Temporary API experiments belong outside the repository, such as
`G:\Projects\tmp\hebcal`.

## Migration sequence

1. Inventory one existing workbook query and its downstream model columns.
2. Capture raw inputs and materialize an equivalent CSV.
3. Compare row counts, keys, nulls, and representative values with the live
   semantic model.
4. Replace only that Power Query partition with the typed CSV loader.
5. Refresh and validate the model in Desktop, save, and commit the isolated
   batch.
6. Retain the workbook until every dependent query has migrated and passed
   comparison.
