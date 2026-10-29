import { Monitor, Moon, Sun } from 'lucide-react';
import { THEME_LABELS, type Theme, useTheme } from '@/lib/theme';
import { Segmented } from './segmented';

const ICONS = { dark: Moon, light: Sun, system: Monitor };

export function ThemeSwitch({ className }: { className?: string }) {
  const { theme, setTheme } = useTheme();
  return (
    <Segmented
      label="Theme"
      className={className}
      value={theme}
      onChange={setTheme}
      options={(['dark', 'light', 'system'] satisfies Theme[]).map((value) => ({
        value,
        label: THEME_LABELS[value],
        icon: ICONS[value],
      }))}
    />
  );
}
