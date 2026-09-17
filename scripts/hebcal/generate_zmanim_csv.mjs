#!/usr/bin/env node

import { createWriteStream } from 'node:fs';
import { once } from 'node:events';
import { GeoLocation, Zmanim } from '@hebcal/core';

export const LOCATION = Object.freeze({
  name: 'Milwaukee',
  latitude: 43.088013,
  longitude: -87.977046,
  elevation: 680,
  tzid: 'America/Chicago',
  zip: '53216',
});

export const VARIABLES = Object.freeze([
  'alotHaShachar',
  'beinHaShmashos',
  'chatzot',
  'chatzotNight',
  'dawn',
  'dusk',
  'minchaGedola',
  'minchaKetana',
  'misheyakir',
  'misheyakirMachmir',
  'plagHaMincha',
  'sofZmanShma',
  'sofZmanShmaMGA',
  'sofZmanShmaMGA16Point1',
  'sofZmanTfilla',
  'sofZmanTfillaMGA',
  'sunrise',
  'sunset',
  'tzeit42min',
  'tzeit50min',
  'tzeit7083deg',
  'tzeit72min',
  'tzeit85deg',
]);

const CALCULATORS = Object.freeze({
  tzeit42min: (zmanim) => zmanim.sunsetOffset(42, false, false),
  tzeit50min: (zmanim) => zmanim.sunsetOffset(50, false, false),
  tzeit7083deg: (zmanim) => zmanim.tzeit(7.083),
  tzeit72min: (zmanim) => zmanim.sunsetOffset(72, false, false),
  tzeit85deg: (zmanim) => zmanim.tzeit(8.5),
});

function parseDate(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) throw new Error(`Invalid ISO date: ${value}`);
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]), 12);
}

function isoDate(date) {
  return [
    String(date.getFullYear()).padStart(4, '0'),
    String(date.getMonth() + 1).padStart(2, '0'),
    String(date.getDate()).padStart(2, '0'),
  ].join('-');
}

function localTimestamp(zman) {
  if (!(zman instanceof Date) || Number.isNaN(zman.getTime())) return '';
  return Zmanim.formatISOWithTimeZone(LOCATION.tzid, zman).slice(0, 19);
}

function rowFor(date) {
  const seaLevel = new GeoLocation(
    LOCATION.name,
    LOCATION.latitude,
    LOCATION.longitude,
    0,
    LOCATION.tzid,
  );
  const elevated = new GeoLocation(
    LOCATION.name,
    LOCATION.latitude,
    LOCATION.longitude,
    LOCATION.elevation,
    LOCATION.tzid,
  );
  const base = new Zmanim(seaLevel, date, false);
  const withElevation = new Zmanim(elevated, date, true);
  const values = [isoDate(date)];
  for (const variable of VARIABLES) {
    const calculate = CALCULATORS[variable] ?? ((zmanim) => zmanim[variable]());
    values.push(localTimestamp(calculate(base)));
    values.push(localTimestamp(calculate(withElevation)));
  }
  return values.join(',');
}

export async function generateCsv(startIso, endIso, outputPath) {
  const start = parseDate(startIso);
  const end = parseDate(endIso);
  if (start > end) throw new Error('Start date is after end date');

  const stream = createWriteStream(outputPath, { encoding: 'utf8', flags: 'wx' });
  const header = ['Date'];
  for (const variable of VARIABLES) {
    header.push(variable, `${variable}_Elevation`);
  }
  stream.write(`${header.join(',')}\n`);

  for (const date = new Date(start); date <= end; date.setDate(date.getDate() + 1)) {
    if (!stream.write(`${rowFor(date)}\n`)) await once(stream, 'drain');
  }
  stream.end();
  await once(stream, 'close');
}

if (import.meta.url === `file:///${process.argv[1].replaceAll('\\', '/')}`) {
  const [start, end, output] = process.argv.slice(2);
  if (!start || !end || !output) {
    console.error('Usage: generate_zmanim_csv.mjs START END OUTPUT.csv');
    process.exit(2);
  }
  await generateCsv(start, end, output);
}
