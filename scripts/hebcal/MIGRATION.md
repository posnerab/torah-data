# Immutable corpus migration

## Population

1. Freeze `corpus-v1.json`, package locks, generator, builder, schemas, and
   validators in a source commit.
2. Build boundary and modern pilots outside the repository.
3. Populate all 60 blocks under `data/hebcal/corpus-v1`.
4. Verify every file hash, the gapless absolute-day spine, global uniqueness,
   source-package consistency, and occurrence foreign keys.
5. Write the timestamp-free root content manifest and its separate provenance
   file. This finalizes the corpus and prevents additional partitions.
6. Preserve the finalized corpus in a second verified location. Future
   consumers download or copy and verify it; they do not regenerate it.

The 100-year blocks are durable population checkpoints. Rebuildable
Power-BI-facing transformations may coalesce them into one file per table for
faster reads.

## Semantic-model cutover

The existing `Hebcal` table is a modern, diaspora-only, one-row-per-day
projection—not an event-occurrence table. Keep its table object, columns,
calculated columns, measures, and lineage intact.

1. Build derived normalized tables from immutable core:
   Hebrew Calendar, Schedule, Event Definition/Occurrence, Parasha Occurrence,
   and Reading Definition/Occurrence/Aliyah.
2. Load them hidden and side-by-side without changing existing relationships.
3. Replace Dates and leap/common indexes with compatible corpus-derived
   projections.
4. Build a modern diaspora compatibility projection with the existing
   `Hebcal` source schema and compare all 18,987 overlapping rows.
5. Change only the existing `Hebcal` partition after a full outer comparison,
   complete-column hashes, DAX checks, partition refresh, and Desktop save.
6. Migrate visuals and relationships gradually to normalized tables.
7. Remove a workbook or named expression only when no model or report
   dependency remains.

## Data that remains separate

- `Pasukim`, `Parashiyos`, mitzvos, and curated parasha mappings.
- US business/vacation logic in `Holidays`.
- Curated fast-day and haftarah metadata unless exact equivalence is proven.
- Zmanim descriptions and location/current-date Milwaukee calculations.
- Personal yahrzeit, birthday, or anniversary inputs.
- Daily-learning schedules, which require their own bounded immutable corpus
  versions.
