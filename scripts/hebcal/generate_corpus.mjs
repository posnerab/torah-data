#!/usr/bin/env node

import {createHash} from 'node:crypto';
import {createWriteStream} from 'node:fs';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {once} from 'node:events';

import {HDate, HebrewCalendar, ParshaEvent, months} from '@hebcal/core';
import {getProlepticLeyningOnDate} from './proleptic_hebcal.mjs';

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const CONTRACT = JSON.parse(
  await readFile(resolve(SCRIPT_DIR, 'corpus-v1.json'), 'utf8'),
);
const FIRST_YEAR = CONTRACT.hebrewYearRange.first;
const LAST_YEAR = CONTRACT.hebrewYearRange.last;

const MONTH_ORDER_COMMON = [
  months.TISHREI,
  months.CHESHVAN,
  months.KISLEV,
  months.TEVET,
  months.SHVAT,
  months.ADAR_I,
  months.NISAN,
  months.IYYAR,
  months.SIVAN,
  months.TAMUZ,
  months.AV,
  months.ELUL,
];

const MONTH_ORDER_LEAP = [
  months.TISHREI,
  months.CHESHVAN,
  months.KISLEV,
  months.TEVET,
  months.SHVAT,
  months.ADAR_I,
  months.ADAR_II,
  months.NISAN,
  months.IYYAR,
  months.SIVAN,
  months.TAMUZ,
  months.AV,
  months.ELUL,
];

function parseInteger(value, optionName) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isInteger(parsed)) {
    throw new Error(`${optionName} must be an integer`);
  }
  return parsed;
}

export function validateYearRange(startYear, endYear) {
  if (startYear < FIRST_YEAR || endYear > LAST_YEAR || endYear < startYear) {
    throw new RangeError(
      `year range must be within ${FIRST_YEAR}-${LAST_YEAR} and ordered`,
    );
  }
}

export function monthOrder(year) {
  return HDate.isLeapYear(year) ? MONTH_ORDER_LEAP : MONTH_ORDER_COMMON;
}

function pad2(value) {
  return String(value).padStart(2, '0');
}

function gregorianDateText(year, month, day) {
  const monthDay = `${pad2(month)}-${pad2(day)}`;
  if (year <= 0) {
    return `${String(1 - year).padStart(4, '0')}-${monthDay} BCE`;
  }
  return `${String(year).padStart(4, '0')}-${monthDay} CE`;
}

function powerBiDate(year, month, day) {
  if (
    year > 1900 ||
    (year === 1900 && (month > 3 || (month === 3 && day >= 1)))
  ) {
    return `${String(year).padStart(4, '0')}-${pad2(month)}-${pad2(day)}`;
  }
  return null;
}

export function dayRow(hdate) {
  const gregorian = hdate.greg();
  const gregorianYear = gregorian.getFullYear();
  const gregorianMonth = gregorian.getMonth() + 1;
  const gregorianDay = gregorian.getDate();
  return {
    absolute_day: hdate.abs(),
    hebrew_year: hdate.getFullYear(),
    hebrew_month: hdate.getMonth(),
    hebrew_month_tishrei_index: hdate.getTishreiMonth(),
    hebrew_month_name: hdate.getMonthName(),
    hebrew_day: hdate.getDate(),
    weekday_sunday_0: hdate.getDay(),
    hebrew_date_en: hdate.render('en'),
    hebrew_date_he: hdate.render('he'),
    hebrew_date_ashkenazi: hdate.render('ashkenazi'),
    hebrew_date_gematria: hdate.renderGematriya(),
    gregorian_year_signed: gregorianYear,
    gregorian_era: gregorianYear <= 0 ? 'BCE' : 'CE',
    gregorian_year_of_era:
      gregorianYear <= 0 ? 1 - gregorianYear : gregorianYear,
    gregorian_month: gregorianMonth,
    gregorian_day: gregorianDay,
    gregorian_date_text: gregorianDateText(
      gregorianYear,
      gregorianMonth,
      gregorianDay,
    ),
    powerbi_date: powerBiDate(
      gregorianYear,
      gregorianMonth,
      gregorianDay,
    ),
  };
}

function canonicalize(value, seen = new WeakSet()) {
  if (value === null || typeof value !== 'object') {
    return value;
  }
  if (value instanceof Date) {
    return {
      year: value.getFullYear(),
      month: value.getMonth() + 1,
      day: value.getDate(),
      hour: value.getHours(),
      minute: value.getMinutes(),
      second: value.getSeconds(),
    };
  }
  if (seen.has(value)) {
    return '[Circular]';
  }
  seen.add(value);
  if (Array.isArray(value)) {
    const result = value.map((item) => canonicalize(item, seen));
    seen.delete(value);
    return result;
  }
  const result = {};
  for (const key of Object.keys(value).sort()) {
    const item = value[key];
    if (item !== undefined && typeof item !== 'function') {
      result[key] = canonicalize(item, seen);
    }
  }
  seen.delete(value);
  return result;
}

export function canonicalJson(value) {
  return JSON.stringify(canonicalize(value));
}

function stableId(prefix, fields) {
  const hash = sha256Text(canonicalJson(fields));
  return `${prefix}_${hash.slice(0, 24)}`;
}

function sha256Text(value) {
  return createHash('sha256').update(value, 'utf8').digest('hex');
}

function eventRows(year, schedule) {
  const israel = schedule === 'israel';
  const events = HebrewCalendar.calendar({
    year,
    isHebrewYear: true,
    il: israel,
    omer: true,
    sedrot: false,
    shabbatMevarchim: true,
    molad: true,
    yomKippurKatan: true,
    behab: true,
    yizkor: true,
  });
  return events
    .filter((event) => event.getDate().getFullYear() === year)
    .map((event) => {
    const hdate = event.getDate();
    const core = {
      schedule,
      absolute_day: hdate.abs(),
      event_class: event.constructor.name,
      event_description: event.getDesc(),
      event_basename: event.basename(),
      event_flags: event.getFlags(),
      title_en: event.render('en'),
      title_he: event.render('he'),
      title_ashkenazi: event.render('ashkenazi'),
      url: event.url() ?? null,
      raw_event_json: canonicalJson(event),
    };
    return {
      occurrence_id: stableId('event', core),
      hebrew_year: hdate.getFullYear(),
      ...core,
    };
    });
}

function dayScheduleRow(hdate, schedule) {
  const israel = schedule === 'israel';
  let tachanunJson;
  let tachanunSupported = true;
  let tachanunError = null;
  try {
    tachanunJson = canonicalJson(HebrewCalendar.tachanun(hdate, israel));
  } catch (error) {
    if (
      hdate.getFullYear() === 1 &&
      error instanceof RangeError &&
      String(error.message).includes('invalid year 0')
    ) {
      tachanunJson = null;
      tachanunSupported = false;
      tachanunError = 'upstream-year-0-dependency';
    } else {
      throw error;
    }
  }
  return {
    absolute_day: hdate.abs(),
    hebrew_year: hdate.getFullYear(),
    schedule,
    hallel: HebrewCalendar.hallel(hdate, israel),
    tachanun_json: tachanunJson,
    tachanun_supported: tachanunSupported,
    tachanun_error: tachanunError,
    eruv_tavshilin: HebrewCalendar.eruvTavshilin(hdate, israel),
  };
}

function parashaRows(year, schedule) {
  const israel = schedule === 'israel';
  const sedra = HebrewCalendar.getSedra(year, israel);
  const first = new HDate(1, months.TISHREI, year);
  const last = new HDate(1, months.TISHREI, year + 1).abs() - 1;
  const firstSaturday = first.abs() + ((6 - first.getDay() + 7) % 7);
  const events = [];
  for (let absoluteDay = firstSaturday; absoluteDay <= last; absoluteDay += 7) {
    const result = sedra.lookup(new HDate(absoluteDay));
    if (result && !result.chag && result.parsha.length) {
      events.push(new ParshaEvent(result));
    }
  }
  return events.map((event) => {
    const hdate = event.getDate();
    const core = {
      schedule,
      absolute_day: hdate.abs(),
      parasha: event.parsha,
      is_combined: event.parsha.length > 1,
      title_en: event.render('en'),
      title_he: event.render('he'),
      title_ashkenazi: event.render('ashkenazi'),
      basename: event.basename(),
      url: event.url() ?? null,
      raw_event_json: canonicalJson(event),
    };
    return {
      occurrence_id: stableId('parasha', core),
      hebrew_year: year,
      ...core,
    };
  });
}

function leyningRows(hdate, schedule) {
  const israel = schedule === 'israel';
  const byLocale = Object.fromEntries(
    CONTRACT.locales.map((locale) => [
      locale,
      getProlepticLeyningOnDate(hdate, israel, true, locale),
    ]),
  );
  const readings = byLocale.en;
  for (const locale of CONTRACT.locales) {
    if (byLocale[locale].length !== readings.length) {
      throw new Error(
        `leyning locale count mismatch on ${hdate.toString()} for ${schedule}`,
      );
    }
  }
  return readings.map((reading, readingIndex) => {
    const hebrewReading = byLocale.he[readingIndex];
    const ashkenaziReading = byLocale.ashkenazi[readingIndex];
    const rawReadingJson = canonicalJson(reading);
    const rawReadingJsonHe = canonicalJson(hebrewReading);
    const rawReadingJsonAshkenazi = canonicalJson(ashkenaziReading);
    const core = {
      schedule,
      absolute_day: hdate.abs(),
      reading_index: readingIndex,
      reading_type: reading.type ?? null,
      name_en: reading.name?.en ?? null,
      name_he: reading.name?.he ?? null,
      summary: reading.summary ?? null,
      summary_he: hebrewReading.summary ?? null,
      summary_ashkenazi: ashkenaziReading.summary ?? null,
      parasha_json: reading.parsha ? canonicalJson(reading.parsha) : null,
      parasha_num_json:
        reading.parshaNum === undefined
          ? null
          : canonicalJson(reading.parshaNum),
      raw_reading_json: rawReadingJson,
      raw_reading_json_he: rawReadingJsonHe,
      raw_reading_json_ashkenazi: rawReadingJsonAshkenazi,
      source_payload_sha256: sha256Text(rawReadingJson),
    };
    return {
      occurrence_id: stableId('leyning', core),
      hebrew_year: hdate.getFullYear(),
      ...core,
    };
  });
}

async function writeLine(stream, value) {
  if (!stream.write(`${JSON.stringify(value)}\n`, 'utf8')) {
    await once(stream, 'drain');
  }
}

async function closeStream(stream) {
  stream.end();
  await once(stream, 'finish');
}

export async function generateBlock({startYear, endYear, outputDir}) {
  validateYearRange(startYear, endYear);
  await mkdir(outputDir, {recursive: true});

  const paths = {
    core_year: resolve(outputDir, 'core_year.ndjson'),
    core_month: resolve(outputDir, 'core_month.ndjson'),
    core_day: resolve(outputDir, 'core_day.ndjson'),
    core_day_schedule: resolve(outputDir, 'core_day_schedule.ndjson'),
    core_event_occurrence: resolve(
      outputDir,
      'core_event_occurrence.ndjson',
    ),
    core_parasha_occurrence: resolve(
      outputDir,
      'core_parasha_occurrence.ndjson',
    ),
    core_leyning_occurrence: resolve(
      outputDir,
      'core_leyning_occurrence.ndjson',
    ),
  };
  const streams = Object.fromEntries(
    Object.entries(paths).map(([name, path]) => [
      name,
      createWriteStream(path, {encoding: 'utf8', flags: 'wx'}),
    ]),
  );
  const counts = Object.fromEntries(Object.keys(paths).map((name) => [name, 0]));

  for (let year = startYear; year <= endYear; year += 1) {
    const first = new HDate(1, months.TISHREI, year);
    const next = new HDate(1, months.TISHREI, year + 1);
    const cheshvan = new HDate(1, months.CHESHVAN, year);
    const kislev = new HDate(1, months.KISLEV, year);
    const yearRow = {
      hebrew_year: year,
      first_absolute_day: first.abs(),
      last_absolute_day: next.abs() - 1,
      days_in_year: HDate.daysInYear(year),
      is_leap_year: HDate.isLeapYear(year),
      months_in_year: HDate.monthsInYear(year),
      rosh_hashanah_weekday_sunday_0: first.getDay(),
      long_cheshvan: cheshvan.daysInMonth() === 30,
      short_kislev: kislev.daysInMonth() === 29,
    };
    await writeLine(streams.core_year, yearRow);
    counts.core_year += 1;

    for (const month of monthOrder(year)) {
      const firstOfMonth = new HDate(1, month, year);
      const daysInMonth = firstOfMonth.daysInMonth();
      await writeLine(streams.core_month, {
        hebrew_year: year,
        hebrew_month: month,
        hebrew_month_tishrei_index: firstOfMonth.getTishreiMonth(),
        hebrew_month_name: firstOfMonth.getMonthName(),
        first_absolute_day: firstOfMonth.abs(),
        last_absolute_day: firstOfMonth.abs() + daysInMonth - 1,
        days_in_month: daysInMonth,
      });
      counts.core_month += 1;

      for (let day = 1; day <= daysInMonth; day += 1) {
        const hdate = new HDate(day, month, year);
        await writeLine(streams.core_day, dayRow(hdate));
        counts.core_day += 1;
        for (const schedule of CONTRACT.schedules) {
          await writeLine(
            streams.core_day_schedule,
            dayScheduleRow(hdate, schedule),
          );
          counts.core_day_schedule += 1;
          for (const row of leyningRows(hdate, schedule)) {
            await writeLine(streams.core_leyning_occurrence, row);
            counts.core_leyning_occurrence += 1;
          }
        }
      }
    }

    for (const schedule of CONTRACT.schedules) {
      for (const row of eventRows(year, schedule)) {
        await writeLine(streams.core_event_occurrence, row);
        counts.core_event_occurrence += 1;
      }
      for (const row of parashaRows(year, schedule)) {
        await writeLine(streams.core_parasha_occurrence, row);
        counts.core_parasha_occurrence += 1;
      }
    }
  }

  await Promise.all(Object.values(streams).map(closeStream));
  const summary = {
    corpus_version: CONTRACT.corpusVersion,
    start_year: startYear,
    end_year: endYear,
    counts,
  };
  await writeFile(
    resolve(outputDir, 'generator-summary.json'),
    `${JSON.stringify(summary, null, 2)}\n`,
    {encoding: 'utf8', flag: 'wx'},
  );
  return summary;
}

function parseArguments(argv) {
  const options = {};
  for (let index = 0; index < argv.length; index += 2) {
    const option = argv[index];
    const value = argv[index + 1];
    if (!option?.startsWith('--') || value === undefined) {
      throw new Error('expected --start-year, --end-year, and --output-dir');
    }
    options[option.slice(2)] = value;
  }
  if (!options['start-year'] || !options['end-year'] || !options['output-dir']) {
    throw new Error('expected --start-year, --end-year, and --output-dir');
  }
  return {
    startYear: parseInteger(options['start-year'], '--start-year'),
    endYear: parseInteger(options['end-year'], '--end-year'),
    outputDir: resolve(options['output-dir']),
  };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const summary = await generateBlock(parseArguments(process.argv.slice(2)));
  process.stdout.write(`${JSON.stringify(summary)}\n`);
}
