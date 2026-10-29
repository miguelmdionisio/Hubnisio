import { useNavigate } from '@tanstack/react-router';
import { Monitor, Moon, Sun } from 'lucide-react';
import { createContext, type ReactNode, use, useEffect, useState } from 'react';
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import { THEME_LABELS, useTheme } from '@/lib/theme';
import { DOMAINS } from './domains';

const SearchContext = createContext<() => void>(() => {});

/** Opens the command menu: the sidebar's Search, the More page, or Ctrl K / ⌘K anywhere. */
export function useOpenSearch() {
  return use(SearchContext);
}

export function SearchProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const { setTheme } = useTheme();

  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === 'k' && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        setOpen((current) => !current);
      }
    };
    window.addEventListener('keydown', listener);
    return () => window.removeEventListener('keydown', listener);
  }, []);

  const run = (action: () => void) => {
    setOpen(false);
    action();
  };

  return (
    <SearchContext value={() => setOpen(true)}>
      {children}
      <CommandDialog open={open} onOpenChange={setOpen} title="Search" description="Go to a page">
        <Command>
          <CommandInput placeholder="Go to…" />
          <CommandList>
            <CommandEmpty>Nothing matches</CommandEmpty>
            {DOMAINS.map((domain) =>
              domain.groups.map((group) => (
                <CommandGroup
                  key={`${domain.name}-${group.label ?? ''}`}
                  heading={group.label ?? domain.name}
                >
                  {group.items.map((item) => (
                    <CommandItem
                      key={item.to}
                      value={`${domain.name} ${item.label}`}
                      onSelect={() => run(() => navigate({ to: item.to }))}
                    >
                      <item.icon aria-hidden />
                      {item.label}
                    </CommandItem>
                  ))}
                </CommandGroup>
              )),
            )}
            <CommandGroup heading="Theme">
              {(
                [
                  ['dark', Moon],
                  ['light', Sun],
                  ['system', Monitor],
                ] as const
              ).map(([theme, Icon]) => (
                <CommandItem
                  key={theme}
                  value={`Theme ${THEME_LABELS[theme]}`}
                  onSelect={() => run(() => setTheme(theme))}
                >
                  <Icon aria-hidden />
                  {THEME_LABELS[theme]} theme
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </CommandDialog>
    </SearchContext>
  );
}
