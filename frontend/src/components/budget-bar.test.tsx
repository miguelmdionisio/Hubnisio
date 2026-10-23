import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, test } from 'vitest';
import { BudgetBar } from './budget-bar';

afterEach(cleanup);

const bar = () => screen.getByRole('progressbar', { name: 'Utilities spent' });
const fill = () => bar().firstElementChild as HTMLElement;

test('fills in proportion to what is spent', () => {
  render(<BudgetBar label="Utilities" spent="60.00" available="240.00" over={false} />);

  expect(bar().getAttribute('aria-valuenow')).toBe('25');
  expect(fill().style.width).toBe('25%');
});

test('stays empty when repayments put the spending below zero', () => {
  render(<BudgetBar label="Utilities" spent="-50.00" available="250.00" over={false} />);

  expect(bar().getAttribute('aria-valuenow')).toBe('0');
  expect(fill().style.width).toBe('0%');
  expect(fill().className).not.toContain('bg-destructive');
  expect(bar().getAttribute('aria-valuetext')).toBe('-€50.00 of €250.00');
});

test('stays empty with nothing available, and full when spending has no room', () => {
  const { rerender } = render(
    <BudgetBar label="Utilities" spent="-5.00" available="0.00" over={false} />,
  );
  expect(fill().style.width).toBe('0%');

  rerender(<BudgetBar label="Utilities" spent="5.00" available="0.00" over />);
  expect(fill().style.width).toBe('100%');
  expect(fill().className).toContain('bg-destructive');
});
