import type { Signal } from '@/api/types.gen';

/**
 * The signals' count, every state named so none hides: "4 OK · 1 no data", or
 * "3 OK · 1 watch · 1 no data". A state with none is left out (OK always shows).
 */
export function signalCount(items: Pick<Signal, 'state'>[]): string {
  const count = (state: Signal['state']) => items.filter((item) => item.state === state).length;
  const watch = count('watch');
  const missing = count('no_data');
  return [`${count('ok')} OK`, watch > 0 && `${watch} watch`, missing > 0 && `${missing} no data`]
    .filter(Boolean)
    .join(' · ');
}
