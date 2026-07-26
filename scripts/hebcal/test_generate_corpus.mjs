import assert from 'node:assert/strict';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';

import {
  dayRow,
  generateBlock,
  monthOrder,
  validateYearRange,
} from './generate_corpus.mjs';
import {
  getProlepticLeyningOnDate,
  prolepticDayOnOrBefore,
} from './proleptic_hebcal.mjs';
import {HDate} from '@hebcal/core';
import {getLeyningOnDate} from '@hebcal/leyning';


test('corpus begins at Hebrew year 1 and rejects year 0', () => {
  assert.throws(() => validateYearRange(0, 1), RangeError);
  assert.doesNotThrow(() => validateYearRange(1, 6000));
});

test('year 1 uses an absolute-day key and BCE Gregorian components', () => {
  const row = dayRow(new HDate(1, 'Tishrei', 1));
  assert.equal(row.absolute_day, -1373427);
  assert.equal(row.gregorian_year_signed, -3760);
  assert.equal(row.gregorian_era, 'BCE');
  assert.equal(row.gregorian_year_of_era, 3761);
  assert.equal(row.powerbi_date, null);
});

test('proleptic weekday helpers normalize negative absolute days', () => {
  assert.equal(prolepticDayOnOrBefore(6, 5), -1);
  assert.equal(HDate.dayOnOrBefore(6, 5), -1);
});

test('BCE Shabbat holiday leyning uses its Shabbat reading', () => {
  const roshHashana = new HDate(1, 'Tishrei', 2);
  assert.equal(roshHashana.abs(), -1373072);
  assert.equal(roshHashana.getDay(), 6);
  const readings = getProlepticLeyningOnDate(
    roshHashana,
    false,
    true,
    'en',
  );
  assert.deepEqual(
    readings.map((reading) => reading.name.en),
    ['Rosh Hashana I (on Shabbat)'],
  );
});

test('proleptic leyning matches upstream throughout a positive year', () => {
  let hdate = new HDate(1, 'Tishrei', 5785);
  const end = new HDate(1, 'Tishrei', 5786).abs();
  for (; hdate.abs() < end; hdate = hdate.next()) {
    for (const israel of [false, true]) {
      for (const locale of ['en', 'he', 'ashkenazi']) {
        assert.deepEqual(
          getProlepticLeyningOnDate(hdate, israel, true, locale),
          getLeyningOnDate(hdate, israel, true, locale),
          `${hdate}/${israel}/${locale}`,
        );
      }
    }
  }
});

test('month order contains 12 common or 13 leap months', () => {
  assert.equal(monthOrder(5783).length, 12);
  assert.equal(monthOrder(5784).length, 13);
});

test('boundary generation includes parasha rows for BCE years', async () => {
  const output = await mkdtemp(join(tmpdir(), 'torah-data-hebcal-'));
  try {
    const summary = await generateBlock({
      startYear: 1,
      endYear: 1,
      outputDir: output,
    });
    assert.equal(summary.counts.core_year, 1);
    assert.equal(summary.counts.core_day, 355);
    assert.equal(summary.counts.core_day_schedule, 710);
    assert.ok(summary.counts.core_event_occurrence > 0);
    assert.ok(summary.counts.core_parasha_occurrence > 0);
    assert.ok(summary.counts.core_leyning_occurrence > 0);
    const firstParasha = (
      await readFile(join(output, 'core_parasha_occurrence.ndjson'), 'utf8')
    ).split('\n')[0];
    assert.match(firstParasha, /"absolute_day":-\d+/);
    const firstParashaRow = JSON.parse(firstParasha);
    assert.equal(firstParashaRow.absolute_day, -1373422);
    assert.deepEqual(firstParashaRow.parasha, ['Vayeilech']);
    const firstLeyning = (
      await readFile(join(output, 'core_leyning_occurrence.ndjson'), 'utf8')
    ).split('\n')[0];
    assert.match(firstLeyning, /"raw_reading_json":/);
  } finally {
    await rm(output, {recursive: true, force: true});
  }
});

test('year 3761 crosses absolute day zero without duplicate parasha', async () => {
  const output = await mkdtemp(join(tmpdir(), 'torah-data-hebcal-'));
  try {
    await generateBlock({
      startYear: 3761,
      endYear: 3761,
      outputDir: output,
    });
    const rows = (
      await readFile(join(output, 'core_parasha_occurrence.ndjson'), 'utf8')
    )
      .trim()
      .split('\n')
      .map((line) => JSON.parse(line));
    assert.equal(new Set(rows.map((row) => row.occurrence_id)).size, rows.length);
    for (const schedule of ['diaspora', 'israel']) {
      const aroundZero = rows
        .filter(
          (row) =>
            row.schedule === schedule &&
            (row.absolute_day === -1 || row.absolute_day === 6),
        )
        .map((row) => [row.absolute_day, row.parasha]);
      assert.deepEqual(aroundZero, [
        [-1, ['Vayechi']],
        [6, ['Shemot']],
      ]);
    }
  } finally {
    await rm(output, {recursive: true, force: true});
  }
});
