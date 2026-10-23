import { useMutation, useQueryClient } from '@tanstack/react-query';
import { type FormEvent, useState } from 'react';
import { toast } from 'sonner';
import {
  deleteBudgetMutation,
  deleteOverallBudgetMutation,
  listBudgetsQueryKey,
  setBudgetMutation,
  setOverallBudgetMutation,
} from '@/api/@tanstack/react-query.gen';
import type { BudgetOut, OverallBudgetOut, Overspend } from '@/api/types.gen';
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

/** What the sheet is for: a budget to change, a new one, or the overall one (`budget` null:
 * not set yet). */
export type BudgetTarget =
  | { type: 'new' }
  | { type: 'edit'; budget: BudgetOut }
  | { type: 'overall'; budget: OverallBudgetOut | null };

/** What the form shows of a budget that exists. */
type Figures = Pick<BudgetOut, 'rollover' | 'overspend' | 'limit' | 'available'>;

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
    saveOverall: useMutation({ ...setOverallBudgetMutation(), ...options }),
    removeOverall: useMutation({ ...deleteOverallBudgetMutation(), ...options }),
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
            key={target.type === 'edit' ? target.budget.category_id : target.type}
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
  const overall = target.type === 'overall';
  const budget: Figures | null = target.type === 'new' ? null : target.budget;
  const edits = useBudgetEdits(onClose);
  const [categoryId, setCategoryId] = useState(
    target.type === 'edit' ? target.budget.category_id : '',
  );
  const [amount, setAmount] = useState(budget ? Number(budget.limit).toFixed(2) : '');
  const [fromMonth, setFromMonth] = useState(month);
  const [rollover, setRollover] = useState(budget?.rollover ?? false);
  const [overspend, setOverspend] = useState<Overspend>(budget?.overspend ?? 'forgive');

  const value = Number(amount);
  const valid = amount.trim() !== '' && Number.isFinite(value) && value >= 0;
  const pending = Object.values(edits).some((edit) => edit.isPending);
  const canSave = valid && isMonth(fromMonth) && (overall || categoryId !== '') && !pending;

  const turnRollover = (on: boolean) => {
    setRollover(on);
    if (on && !budget?.rollover) setOverspend('carry');
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!canSave) return;
    const body = {
      amount: value.toFixed(2),
      from_month: monthStart(fromMonth),
      rollover,
      overspend,
    };
    if (overall) edits.saveOverall.mutate({ body });
    else edits.save.mutate({ path: { category_id: categoryId }, body });
  };
  const remove = () => {
    if (target.type === 'edit')
      edits.remove.mutate({ path: { category_id: target.budget.category_id } });
    else edits.removeOverall.mutate({});
  };

  return (
    <form onSubmit={submit} className="flex flex-1 flex-col gap-4">
      <SheetHeader>
        <SheetTitle>{title(target)}</SheetTitle>
        <SheetDescription>
          {budget
            ? `${formatMoney(budget.available, 'EUR')} available in ${formatMonth(month)}.`
            : overall
              ? 'A monthly cap on everything you spend, uncategorized too. Category budgets are limits within it.'
              : 'A monthly limit for one category, or for a whole group.'}
        </SheetDescription>
      </SheetHeader>

      <div className="space-y-5 px-4 text-sm">
        {target.type === 'new' && (
          <CategoryField value={categoryId} onChange={setCategoryId} taken={budgeted} />
        )}

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
          <Button type="button" variant="outline" disabled={pending} onClick={remove}>
            Remove budget
          </Button>
        )}
      </SheetFooter>
    </form>
  );
}

function title(target: BudgetTarget): string {
  if (target.type === 'new') return 'Add budget';
  return target.type === 'overall' ? 'All spending' : target.budget.name;
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
