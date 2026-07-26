# Static data storage strategy

## Decision

Generate the location-independent Hebcal corpus once for Hebrew years 1 through
6000, validate it, and preserve the resulting `corpus-v1` partitions as
immutable source data. Core rows are never regenerated or overwritten after
publication. A correction creates a new corpus version.

Large core tables use Zstandard-compressed Parquet in 100-Hebrew-year
partitions. Small manifests and lookup tables use JSON or UTF-8 CSV. DuckDB is
the one-time population and validation engine. Its working database remains
disposable; the landed Parquet partitions are the durable source.

Power BI should use Import mode with slim expressions that read the landed
partitions and apply only explicit types and intentional filters. New
transformations and relationships may evolve without modifying the core
partitions.

## Why not PostgreSQL now

PostgreSQL is an excellent operational database, but this project currently
has small, effectively immutable datasets and no scheduled refresh
requirement. A server would introduce service lifecycle, credentials, backups,
network availability, and Power BI gateway configuration without removing the
need to materialize stable tables.

Adopt PostgreSQL later if the requirements change to include concurrent
writes, several applications querying the same live state, row-level
transactional updates, or unattended refresh from an always-on host.

## Why Parquet at the Power BI boundary

- The full day spine contains 2,191,465 rows before event and reading tables.
- Columnar compression avoids the repeated text and parsing cost of CSV.
- Power Query can read local Parquet directly without an ODBC driver.
- Partition files are immutable; Git's poor binary-diff behavior is therefore
  not multiplied by repeated rebuilds.
- Explicit typing remains defined in the corpus schema and semantic model.

Small human-maintained lookup and compatibility tables may still use CSV.

## Intended repository layout

```text
data/
  hebcal/
    corpus-v1/
      block=0001-0100/
      ...
      block=5901-6000/
scripts/
  hebcal/
    corpus-v1.json       # immutable scope and version contract
    generate_corpus.mjs  # pinned local Hebcal generator
    proleptic_hebcal.mjs # negative-absolute-day compatibility layer
    build_corpus.py      # one-time DuckDB population
    hebcal_api.py        # REST sampling and verification helper
    sql/                 # derived transformations
```

Partitions enter `data/` only after their schema, row counts, key continuity,
boundary behavior, package versions, and checksums have been verified. The
builder refuses to overwrite a completed partition. Temporary pilots belong
outside the repository, such as `G:\Projects\tmp\hebcal-corpus`.

The full historical corpus uses `absolute_day` as its relationship key. Dates
before March 1900 are stored as signed Gregorian components and display text,
not as Power BI native dates.

## Migration sequence

1. Lock `corpus-v1` and the exact Hebcal package versions.
2. Populate and validate boundary and modern pilot blocks.
3. Populate all 60 immutable blocks and publish their checksummed manifest.
4. Add new corpus-backed semantic tables alongside the existing workbook
   tables.
5. Compare overlapping rows and switch one existing partition at a time.
6. Refresh and validate the model in Desktop after each cutover.
7. Retain each workbook until every dependent query has migrated and passed
   comparison.
