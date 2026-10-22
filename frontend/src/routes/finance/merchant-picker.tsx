import { useQuery } from '@tanstack/react-query';
import { ChevronsUpDown } from 'lucide-react';
import { type ReactNode, useState } from 'react';
import { listCounterpartiesOptions } from '@/api/@tanstack/react-query.gen';
import { Button } from '@/components/ui/button';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';

/** The household's merchants, most used first. */
export function useMerchants() {
  return useQuery({ ...listCounterpartiesOptions(), staleTime: 60_000 });
}

/** Pick a merchant, searchable. `exclude` leaves one out (merging a merchant into itself). */
export function MerchantPicker({
  onChange,
  children,
  exclude,
  className,
}: {
  onChange: (merchantId: string) => void;
  children: ReactNode; // the trigger's label
  exclude?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const merchants = useMerchants();

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className={cn('h-8 max-w-64 justify-between gap-1 px-2 font-normal', className)}
        >
          <span className="truncate">{children}</span>
          <ChevronsUpDown className="size-3 shrink-0 opacity-50" aria-hidden />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-64 p-0" align="start">
        <Command>
          <CommandInput placeholder="Search merchants" />
          <CommandList>
            <CommandEmpty>No merchant matches.</CommandEmpty>
            <CommandGroup>
              {merchants.data
                ?.filter((merchant) => merchant.id !== exclude)
                .map((merchant) => (
                  <CommandItem
                    key={merchant.id}
                    value={`${merchant.name} ${merchant.id}`}
                    onSelect={() => {
                      setOpen(false);
                      onChange(merchant.id);
                    }}
                  >
                    {merchant.name}
                  </CommandItem>
                ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
