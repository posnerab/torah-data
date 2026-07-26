# Immutable data operations

## Operating rule

The landed version directories are durable data products, not build caches.
After a directory has a complete manifest:

- do not rerun its population command;
- do not add, replace, or edit files inside it;
- verify and copy the landed files when moving machines;
- publish a new version when the source contract or transformation changes.

Changing DAX, relationships, report visuals, or downstream transformations
does not require regenerating an existing data version.

## Data surfaces

| Surface | Purpose | Normal refresh |
| --- | --- | --- |
| `data/hebcal/corpus-v1` | Hebrew years 1-6000 core | Never |
| `data/hebcal/powerbi-v1` | Normalized schedule and event tables | Never |
| `data/hebcal/powerbi-readings-v1` | Normalized Parasha and leyning tables | Never |
| `data/hebcal/powerbi-compatibility-v1` | Exact legacy `Hebcal` report contract | Never |
| `data/powerbi-static-v1` | Small curated semantic-model tables | Never |
| `Zmanim` semantic-model surface | Current Milwaukee times and comparisons | On demand or scheduled |

Static Import tables use `excludeFromModelRefresh`. A new Desktop model or a
relocated artifact still needs one explicit table or partition refresh to load
the data. After that targeted load succeeds, ordinary Refresh All operations
leave the static rows untouched.

## Relocating or restoring the data

1. Copy the complete version directories; do not run the generators.
2. Verify every copied file against its committed manifest.
3. Update only the semantic-model path parameter for the new repository
   location.
4. Refresh each affected static partition explicitly once.
5. Confirm row counts, relationship integrity, and representative DAX results.
6. Keep the tables excluded from ordinary refresh.

The source manifests and landed Parquet files are sufficient for recovery.
Disposable DuckDB files, API responses, and exporter staging directories are
not recovery inputs.

## Publishing a changed contract

For a new data type, corrected transformation, or changed table grain:

1. Leave every existing version directory unchanged.
2. Define a new schema and output directory such as `powerbi-v2`.
3. Read the immutable upstream version; never rewrite it in place.
4. Materialize and validate the new version side by side.
5. Compare complete rows in both directions, including nulls and duplicates.
6. Cut over only the intended partitions, relationships, or report bindings.
7. Refresh those partitions once and then exclude them from routine refresh.

If only DAX, relationships, or visuals change, skip data materialization and
edit the semantic model or report directly.

## Refresh boundary

Scheduled refresh is not required for the immutable data. If current Zmanim
must update unattended, target that small surface; do not re-enable refresh on
the static tables. `TODAY()`-dependent calculated columns are a separate model
concern: migrate them to measures or another small recalculated surface rather
than refreshing millions of immutable date rows.
