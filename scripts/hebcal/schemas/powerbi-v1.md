# Power BI materialization v1

`data/hebcal/powerbi-v1` is the one-time, model-ready derivative of finalized
`corpus-v1`. It is narrow enough for efficient Power BI import and contains no
logic that must be rerun on a schedule. The lossless core remains unchanged.

## Build and immutability contract

Run from the repository root:

```powershell
G:\Projects\.venv\Scripts\python.exe scripts\hebcal\materialize_powerbi.py
```

The command verifies the root provenance, partition manifests, and all 180
source Parquet checksums it reads. It builds in a sibling staging directory,
validates the landed Parquet, and renames the completed artifact atomically.
The destination must not exist, and there is no force or overwrite option.

Parquet files and `manifest.json` are deterministic under the pinned DuckDB
1.5.5 contract. `provenance.json` contains the build timestamp and the
deterministic manifest checksum. A changed table shape, key rule, or
transformation creates `powerbi-v2`; it never rewrites `powerbi-v1` or
`corpus-v1`.

## Schedule key

The shared schedule key is fixed:

| `schedule_key` | Schedule |
| ---: | --- |
| 0 | Diaspora |
| 1 | Israel |

## `hebrew_day_schedule.parquet`

One row per `absolute_day` and `schedule_key`:

- `absolute_day` (`INTEGER`)
- `schedule_key` (`TINYINT`)
- `hallel_level` (`TINYINT`, values 0 through 2)
- `tachanun_shacharit` (nullable `BOOLEAN`)
- `tachanun_mincha` (nullable `BOOLEAN`)
- `tachanun_all_congregations` (nullable `BOOLEAN`)
- `tachanun_supported` (`BOOLEAN`)
- `eruv_tavshilin` (`BOOLEAN`)

The three Tachanun values are null exactly when `tachanun_supported` is false.
That is 710 year-1 rows in corpus-v1, caused by the upstream year-0 dependency.

Production validation:

- 4,382,930 unique `(absolute_day, schedule_key)` rows.
- 2,191,465 rows for each schedule.
- No null required keys or orphan dates.

## `hebcal_event_definition.parquet`

One row per distinct tuple:

`event_class`, `event_description`, `event_basename`, `event_flags`,
`title_en`, `title_he`, `title_ashkenazi`.

`event_definition_key` is a dense, one-based `INTEGER`. Stable assignment uses
UTF-8 byte ordering for every text member, explicit null ordering, and numeric
ordering for `event_flags`. The null-safe tuple is the complete identity; no
hash value is used as a relationship key.

Production validation:

- 142,603 definitions and keys 1 through 142,603.
- Definition fingerprint:
  `108ea0bfffe3e5fe214a1fe3e6dc4bf4cb9e85d36f230adb2f42453b5a5b47b6`.

## `hebcal_event_occurrence.parquet`

One row per schedule-specific event occurrence:

- `absolute_day` (`INTEGER`)
- `schedule_key` (`TINYINT`)
- `event_definition_key` (`INTEGER`)

Production validation:

- 2,037,895 unique composite rows.
- 1,027,106 Diaspora rows and 1,010,789 Israel rows.
- No null keys, day orphans, or event-definition orphans.

The source `occurrence_id`, URL, and canonical event JSON remain available in
`corpus-v1`; they are intentionally absent from this narrow model boundary.

## Semantic-model relationships

Use these one-to-many relationships:

- Hebrew day (`absolute_day`) to day schedule.
- Hebrew day (`absolute_day`) to event occurrence.
- Schedule (`schedule_key`) to both facts.
- Event definition (`event_definition_key`) to event occurrence.

Import these static files once. After a successful model load and relationship
validation, mark the associated partitions as excluded from ordinary refresh.
Only a new materialization version needs to be loaded when transformations or
relationships change.
