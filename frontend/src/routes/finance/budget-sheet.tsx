import { useMutation, useQueryClient } from '@tanstack/react-query';
import { type FormEvent, useState } from 'react';
import { toast } from 'sonner';
import {
  deleteBudgetMutation,
  listBudgetsQueryKey,
  setBudgetMutation,
} from '@/api/@tanstack/react-query.gen';
import type { BudgetOut, Overspend } from '@/api/types.gen';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { Switch } from '@/components/ui/switch';
import { errorMessage } from '@/lib/errors';
import { formatMoney, formatMonth } from '@/lib/format';
import { isMonth, monthStart } from '@/lib/months';
import { activeGroups, useCategories } from './category-picker';

/** What the sheet is for: a budget to change, or a new one. */
export type BudgetTarget = { type: 'new' } | { type: 'edit'; budget: BudgetOut };

const OVERSPEND_OPTIONS: { value: Overspend; label: string }[] = [
  { value: 'forgive', label: 'Start fresh next month' },
  { value: 'carry', label: 'Take it from next month' },
];

function useBudgetEdits(onDone: () => void) {
  const queryClient = useQueryClient();
  const options = {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: listBudgetsQueryKey() });
      onDone();
    },
    onError: (error: unknown) => toast.error(errorMessage(error)),
  };
  return {
    save: useMutation({ ...setBudgetMutation(), ...options }),
    remove: useMutation({ ...deleteBudgetMutation(), ...options }),
  };
}

export function BudgetSheet({
  target,
  month,
  budgeted,
  onClose,
}: {
  target: BudgetTarget | null;
  month: string; // the month being viewed: where "Applies from" starts
  budgeted: Set<string>; // categories and groups that already have a budget
  onClose: () => void;
}) {
  return (
    <Sheet open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-md">
        {target && (
          <BudgetForm
            key={target.type === 'edit' ? target.budget.category_id : 'new'}
            target={target}
            month={month}
            budgeted={budgeted}
            onClose={onClose}
          />
        )}
      </SheetContent>
    </Sheet>
  );
}

function BudgetForm({
  target,
  month,
  budgeted,
  onClose,
}: {
  target: BudgetTarget;
  month: string;
  budgeted: Set<string>;
  onClose: () => void;
}) {
  const budget = target.type === 'edit' ? target.budget : null;
  const edits = useBudgetEdits(onClose);
  const [categoryId, setCategoryId] = useState(budget?.category_id ?? '');
  const [amount, setAmount] = useState(budget ? Number(budget.limit).toFixed(2) : '');
  const [fromMonth, setFromMonth] = useState(month);
  const [rollover, setRollover] = useState(budget?.rollover ?? false);
  const [overspend, setOverspend] = useState<Overspend>(budget?.overspend ?? 'forgive');

  const value = Number(amount);
  const valid = amount.trim() !== '' && Number.isFinite(value) && value >= 0;
  const pending = edits.save.isPending || edits.remove.isPending;
  const canSave = valid && isMonth(fromMonth) && categoryId !== '' && !pending;

  const turnRollover = (on: boolean) => {
    setRollover(on);
    if (on && !budget?.rollover) setOverspend('carry');
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!canSave) return;
    edits.save.mutate({
      path: { category_id: categoryId },
      body: {
        amount: value.toFixed(2),
        from_month: monthStart(fromMonth),
        rollover,
        overspend,
      },
    });
  };

  return (
    <form onSubmit={submit} className="flex flex-1 flex-col gap-4">
      <SheetHeader>
        <SheetTitle>{budget ? budget.name : 'Add budget'}</SheetTitle>
        <SheetDescription>
          {budget
            ? `${formatMoney(budget.available, 'EUR')} available in ${formatMonth(month)}.`
            : 'A monthly limit for one category, or for a whole group.'}
        </SheetDescription>
      </SheetHeader>

      <div className="space-y-5 px-4 text-sm">
        {!budget && <CategoryField value={categoryId} onChange={setCategoryId} taken={budgeted} />}

        <div className="space-y-1.5">
          <Label htmlFor="budget-amount">Amount per month (EUR)</Label>
          <Input
            id="budget-amount"
            type="number"
            inputMode="decimal"
            min="0"
            step="0.01"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="budget-from">Applies from</Label>
          <Input
            id="budget-from"
            type="month"
            placeholder="YYYY-MM"
            value={fromMonth}
            onChange={(event) => setFromMonth(event.target.value)}
          />
          <p className="text-xs text-muted-foreground">Earlier months keep their own amounts.</p>
        </div>

        <div className="space-y-1.5">
          <div className="flex items-center justify-between gap-3">
            <Label htmlFor="budget-rollover">Roll over what's left</Label>
            <Switch id="budget-rollover" checked={rollover} onCheckedChange={turnRollover} />
          </div>
          <p className="text-xs text-muted-foreground">
            Unspent money is added to next month's budget instead of disappearing.
          </p>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="budget-overspend">If I overspend</Label>
          <Select value={overspend} onValueChange={(next) => setOverspend(next as Overspend)}>
            <SelectTrigger id="budget-overspend" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {OVERSPEND_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <SheetFooter>
        <Button type="submit" disabled={!canSave}>
          Save budget
        </Button>
        {budget && (
          <Button
            type="button"
            variant="outline"
            disabled={pending}
            onClick={() => edits.remove.mutate({ path: { category_id: budget.category_id } })}
          >
            Remove budget
          </Button>
        )}
      </SheetFooter>
    </form>
  );
}

/** Spending groups and categories that have no budget yet. */
function CategoryField({
  value,
  onChange,
  taken,
}: {
  value: string;
  onChange: (categoryId: string) => void;
  taken: Set<string>;
}) {
  const groups = activeGroups(useCategories().data).filter((group) => group.kind === 'expense');
  return (
    <div className="space-y-1.5">
      <Label htmlFor="budget-category">Category</Label>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger id="budget-category" className="w-full">
          <SelectValue placeholder="Choose a category or group" />
        </SelectTrigger>
        <SelectContent>
          {groups.map((group) => {
            const free = [group, ...group.children].filter((category) => !taken.has(category.id));
            if (free.length === 0) return null;
            return (
              <SelectGroup key={group.id}>
                <SelectLabel>{group.name}</SelectLabel>
                {free.map((category) => (
                  <SelectItem key={category.id} value={category.id}>
                    {category.id === group.id ? `All of ${group.name}` : category.name}
                  </SelectItem>
                ))}
              </SelectGroup>
            );
          })}
        </SelectContent>
      </Select>
    </div>
  );
}
