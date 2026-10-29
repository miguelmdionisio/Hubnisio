import { createContext, type ReactNode, use, useEffect, useState } from 'react';

/** Dark by default; light, or whatever the system says, on request. */
export type Theme = 'dark' | 'light' | 'system';

export const THEME_LABELS: Record<Theme, string> = {
  dark: 'Dark',
  light: 'Light',
  system: 'System',
};

// index.html reads the same key before the first paint, so a light choice doesn't flash dark.
const STORAGE_KEY = 'hubnisio.theme';

function storedTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === 'light' || stored === 'system' ? stored : 'dark';
  } catch {
    return 'dark';
  }
}

const ThemeContext = createContext<{ theme: Theme; setTheme: (theme: Theme) => void }>({
  theme: 'dark',
  setTheme: () => {},
});

/** The chosen theme, remembered in this browser, applied as the `dark` class on `<html>`. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setState] = useState<Theme>(storedTheme);

  useEffect(() => {
    const system = window.matchMedia('(prefers-color-scheme: dark)');
    const apply = () =>
      document.documentElement.classList.toggle(
        'dark',
        theme === 'dark' || (theme === 'system' && system.matches),
      );
    apply();
    if (theme !== 'system') return;
    system.addEventListener('change', apply);
    return () => system.removeEventListener('change', apply);
  }, [theme]);

  const setTheme = (next: Theme) => {
    setState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Storage blocked: the choice lasts until the page reloads.
    }
  };
  return <ThemeContext value={{ theme, setTheme }}>{children}</ThemeContext>;
}

export function useTheme() {
  return use(ThemeContext);
}
