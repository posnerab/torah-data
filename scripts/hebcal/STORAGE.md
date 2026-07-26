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
    powerbi-compatibility-v1/
      hebcal_compatibility.parquet
      manifest.json
      provenance.json
  powerbi-static-v1/
    tables/
      holidays.parquet
      pasukim.parquet
      parashiyos.parquet
      fast_days.parquet
      haftaros.parquet
      parasha_mitzvos.parquet
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
    materialize_powerbi_compatibility.py # exact legacy cutover snapshot
    materialize_powerbi_static_snapshots.py # six curated compatibility tables
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

`powerbi-compatibility-v1` is an immutable cutover shim rather than another
all-years normalized table. It captures the 87 imported columns and 18,987
one-row-per-date records currently loaded in `Hebcal`, including the finite
2025–2027 Zmanim overlay. This preserves the table's calculated columns,
measures, hierarchy, relationships, lineage, and report references while its
large workbook query is retired. Known legacy formatting and workbook errors
remain isolated in the shim; they do not alter the correct normalized
`corpus-v1` data. Later cleanup creates a narrower v2 instead of rewriting v1.

`powerbi-static-v1` is a separate immutable compatibility boundary for six
small curated semantic tables that do not belong in the all-years Hebcal
corpus. It preserves the exact 102 imported-column values across 6,895 live
model rows. The one-time exporter binds the snapshot to the TMDL contracts;
the materializer verifies the source hashes and compares every output row in
both directions. These Parquet files replace repeated Excel and Power Query
processing without introducing a database service.

## Migration sequence

1. Lock `corpus-v1` and the exact Hebcal package versions.
2. Populate and validate boundary and modern pilot blocks.
3. Populate all 60 immutable blocks and publish their checksummed manifest.
4. Add new corpus-backed semantic tables alongside the existing workbook
   tables.
5. Export and materialize the exact loaded `Hebcal` compatibility snapshot.
6. Load it side-by-side, compare all 87 imported columns, then switch only the
   existing `Hebcal` partition.
7. Export and materialize the six curated semantic tables as
   `powerbi-static-v1`, then compare and switch their existing partitions.
8. Refresh and validate the model in Desktop after each cutover.
9. Retain each workbook until every dependent query has migrated and passed
   comparison.
