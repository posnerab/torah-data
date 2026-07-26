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
import {HDate} from '@hebcal/core';


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
    const firstLeyning = (
      await readFile(join(output, 'core_leyning_occurrence.ndjson'), 'utf8')
    ).split('\n')[0];
    assert.match(firstLeyning, /"raw_reading_json":/);
  } finally {
    await rm(output, {recursive: true, force: true});
  }
});
