import { expect, test } from 'vitest';
import {
  formatDate,
  formatMoney,
  formatMonth,
  formatRelative,
  formatShortMonth,
  parseDate,
} from './format';
import { isMonth, shiftMonth } from './months';

test('formats money in the given locale', () => {
  expect(formatMoney('-42.1700', 'EUR', 'en-GB')).toBe('-€42.17');
  expect(formatMoney(2100, 'EUR', 'pt-PT')).toMatch(/^2100,00\s€$/);
});

test('keeps calendar dates on their day in any timezone', () => {
  expect(parseDate('2026-01-01').getDate()).toBe(1);
  expect(formatDate('2026-10-14', 'en-GB')).toBe('14 Oct 2026');
});

test('names months, from a month or any date in it', () => {
  expect(formatMonth('2026-10', 'en-GB')).toBe('October 2026');
  expect(formatMonth('2026-10-01', 'en-GB')).toBe('October 2026');
  expect(formatShortMonth('2026-03-05', 'en-GB')).toBe('Mar 2026');
});

test('steps through months across year ends', () => {
  expect(shiftMonth('2026-10', -1)).toBe('2026-09');
  expect(shiftMonth('2026-01', -1)).toBe('2025-12');
  expect(shiftMonth('2026-12', 1)).toBe('2027-01');
  expect(isMonth('2026-10')).toBe(true);
  expect(isMonth('2026-13')).toBe(false);
  expect(isMonth('2026-10-01')).toBe(false);
});

test('describes times relative to now', () => {
  const now = Date.parse('2026-10-22T12:00:00Z');
  expect(formatRelative('2026-10-22T11:55:00Z', now, 'en')).toBe('5 minutes ago');
  expect(formatRelative('2026-10-21T12:00:00Z', now, 'en')).toBe('yesterday');
  expect(formatRelative('2026-10-22T11:59:50Z', now, 'en')).toBe('now');
});
