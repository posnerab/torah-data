# Corpus v1 physical schema

Every Parquet file is immutable after the root corpus manifest is published.
Columns may be interpreted by new derived transformations, but core files and
rows are never rewritten.

## Shared conventions

- `absolute_day` is the Rata Die integer and is the universal date key.
- `schedule` is `diaspora` or `israel`.
- `occurrence_id` is a stable SHA-256-derived identifier for an exact
  schedule-specific occurrence.
- Pre-1900 Gregorian dates use signed components and text. `powerbi_date` is
  nullable and begins on 1900-03-01.
- `raw_*_json` columns preserve lossless canonical library output so future
  normalization does not require Hebcal to run again.

## `core_year`

One row per Hebrew year:

`hebrew_year`, first/last absolute day, days and months in year, leap-year
flag, Rosh Hashanah weekday, long-Cheshvan flag, and short-Kislev flag.

## `core_month`

One row per Hebrew month:

Hebrew year, Nisan-based month number, Tishrei-based month index, English month
name, first/last absolute day, and month length.

## `core_day`

One row for every day in Hebrew years 1 through 6000:

- Absolute day and numeric Hebrew date components.
- Hebrew date text in English, Hebrew, Ashkenazi transliteration, and Hebrew
  gematria.
- Signed proleptic Gregorian year, BCE/CE era, year-of-era, month, day, and
  display text.
- Nullable `powerbi_date`.

## `core_event_occurrence`

One schedule-specific row for each location-independent Hebcal calendar event:

Occurrence ID, Hebrew year, schedule, absolute day, event class, stable
description, basename, bitmask flags, localized titles, optional URL, and
lossless canonical event JSON.

## `core_day_schedule`

Exactly two rows per absolute day, one for each Israel/Diaspora schedule:

Hallel level (`0`, `1`, or `2`), canonical Tachanun result JSON, Tachanun
support/error fields, and Eruv Tavshilin flag. These are preserved as source
outputs rather than recomputed by later transformations. Hebcal's Tachanun
implementation consults the preceding year and cannot evaluate Hebrew year 1
because year 0 is invalid; those rows explicitly record
`upstream-year-0-dependency`.

## `core_parasha_occurrence`

One schedule-specific row for every regular Shabbat parasha:

Occurrence ID, Hebrew year, schedule, absolute day, parasha-name list,
combined-parasha flag, localized titles, basename, URL, and canonical event
JSON.

The generator enumerates Shabbat absolute days and uses the lower-level Sedra
engine. This is required because the high-level calendar API suppresses sedrot
for ancient Gregorian ranges.

## `core_leyning_occurrence`

One row per item returned by `getLeyningOnDate(..., wantarray=true)`:

- Occurrence ID, Hebrew year, schedule, absolute day, and array index.
- Reading type and English/Hebrew names.
- English, Hebrew, and Ashkenazi summaries.
- Parasha names and numbers as canonical JSON.
- Complete canonical reading JSON for all three locales.
- SHA-256 of the canonical English source payload.

The array index is material because one date can contain multiple morning,
Mincha, or night readings. The complete JSON retains Torah aliyot, maftir,
haftarah, Sephardic and Chabad variants, alternate readings, megillah,
reasons, notes, and unknown future fields.

## Derived tables

Rebuildable SQL may later create:

- Event Definition and Event Occurrence.
- Reading Definition, Reading Occurrence, and Reading Aliyah.
- Hebrew Calendar and Schedule dimensions.
- Modern, diaspora-only compatibility projections for the current Power BI
  model.

Derived tables are not part of the immutable core identity.
