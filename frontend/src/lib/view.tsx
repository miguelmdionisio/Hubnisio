import { createContext, type ReactNode, use, useState } from 'react';
import type { GetSpendingData } from '@/api/types.gen';

/**
 * Whose money the overview, charts and budgets count (ADR-0005). "personal" is Mine: the
 * viewer's own accounts, with a shared pot counted as what they move into it. "household" is
 * every account in full.
 */
export type View = NonNullable<NonNullable<GetSpendingData['query']>['view']>;

export const VIEW_LABELS: Record<View, string> = { personal: 'Mine', household: 'Household' };

export const VIEW_NOTES: Record<View, string> = {
  personal: 'Your own accounts. A shared pot counts as what you move into it.',
  household: 'Every account in full, shared pots included.',
};

const STORAGE_KEY = 'hubnisio.view';

function storedView(): View {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'household' ? 'household' : 'personal';
  } catch {
    return 'personal';
  }
}

const ViewContext = createContext<{ view: View; setView: (view: View) => void }>({
  view: 'personal',
  setView: () => {},
});

/** The chosen view, remembered in this browser (Mine when storage is unavailable). */
export function ViewProvider({ children }: { children: ReactNode }) {
  const [view, setState] = useState<View>(storedView);
  const setView = (next: View) => {
    setState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Storage blocked: the choice lasts until the page reloads.
    }
  };
  return <ViewContext value={{ view, setView }}>{children}</ViewContext>;
}

export function useView() {
  return use(ViewContext);
}
