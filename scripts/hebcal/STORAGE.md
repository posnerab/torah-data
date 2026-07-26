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
    powerbi-v1/
      hebrew_day_schedule.parquet
      hebcal_event_definition.parquet
      hebcal_event_occurrence.parquet
      manifest.json
      provenance.json
    powerbi-readings-v1/
      parasha_definition.parquet
      parasha_definition_member.parquet
      parasha_occurrence.parquet
      leyning_reading_definition.parquet
      leyning_definition_parasha.parquet
      leyning_segment_definition.parquet
      leyning_occurrence.parquet
      manifest.json
      provenance.json
scripts/
  hebcal/
    corpus-v1.json       # immutable scope and version contract
    generate_corpus.mjs  # pinned local Hebcal generator
    proleptic_hebcal.mjs # negative-absolute-day compatibility layer
    build_corpus.py      # one-time DuckDB population
    materialize_powerbi.py # one-time narrow Power BI projection
    materialize_powerbi_readings.py # separate one-time readings projection
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

The `powerbi-v1` derivative is independently immutable. It removes source
payload JSON and repeated event text from occurrence rows while retaining the
lossless fields in `corpus-v1`. Its manifest binds the derivative to the exact
corpus manifest and builder version. A changed projection lands under a new
versioned directory.

`powerbi-readings-v1` is a second, independently immutable derivative. It
normalizes the Parasha and leyning definition/member/passage structures and
keeps the two occurrence tables narrow. Its seven Parquet files are imported
once and excluded from scheduled semantic-model refresh. Raw JSON stays in
`corpus-v1`; only normalized localized passage fields cross this boundary.
`materialize_powerbi.py` and `powerbi-v1` remain unchanged. A new reading data
type or transformation contract lands under `powerbi-readings-v2` instead of
regenerating v1.

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
