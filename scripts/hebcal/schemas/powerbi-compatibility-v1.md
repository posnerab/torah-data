# Power BI compatibility materialization v1

`data/hebcal/powerbi-compatibility-v1` is the exact, immutable bridge between
the current workbook-backed `Hebcal` table and its future static Parquet
partition. It preserves the existing semantic and report contract while the
normalized Hebrew years 1–6000 data remains in `corpus-v1`, `powerbi-v1`, and
`powerbi-readings-v1`.

## Scope

- Grain: one row per Gregorian `Date`.
- Rows and unique dates: 18,987.
- Date range: 2023-09-16 through 2075-09-09.
- Hebrew years: 5784 through 5835.
- Imported columns: all 87 existing `Hebcal` data columns, in their existing
  order and types.
- Zmanim overlay: the 1,095 already-loaded Milwaukee rows from 2025-01-01
  through 2027-12-31; other compatibility dates retain their existing nulls.

This finite horizon is intentional. The legacy table depends on native
Gregorian dates, automatic date tables, current-date DAX, and one-row-per-date
Diaspora semantics. The normalized absolute-day tables hold the authoritative
all-years data, including BCE dates that cannot be represented in the legacy
shape.

## One-time source

`scripts/powerbi/Export-HebcalCompatibilitySnapshot.ps1` queries the exact open
`T-Projects` model through its local Analysis Services endpoint. It reads the
data-column contract from `Hebcal.tmdl`, exports only imported columns with a
date-ordering DAX query, and writes:

- `hebcal_compatibility.jsonl`
- `schema.json`
- `provenance.json`

Null and empty string remain distinct. Numeric, Boolean, and DateTime values
remain typed. The exporter writes through staging, requires 87 columns and
18,987 rows, and has no overwrite path.

The source snapshot is a one-time validation input outside the repository.
The landed Parquet and its manifest are the durable model boundary.

## Landed file

`hebcal_compatibility.parquet` has the exact imported-column names used by the
existing table. `materialize_powerbi_compatibility.py`:

1. verifies the source schema and provenance hashes;
2. casts all 87 fields explicitly;
3. requires unique, non-null, gapless daily dates;
4. validates the date, Hebrew-year, and Zmanim bounds;
5. writes one Zstandard-compressed Parquet file with one DuckDB thread;
6. reads the landed Parquet back and repeats validation; and
7. atomically publishes only when the destination does not exist.

The official source JSONL fingerprint is:

```text
df72a72b36e2a75e0c6cb6d5ec4dc7956f0a412a629dc8acfc861a16057c5e47
```

The official source schema fingerprint is:

```text
288aa02dc36367cce18b1653b9ab700263423347e85e4f4671c8973e51ed5aaa
```

The landed Parquet fingerprint is:

```text
c59883945e95976966effe17a5107716e0117b23a8aff32b1f1e445517dbb730
```

The deterministic content-manifest fingerprint is:

```text
a2c52df3ea947c51399f7f1225820552b08743bf5588ae1982d71f3dee0029fb
```

## Cutover contract

Load the Parquet into a temporary hidden comparison table first. Before
changing `Hebcal`, require:

- exact 18,987-row and date bounds;
- null-aware equality for every one of the 87 imported columns;
- zero forward and reverse set differences;
- all existing relationships in `Ready` state;
- focused DAX checks for current report calculations; and
- saved Desktop source plus report render verification.

Then change only the existing `Hebcal` partition to a slim Parquet expression.
Keep its table, columns, calculated columns, measures, hierarchy, lineage, and
relationships intact. Mark the static partition excluded from ordinary model
refresh.

Compatibility v1 intentionally preserves existing spellings, concatenation
order, blank semantics, Zmanim snapshot, and known workbook errors. Correct
normalized values remain untouched. A later coordinated schema cleanup creates
`powerbi-compatibility-v2`; it never rewrites v1 or any core corpus data.
