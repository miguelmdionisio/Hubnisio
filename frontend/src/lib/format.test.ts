import { expect, test } from 'vitest';
import {
  formatCompactMoney,
  formatDate,
  formatDistance,
  formatDuration,
  formatMoney,
  formatMonth,
  formatMonthName,
  formatPace,
  formatPercent,
  formatQuantity,
  formatRelative,
  formatShortMonth,
  parseDate,
} from './format';
import { isMonth, shiftMonth } from './months';

test('formats money in the given locale', () => {
  expect(formatMoney('-42.1700', 'EUR', 'en-GB')).toBe('-€42.17');
  expect(formatMoney(2100, 'EUR', 'pt-PT')).toMatch(/^2100,00\s€$/);
});

test('formats share quantities and percentages', () => {
  expect(formatQuantity('12.3456789000', 'en-GB')).toBe('12.345679');
  expect(formatQuantity('1200.0000000000', 'en-GB')).toBe('1,200');
  expect(formatPercent('0.6667', false, 'en-GB')).toBe('66.7%');
  expect(formatPercent(0.091, true, 'en-GB')).toBe('+9.1%');
  expect(formatPercent(-0.2, true, 'en-GB')).toBe('-20%');
});

test('keeps calendar dates on their day in any timezone', () => {
  expect(parseDate('2026-01-01').getDate()).toBe(1);
  expect(formatDate('2026-10-14', 'en-GB')).toBe('14 Oct 2026');
});

test('shortens money for chart axes', () => {
  expect(formatCompactMoney('1250', 'EUR', 'en-GB')).toBe('€1.3k');
  expect(formatCompactMoney(-80, 'EUR', 'en-GB')).toBe('-€80');
});

test('names months, from a month or any date in it', () => {
  expect(formatMonth('2026-10', 'en-GB')).toBe('October 2026');
  expect(formatMonth('2026-10-01', 'en-GB')).toBe('October 2026');
  expect(formatShortMonth('2026-03-05', 'en-GB')).toBe('Mar 2026');
  expect(formatMonthName('2026-10-01', 'en-GB')).toBe('Oct');
});

test('steps through months across year ends', () => {
  expect(shiftMonth('2026-10', -1)).toBe('2026-09');
  expect(shiftMonth('2026-01', -1)).toBe('2025-12');
  expect(shiftMonth('2026-12', 1)).toBe('2027-01');
  expect(isMonth('2026-10')).toBe(true);
  expect(isMonth('2026-13')).toBe(false);
  expect(isMonth('2026-10-01')).toBe(false);
});

test('formats durations as clock readings', () => {
  expect(formatDuration(0)).toBe('0:00');
  expect(formatDuration(3125.4)).toBe('52:05');
  expect(formatDuration(6730)).toBe('1:52:10');
});

test('formats pace as minutes and seconds', () => {
  expect(formatPace(314)).toBe('5:14');
  expect(formatPace(299.6)).toBe('5:00');
  expect(formatPace(66.67)).toBe('1:07');
});

test('formats distances in metres under a kilometre and kilometres above', () => {
  expect(formatDistance(850.4)).toBe('850 m');
  expect(formatDistance(21412)).toBe('21.4 km');
  expect(formatDistance(10000)).toBe('10.0 km');
});

test('describes times relative to now', () => {
  const now = Date.parse('2026-10-22T12:00:00Z');
  expect(formatRelative('2026-10-22T11:55:00Z', now, 'en')).toBe('5 minutes ago');
  expect(formatRelative('2026-10-21T12:00:00Z', now, 'en')).toBe('yesterday');
  expect(formatRelative('2026-10-22T11:59:50Z', now, 'en')).toBe('now');
});
