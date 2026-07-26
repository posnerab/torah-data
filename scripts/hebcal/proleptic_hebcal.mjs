/*
 * Proleptic compatibility for @hebcal/hdate 0.22.5 and
 * @hebcal/leyning 9.5.6.
 *
 * The pinned HDate.dayOnOrBefore() implementation uses JavaScript remainder
 * directly. For negative Rata Die values this can return the following
 * weekday instead of the requested weekday on or before the date. Hebcal
 * years 1-3761 contain negative absolute days, so install a mathematically
 * normalized implementation before any calendar caches are populated.
 *
 * @hebcal/leyning's getLeyningKeyForEvent() also uses `abs() % 7` directly.
 * The functions below retain its published 9.5.6 behavior while normalizing
 * that weekday calculation for the proleptic range.
 */

import {
  HDate,
  ParshaEvent,
  flags,
  getHolidaysOnDate,
  getSedra,
  months,
} from '@hebcal/core';
import {
  getLeyningForHolidayKey,
  getLeyningForParshaHaShavua,
  getWeekdayReading,
  hasFestival,
  makeLeyningNames,
  makeLeyningParts,
  makeSummaryFromParts,
} from '@hebcal/leyning';
import {translateLeyning} from '@hebcal/leyning/dist/esm/translate';

function modulo(value, divisor) {
  return ((value % divisor) + divisor) % divisor;
}

export function prolepticDayOnOrBefore(dayOfWeek, absoluteDay) {
  return absoluteDay - modulo(absoluteDay - dayOfWeek, 7);
}

HDate.dayOnOrBefore = prolepticDayOnOrBefore;

const HOLIDAY_IGNORE_MASK =
  flags.DAF_YOMI |
  flags.OMER_COUNT |
  flags.SHABBAT_MEVARCHIM |
  flags.MOLAD |
  flags.USER_EVENT |
  flags.HEBREW_DATE |
  flags.MISHNA_YOMI |
  flags.MODERN_HOLIDAY |
  flags.YERUSHALMI_YOMI;

export function getProlepticLeyningKeyForEvent(event, israel = false) {
  if (event.eventTime !== undefined) {
    return undefined;
  }
  const mask = event.getFlags();
  if (mask & HOLIDAY_IGNORE_MASK) {
    if (mask & flags.MODERN_HOLIDAY) {
      const description = event.getDesc();
      if (hasFestival(description)) {
        return description;
      }
    }
    return undefined;
  }
  const description = event.getDesc();
  if (mask & flags.EREV && !hasFestival(description)) {
    return undefined;
  }
  const hdate = event.getDate();
  const day = hdate.getDate();
  const weekday = modulo(hdate.abs(), 7);
  const month = hdate.getMonth();
  const isShabbat = weekday === 6;
  const isRoshChodesh = day === 1 || day === 30;
  const holiday = event.basename();
  const isPesach = holiday === 'Pesach';

  if (israel && isPesach) {
    if (isShabbat) {
      return day === 15 || day === 21
        ? `${description} (on Shabbat)`
        : 'Pesach Shabbat Chol ha-Moed';
    }
    return description;
  }
  if (day === 1 && month === months.TISHREI) {
    return isShabbat ? 'Rosh Hashana I (on Shabbat)' : 'Rosh Hashana I';
  }

  const cholHaMoedDay = event.cholHaMoedDay;
  if (typeof cholHaMoedDay === 'number') {
    if (isShabbat) {
      return `${holiday} Shabbat Chol ha-Moed`;
    }
    if (description === 'Sukkot VII (Hoshana Raba)') {
      return 'Sukkot Final Day (Hoshana Raba)';
    }
    if (isPesach && cholHaMoedDay) {
      if (weekday === 0 && description === "Pesach IV (CH''M)") {
        return 'Pesach Chol ha-Moed Day 2 on Sunday';
      }
      if (weekday === 1 && description === "Pesach V (CH''M)") {
        return 'Pesach Chol ha-Moed Day 3 on Monday';
      }
    }
    return `${holiday} Chol ha-Moed Day ${cholHaMoedDay}`;
  }

  const chanukahDay = event.chanukahDay;
  if (typeof chanukahDay === 'number') {
    if (isShabbat && isRoshChodesh) {
      return 'Shabbat Rosh Chodesh Chanukah';
    }
    if (isRoshChodesh && chanukahDay === 7) {
      return 'Chanukah Day 7 (on Rosh Chodesh)';
    }
    if (isShabbat) {
      return `Chanukah Day ${chanukahDay} (on Shabbat)`;
    }
    return `Chanukah Day ${chanukahDay}`;
  }

  if (
    isRoshChodesh &&
    (description === 'Shabbat HaChodesh' ||
      description === 'Shabbat Shekalim')
  ) {
    return `${description} (on Rosh Chodesh)`;
  }
  if (israel && description === 'Shmini Atzeret') {
    return `Simchat Torah${isShabbat ? ' (on Shabbat)' : ''}`;
  }
  if (description === 'Chag HaBanot') {
    return undefined;
  }
  if (isShabbat && description.substring(0, 7) !== 'Shabbat') {
    if (isRoshChodesh) {
      if (description === 'Rosh Chodesh Tevet') {
        return 'Shabbat Rosh Chodesh Chanukah';
      }
      return 'Shabbat Rosh Chodesh';
    }
    const shabbatDescription = `${description} (on Shabbat)`;
    if (hasFestival(shabbatDescription)) {
      return shabbatDescription;
    }
  }
  if (hasFestival(description)) {
    return description;
  }
  if (isShabbat) {
    const tomorrow = hdate.next().getDate();
    if (tomorrow === 30 || tomorrow === 1) {
      return 'Shabbat Machar Chodesh';
    }
  }
  if (description === 'Rosh Hashana LaBehemot') {
    return undefined;
  }
  if (description === 'Rosh Chodesh Tevet') {
    if (isShabbat) {
      return 'Shabbat Rosh Chodesh Chanukah';
    }
    if (day === 30 || HDate.shortKislev(hdate.getFullYear())) {
      return 'Chanukah Day 6';
    }
    return 'Chanukah Day 7 (on Rosh Chodesh)';
  }
  if (isRoshChodesh) {
    return description;
  }
  if (description === "Tish'a B'Av (observed)") {
    return "Tish'a B'Av";
  }
  return undefined;
}

function getProlepticLeyningForHoliday(event, israel = false) {
  if (typeof event !== 'object' || typeof event.getFlags !== 'function') {
    throw new TypeError(`Bad event argument: ${JSON.stringify(event)}`);
  }
  if (event.eventTime !== undefined) {
    return undefined;
  }
  if (event.getFlags() & flags.PARSHA_HASHAVUA) {
    throw new TypeError(`Event should be a holiday: ${event.getDesc()}`);
  }
  if (event.getFlags() & HOLIDAY_IGNORE_MASK) {
    return undefined;
  }
  const key = getProlepticLeyningKeyForEvent(event, israel);
  return getLeyningForHolidayKey(
    key,
    event.cholHaMoedDay,
    israel,
    'en',
  );
}

function findParshaHaShavua(saturday, israel) {
  const hebrewYear = saturday.getFullYear();
  const sedra = getSedra(hebrewYear, israel);
  const parasha = sedra.lookup(saturday);
  if (!parasha.chag) {
    return parasha;
  }
  if (saturday.getMonth() === months.TISHREI) {
    const day = saturday.getDate();
    const simchatTorah = israel ? 22 : 23;
    if (day > 2 && day <= simchatTorah) {
      return {
        parsha: ['Vezot Haberakhah'],
        chag: false,
        num: 54,
        hdate: saturday,
        il: israel,
      };
    }
  }
  const endOfYear =
    new HDate(1, months.TISHREI, hebrewYear + 1).abs() - 1;
  const searchEnd = endOfYear + 30;
  for (
    let absoluteDay = saturday.abs() + 7;
    absoluteDay <= searchEnd;
    absoluteDay += 7
  ) {
    const nextSedra =
      absoluteDay > endOfYear ? getSedra(hebrewYear + 1, israel) : sedra;
    const nextParasha = nextSedra.lookup(absoluteDay);
    if (!nextParasha.chag) {
      return nextParasha;
    }
  }
  throw new Error(`can't find parasha for ${saturday}/${israel}`);
}

function getMincha(event, israel) {
  const description = `${event.getDesc()} (Mincha)`;
  const reading = getLeyningForHolidayKey(
    description,
    event.cholHaMoedDay,
    israel,
  );
  if (reading) {
    return reading;
  }
  const key = getProlepticLeyningKeyForEvent(event, israel);
  if (key) {
    return getLeyningForHolidayKey(
      `${key} (Mincha)`,
      event.cholHaMoedDay,
      israel,
    );
  }
  return undefined;
}

export function getProlepticLeyningOnDate(
  hdate,
  israel,
  wantArray = false,
  language = 'en',
) {
  const weekday = hdate.getDay();
  const readings = [];
  let hasParshaHaShavua = false;

  if (weekday === 6) {
    const sedra = getSedra(hdate.getFullYear(), israel);
    const parasha = sedra.lookup(hdate);
    if (!parasha.chag) {
      const event = new ParshaEvent(parasha);
      const reading = getLeyningForParshaHaShavua(
        event,
        israel,
        language,
      );
      if (wantArray) {
        hasParshaHaShavua = true;
        readings.push(reading);
      } else {
        return reading;
      }
    }
  }

  const events = getHolidaysOnDate(hdate, israel) || [];
  let hasFullKriyah = false;
  for (const event of events) {
    const specialShabbat = Boolean(
      event.getFlags() &
        (flags.SPECIAL_SHABBAT | flags.ROSH_CHODESH),
    );
    if (hasParshaHaShavua && specialShabbat) {
      continue;
    }
    const reading = getProlepticLeyningForHoliday(event, israel);
    if (reading) {
      if (
        readings.some(
          (existingReading) =>
            existingReading.name.en === reading.name.en,
        )
      ) {
        continue;
      }
      const fullKriyah = reading.fullkriyah;
      if (fullKriyah) {
        hasFullKriyah = true;
      }
      const specialMaftirOnly =
        hasParshaHaShavua &&
        hasFullKriyah &&
        fullKriyah.M &&
        !fullKriyah['1'];
      if (!specialMaftirOnly) {
        readings.push(reading);
      }
      const mincha = getMincha(event, israel);
      if (mincha) {
        readings.push(mincha);
      }
      const description = event.getDesc();
      if (
        (israel && description === 'Sukkot VII (Hoshana Raba)') ||
        (!israel && description === 'Shmini Atzeret')
      ) {
        readings.push(getLeyningForHolidayKey('Erev Simchat Torah'));
      }
    }
  }

  if (!hasFullKriyah && (weekday === 1 || weekday === 4)) {
    const saturday = hdate.onOrAfter(6);
    const parasha = findParshaHaShavua(saturday, israel);
    const aliyot = getWeekdayReading(parasha.parsha);
    const parts = makeLeyningParts(aliyot);
    readings.unshift({
      name: makeLeyningNames(parasha.parsha),
      type: 'weekday',
      parsha: parasha.parsha,
      parshaNum: parasha.num,
      weekday: aliyot,
      summary: makeSummaryFromParts(parts),
    });
  }

  if (readings.length === 0) {
    return wantArray ? readings : readings[0];
  }
  if (wantArray) {
    return readings.map((reading) => translateLeyning(reading, language));
  }
  return translateLeyning(readings[0], language);
}
