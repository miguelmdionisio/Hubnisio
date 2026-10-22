import { expect, test } from 'vitest';
import { formatDate, formatMoney, formatRelative, parseDate } from './format';

test('formats money in the given locale', () => {
  expect(formatMoney('-42.1700', 'EUR', 'en-GB')).toBe('-€42.17');
  expect(formatMoney(2100, 'EUR', 'pt-PT')).toMatch(/^2100,00\s€$/);
});

test('keeps calendar dates on their day in any timezone', () => {
  expect(parseDate('2026-01-01').getDate()).toBe(1);
  expect(formatDate('2026-10-14', 'en-GB')).toBe('14 Oct 2026');
});

test('describes times relative to now', () => {
  const now = Date.parse('2026-10-22T12:00:00Z');
  expect(formatRelative('2026-10-22T11:55:00Z', now, 'en')).toBe('5 minutes ago');
  expect(formatRelative('2026-10-21T12:00:00Z', now, 'en')).toBe('yesterday');
  expect(formatRelative('2026-10-22T11:59:50Z', now, 'en')).toBe('now');
});
