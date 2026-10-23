import { useQuery } from '@tanstack/react-query';
import { Check, ChevronsUpDown } from 'lucide-react';
import { type ReactNode, useState } from 'react';
import { listCategoriesOptions } from '@/api/@tanstack/react-query.gen';
import type { CategoryGroupOut } from '@/api/types.gen';
import { Button } from '@/components/ui/button';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';

/** The household's categories, cached: they change rarely. */
export function useCategories() {
  return useQuery({ ...listCategoriesOptions(), staleTime: 5 * 60_000 });
}

/** Active (not archived) groups and categories, for pickers and filters. */
export function activeGroups(groups: CategoryGroupOut[] | undefined): CategoryGroupOut[] {
  return (groups ?? [])
    .filter((group) => !group.archived)
    .map((group) => ({ ...group, children: group.children.filter((child) => !child.archived) }));
}

/** Every category and group by ID, archived ones too: the name to show for a saved choice. */
export function categoryNames(groups: CategoryGroupOut[] | undefined): Map<string, string> {
  return new Map(
    (groups ?? []).flatMap((group) => [
      [group.id, group.name] as const,
      ...group.children.map((child) => [child.id, child.name] as const),
    ]),
  );
}

/**
 * Pick a category, searchable. `onChange(null)` hands the choice back to rules and the
 * merchant's default ("Automatic"); `noneLabel` renames that entry, or hides it with `null`.
 * `kind` offers only expense or only income categories.
 */
export function CategoryPicker({
  value,
  onChange,
  children,
  disabled,
  className,
  noneLabel = 'Automatic (rules and merchant)',
  kind,
}: {
  value: string | null;
  onChange: (categoryId: string | null) => void;
  children: ReactNode; // the trigger's label
  disabled?: boolean;
  className?: string;
  noneLabel?: string | null;
  kind?: CategoryGroupOut['kind'];
}) {
  const [open, setOpen] = useState(false);
  const categories = useCategories();
  const groups = activeGroups(categories.data).filter((group) => !kind || group.kind === kind);
  const choose = (categoryId: string | null) => {
    setOpen(false);
    if (categoryId !== value) onChange(categoryId);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          disabled={disabled}
          className={cn('h-7 max-w-52 justify-between gap-1 px-2 font-normal', className)}
        >
          <span className="truncate">{children}</span>
          <ChevronsUpDown className="size-3 shrink-0 opacity-50" aria-hidden />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-64 p-0" align="start">
        <Command>
          <CommandInput placeholder="Search categories" />
          <CommandList>
            <CommandEmpty>No category matches.</CommandEmpty>
            {noneLabel !== null && (
              <>
                <CommandGroup>
                  <CommandItem value="automatic" onSelect={() => choose(null)}>
                    <span className="text-muted-foreground">{noneLabel}</span>
                  </CommandItem>
                </CommandGroup>
                <CommandSeparator />
              </>
            )}
            {groups.map((group) => (
              <CommandGroup key={group.id} heading={group.name}>
                {[group, ...group.children].map((category) => (
                  <CommandItem
                    key={category.id}
                    value={`${group.name} ${category.name} ${category.id}`}
                    onSelect={() => choose(category.id)}
                  >
                    <Check
                      className={cn('size-3', value === category.id ? 'opacity-100' : 'opacity-0')}
                      aria-hidden
                    />
                    {category.id === group.id ? `${group.name} (general)` : category.name}
                  </CommandItem>
                ))}
              </CommandGroup>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
