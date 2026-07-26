# `powerbi-readings-v1` schema

`powerbi-readings-v1` is the immutable, relationship-ready Parasha and leyning
projection of the finalized `corpus-v1`. The seven Zstandard-compressed Parquet
files contain no raw event or reading JSON. They are generated once, imported
once, and excluded from routine Power BI refresh.

All definition keys and member/segment indexes are one-based. `schedule_key`
is `0` for Diaspora and `1` for Israel. Source `reading_index` remains
zero-based.

## Files and grains

### `parasha_definition.parquet`

| Column | Parquet type | Null |
| --- | --- | --- |
| `parasha_definition_key` | `INTEGER` | no |
| `is_combined` | `BOOLEAN` | no |
| `title_en` | `VARCHAR` | no |
| `title_he` | `VARCHAR` | no |
| `title_ashkenazi` | `VARCHAR` | no |
| `basename` | `VARCHAR` | no |

Grain: `parasha_definition_key`. There are 60 rows and dense keys 1-60:
53 single and 7 combined definitions.

### `parasha_definition_member.parquet`

| Column | Parquet type | Null |
| --- | --- | --- |
| `parasha_definition_key` | `INTEGER` | no |
| `member_index` | `TINYINT` | no |
| `parasha_name` | `VARCHAR` | no |

Grain: `(parasha_definition_key, member_index)`. There are 67 rows: 60 at
index 1 and 7 at index 2, with 53 distinct member names and no definition
orphans.

### `parasha_occurrence.parquet`

| Column | Parquet type | Null |
| --- | --- | --- |
| `absolute_day` | `INTEGER` | no |
| `schedule_key` | `TINYINT` | no |
| `parasha_definition_key` | `INTEGER` | no |

Grain: `(absolute_day, schedule_key)`. There are 588,052 rows: 292,328
Diaspora and 295,724 Israel. Day, schedule, and definition orphan counts are
zero.

### `leyning_reading_definition.parquet`

| Column | Parquet type | Null |
| --- | --- | --- |
| `reading_definition_key` | `INTEGER` | no |
| `source_payload_sha256` | `VARCHAR` | no |
| `reading_type` | `VARCHAR` | no |
| `name_en` | `VARCHAR` | no |
| `name_he` | `VARCHAR` | no |
| `summary` | `VARCHAR` | yes |
| `summary_he` | `VARCHAR` | yes |
| `summary_ashkenazi` | `VARCHAR` | yes |

Grain: `reading_definition_key`; `source_payload_sha256` is also unique.
There are 269 rows and dense keys 1-269: 123 `shabbat`, 85 `holiday`, and 61
`weekday`. Each summary column has exactly one null definition.

### `leyning_definition_parasha.parquet`

| Column | Parquet type | Null |
| --- | --- | --- |
| `reading_definition_key` | `INTEGER` | no |
| `member_index` | `TINYINT` | no |
| `parasha_name` | `VARCHAR` | no |
| `parasha_number` | `SMALLINT` | no |

Grain: `(reading_definition_key, member_index)`. There are 202 rows: 184 at
index 1 and 18 at index 2. Parasha numbers span 1-54; 184 definitions are
represented and 85 legitimately have no Parasha member.

### `leyning_segment_definition.parquet`

| Column | Parquet type | Null |
| --- | --- | --- |
| `reading_definition_key` | `INTEGER` | no |
| `segment_kind` | `VARCHAR` | no |
| `segment_label` | `VARCHAR` | no |
| `segment_index` | `TINYINT` | no |
| `book_en` | `VARCHAR` | no |
| `book_he` | `VARCHAR` | no |
| `book_ashkenazi` | `VARCHAR` | no |
| `begin_ref_en` | `VARCHAR` | no |
| `begin_ref_he` | `VARCHAR` | no |
| `begin_ref_ashkenazi` | `VARCHAR` | no |
| `end_ref_en` | `VARCHAR` | no |
| `end_ref_he` | `VARCHAR` | no |
| `end_ref_ashkenazi` | `VARCHAR` | no |
| `verse_count` | `SMALLINT` | yes |
| `parasha_number` | `SMALLINT` | yes |
| `reason_en` | `VARCHAR` | yes |
| `reason_he` | `VARCHAR` | yes |
| `reason_ashkenazi` | `VARCHAR` | yes |
| `note_en` | `VARCHAR` | yes |
| `note_he` | `VARCHAR` | yes |
| `note_ashkenazi` | `VARCHAR` | yes |

Grain: `(reading_definition_key, segment_kind, segment_index)`. The 2,265
rows split as follows:

| `segment_kind` | Rows | Maximum index |
| --- | ---: | ---: |
| `alt` | 24 | 6 |
| `chabad` | 18 | 2 |
| `fullkriyah` | 1,387 | 9 |
| `haft` | 182 | 3 |
| `megillah` | 168 | 12 |
| `seph` | 59 | 4 |
| `summaryParts` | 244 | 4 |
| `weekday` | 183 | 3 |

`summaryParts` accounts for all 244 null `verse_count` values. The other
2,021 rows require a count. `parasha_number` is present on 473 rows. Each
localized reason column has 190 populated rows; each localized note column has
one. Definition orphan count is zero.

### `leyning_occurrence.parquet`

| Column | Parquet type | Null |
| --- | --- | --- |
| `absolute_day` | `INTEGER` | no |
| `schedule_key` | `TINYINT` | no |
| `reading_index` | `TINYINT` | no |
| `reading_definition_key` | `INTEGER` | no |

Grain: `(absolute_day, schedule_key, reading_index)`. There are 2,339,622
rows: 1,172,415 Diaspora and 1,167,207 Israel. Reading indexes 0, 1, and 2
contain 2,234,361, 97,091, and 8,170 rows respectively. Day, schedule, and
definition orphan counts are zero.

## Deterministic keys and passage flattening

Parasha definitions sort by the UTF-8 bytes of compact JSON for the ordered
member array, then `is_combined`, localized titles, and basename. Reading
definitions sort by `source_payload_sha256`. Both key spaces are dense and
one-based.

Recognized passage roots are exactly `alt`, `chabad`, `fullkriyah`, `haft`,
`megillah`, `seph`, `summaryParts`, and `weekday`. Keyed objects retain their
source label; numeric labels sort numerically and `M` follows them. A single
range object receives label `1`; array entries receive one-based ordinal
labels. `segment_index` is dense within reading definition and kind.

English, Hebrew, and Ashkenazi payloads must have identical range paths and
numeric `v`/`p` values. Localized book, begin, end, reason, and leaf note text
is preserved separately. Unknown JSON roots, unknown range paths or fields,
and locale structural mismatches fail the build.

## Frozen content fingerprints

Fingerprints use `sha256(string_agg(to_json(struct_pack(...)), chr(10) ORDER
BY grain))`: one LF between rows and no trailing LF. The canonical struct
aliases and ordering are:

| Table | `struct_pack` fields in order | Aggregate order |
| --- | --- | --- |
| `parasha_definition` | `k := parasha_definition_key`, `c := is_combined`, `en := title_en`, `he := title_he`, `a := title_ashkenazi`, `b := basename` | `parasha_definition_key` |
| `parasha_definition_member` | `k := parasha_definition_key`, `i := member_index`, `n := parasha_name` | `parasha_definition_key, member_index` |
| `leyning_reading_definition` | `k := reading_definition_key`, `h := source_payload_sha256`, `t := reading_type`, `en := name_en`, `he := name_he`, `s := summary`, `she := summary_he`, `sa := summary_ashkenazi` | `reading_definition_key` |
| `leyning_definition_parasha` | `k := reading_definition_key`, `i := member_index`, `n := parasha_name`, `p := parasha_number` | `reading_definition_key, member_index` |
| `leyning_segment_definition` | `k := reading_definition_key`, `g := segment_kind`, `l := segment_label`, `i := segment_index`, `ken := book_en`, `khe := book_he`, `ka := book_ashkenazi`, `ben := begin_ref_en`, `bhe := begin_ref_he`, `ba := begin_ref_ashkenazi`, `een := end_ref_en`, `ehe := end_ref_he`, `ea := end_ref_ashkenazi`, `v := verse_count`, `p := parasha_number`, `ren := reason_en`, `rhe := reason_he`, `ra := reason_ashkenazi`, `nen := note_en`, `nhe := note_he`, `na := note_ashkenazi` | `reading_definition_key, segment_kind, segment_index` |

| Table | SHA-256 |
| --- | --- |
| `parasha_definition` | `88a2aaedb0d1ce960bb24761b9d1a3ed809494e58011f37f80000d5c797f7332` |
| `parasha_definition_member` | `9daf028f3f0231d301f71c04ba852a5fde1800ccb093288ceff36da63119ac9a` |
| `leyning_reading_definition` | `2d967b7a5d4bbc8be7e5220258e6f389d03c6071f25caf93e1130e6dde260209` |
| `leyning_definition_parasha` | `22c28511f9f8efcb782670dfbeff28ecfcbdc71b627c075e864d8fd97037d357` |
| `leyning_segment_definition` | `97e291fbeb67223105c3b50bd71164ac41a8f4f1f77da57a27706cfb9a7322e5` |

The manifest records these semantic fingerprints, each Parquet file hash and
schema, the verified source manifest hash, and validation evidence.
Timestamped run metadata is isolated in `provenance.json`.

## Immutability

The builder verifies the complete source manifest and every source file before
derivation, uses one DuckDB thread, writes to sibling staging, validates the
landed Parquet, and atomically renames only after success. It has no overwrite
or force option. A changed projection contract creates
`powerbi-readings-v2`; it never rewrites this directory.
