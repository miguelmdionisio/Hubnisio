import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, ChevronsUpDown, Plus } from 'lucide-react';
import { type ReactNode, useState } from 'react';
import { toast } from 'sonner';
import {
  createCounterpartyMutation,
  listCounterpartiesOptions,
  listCounterpartiesQueryKey,
} from '@/api/@tanstack/react-query.gen';
import type { CounterpartyOut } from '@/api/types.gen';
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
import { errorMessage } from '@/lib/errors';
import { cn } from '@/lib/utils';

/** The household's merchants, most used first. */
export function useMerchants(enabled = true) {
  return useQuery({ ...listCounterpartiesOptions(), staleTime: 60_000, enabled });
}

/** A name as the server compares merchants (`match_key`): lowercase, no accents, words only. */
export function matchKey(name: string) {
  return name
    .toLowerCase()
    .normalize('NFKD')
    .replace(/\p{M}/gu, '')
    .replace(/[^\p{L}\p{N}_]+/gu, ' ')
    .trim();
}

/**
 * Pick a merchant, searchable. `exclude` leaves one out (merging a merchant into itself);
 * `automatic` adds an item that clears the choice (null); `creatable` offers to create a
 * merchant named as typed when none has that name.
 */
export function MerchantPicker({
  onChange,
  children,
  value,
  exclude,
  automatic,
  creatable = false,
  disabled,
  className,
}: {
  onChange: (merchantId: string | null) => void;
  children: ReactNode; // the trigger's label
  value?: string | null; // ticked in the list
  exclude?: string;
  automatic?: string;
  creatable?: boolean;
  disabled?: boolean;
  className?: string;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const merchants = useMerchants(open);
  const choose = (merchantId: string | null) => {
    setOpen(false);
    setSearch('');
    if (merchantId !== value) onChange(merchantId);
  };
  const create = useMutation({
    ...createCounterpartyMutation(),
    onSuccess: (merchant) => {
      queryClient.setQueryData(
        listCounterpartiesQueryKey(),
        (old: CounterpartyOut[] | undefined) => old && [...old, merchant],
      );
      queryClient.invalidateQueries({ queryKey: listCounterpartiesQueryKey() });
      toast.success(`Created ${merchant.name}.`);
      choose(merchant.id);
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const name = search.trim();
  const offerCreate =
    creatable &&
    !!matchKey(name) &&
    !!merchants.data &&
    !merchants.data.some((merchant) => matchKey(merchant.name) === matchKey(name));

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setSearch('');
      }}
    >
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          disabled={disabled}
          className={cn('h-8 max-w-64 justify-between gap-1 px-2 font-normal', className)}
        >
          <span className="truncate">{children}</span>
          <ChevronsUpDown className="size-3 shrink-0 opacity-50" aria-hidden />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-72 p-0" align="start">
        <Command>
          <CommandInput placeholder="Search merchants" value={search} onValueChange={setSearch} />
          <CommandList>
            {!offerCreate && <CommandEmpty>No merchant matches.</CommandEmpty>}
            <CommandGroup>
              {automatic && (
                <CommandItem value="automatic" onSelect={() => choose(null)}>
                  <span className="text-muted-foreground">{automatic}</span>
                </CommandItem>
              )}
              {merchants.data
                ?.filter((merchant) => merchant.id !== exclude)
                .map((merchant) => (
                  <CommandItem
                    key={merchant.id}
                    value={`${merchant.name} ${merchant.id}`}
                    onSelect={() => choose(merchant.id)}
                  >
                    {value !== undefined && (
                      <Check
                        className={cn(
                          'size-3',
                          value === merchant.id ? 'opacity-100' : 'opacity-0',
                        )}
                        aria-hidden
                      />
                    )}
                    {merchant.name}
                  </CommandItem>
                ))}
            </CommandGroup>
            {offerCreate && (
              <CommandGroup forceMount>
                <CommandItem
                  forceMount
                  value={`create ${name}`}
                  disabled={create.isPending}
                  onSelect={() => create.mutate({ body: { name } })}
                >
                  <Plus className="size-3" aria-hidden />
                  Create “{name}”
                </CommandItem>
              </CommandGroup>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
