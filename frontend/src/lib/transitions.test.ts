import { expect, test } from 'vitest';
import { slideFor, viewTransitionTypes } from './transitions';

test('detail pages slide in and back out; other moves are instant', () => {
  expect(slideFor('/finance/spending', '/finance/spending/category/c1')).toBe('slide-forward');
  expect(slideFor('/finance/spending/merchant/m1', '/finance/spending')).toBe('slide-back');
  expect(slideFor('/health/activities', '/health/activities/42')).toBe('slide-forward');
  expect(slideFor('/health/activities/42', '/health')).toBe('slide-back');
  expect(slideFor('/', '/finance/spending')).toBeUndefined(); // a tab
  expect(
    slideFor('/finance/spending/category/c1', '/finance/spending/merchant/m1'),
  ).toBeUndefined();
  expect(slideFor(undefined, '/finance/spending/category/c1')).toBeUndefined(); // first load
});

test('no transition when only the search changes', () => {
  const at = (pathname: string) => ({ pathname });
  expect(
    viewTransitionTypes({ fromLocation: at('/a'), toLocation: at('/a'), pathChanged: false }),
  ).toBe(false);
  expect(
    viewTransitionTypes({
      fromLocation: at('/health/activities'),
      toLocation: at('/health/activities/7'),
      pathChanged: true,
    }),
  ).toEqual(['slide-forward']);
});
