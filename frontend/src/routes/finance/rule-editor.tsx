import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, X } from 'lucide-react';
import { type ReactNode, useEffect, useState } from 'react';
import { toast } from 'sonner';
import {
  createRuleMutation,
  listRulesQueryKey,
  updateRuleMutation,
} from '@/api/@tanstack/react-query.gen';
import { previewRule } from '@/api/sdk.gen';
import type { RuleMatch, RuleOut, TransactionKind } from '@/api/types.gen';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { errorMessage } from '@/lib/errors';
import { formatDate, formatMoney } from '@/lib/format';
import { CategoryPicker, categoryNames, useCategories } from './category-picker';
import { MerchantPicker, useMerchants } from './merchant-picker';
import {
  ACTION_LABELS,
  type ActionDraft,
  type ActionType,
  blankRule,
  type ConditionDraft,
  conditionInputs,
  DIRECTION_LABELS,
  draftOf,
  FIELDS,
  type Field,
  fieldSpec,
  KIND_LABELS,
  newAction,
  newCondition,
  OP_LABELS,
  type Op,
  ruleInput,
} from './rule-model';
import { useAccounts } from './use-accounts';
import { invalidateUserLayer } from './use-transaction-edits';

const PREVIEW_DELAY_MS = 400;

/** A value that follows `value` once it has stopped changing for `delay` ms. */
function useDebounced<T>(value: T, delay: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return settled;
}

function toOptions<T extends string>(labels: Record<T, string>) {
  return (Object.keys(labels) as T[]).map((value) => ({ value, label: labels[value] }));
}

function Choice<T extends string>({
  value,
  onChange,
  options,
  label,
  placeholder,
  className,
}: {
  value: T | '';
  onChange: (value: T) => void;
  options: { value: T; label: string }[];
  label: string;
  placeholder?: string;
  className?: string;
}) {
  return (
    <Select value={value} onValueChange={(next) => onChange(next as T)}>
      <SelectTrigger aria-label={label} className={className}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** Create a rule (`rule` null) or edit one, with a live count of what it would match. */
export function RuleEditor({ rule, onClose }: { rule: RuleOut | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(() => (rule ? draftOf(rule) : blankRule()));
  const accounts = useAccounts();
  const categories = useCategories();
  const merchants = useMerchants();
  const categoryLabels = categoryNames(categories.data);
  const merchantLabels = new Map(merchants.data?.map((merchant) => [merchant.id, merchant.name]));

  const saved = {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: listRulesQueryKey() });
      invalidateUserLayer(queryClient);
      toast.success('Rule saved and applied.');
      onClose();
    },
  };
  const create = useMutation({ ...createRuleMutation(), ...saved });
  const update = useMutation({ ...updateRuleMutation(), ...saved });
  const saving = create.isPending || update.isPending;
  const saveError = create.error ?? update.error;

  const input = ruleInput(draft, rule?.enabled ?? true);
  const save = () => {
    if (!input) return;
    if (rule) update.mutate({ path: { rule_id: rule.id }, body: input });
    else create.mutate({ body: input });
  };

  const setCondition = (index: number, next: ConditionDraft) =>
    setDraft((previous) => ({
      ...previous,
      conditions: previous.conditions.map((item, at) => (at === index ? next : item)),
    }));
  const setAction = (index: number, next: ActionDraft) =>
    setDraft((previous) => ({
      ...previous,
      actions: previous.actions.map((item, at) => (at === index ? next : item)),
    }));
  const without = <T,>(items: T[], index: number) => items.filter((_, at) => at !== index);

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{rule ? 'Edit rule' : 'New rule'}</DialogTitle>
          <DialogDescription>
            Rules run in order, from the top of the list. Text is compared ignoring case and
            accents; amounts ignore the sign.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <Label htmlFor="rule-name">Name</Label>
          <Input
            id="rule-name"
            value={draft.name}
            maxLength={80}
            placeholder="e.g. Groceries at Continente"
            onChange={(event) => setDraft({ ...draft, name: event.target.value })}
          />
        </div>

        <section className="space-y-2" aria-label="Conditions">
          <div className="flex items-center gap-2 text-sm">
            When
            <Choice<RuleMatch>
              label="Match"
              value={draft.match}
              className="w-20"
              options={[
                { value: 'all', label: 'all' },
                { value: 'any', label: 'any' },
              ]}
              onChange={(match) => setDraft({ ...draft, match })}
            />
            of these are true:
          </div>
          {draft.conditions.map((condition, index) => (
            <ConditionRow
              // Rows have no identity of their own; they are only ever edited in place.
              // biome-ignore lint/suspicious/noArrayIndexKey: see above
              key={index}
              position={index + 1}
              condition={condition}
              accounts={accounts.data
                // A hidden account isn't offered, unless the rule already names it.
                ?.filter((account) => !account.hidden_at || account.id === condition.value)
                .map((account) => ({ value: account.id, label: account.name }))}
              removable={draft.conditions.length > 1}
              onChange={(next) => setCondition(index, next)}
              onRemove={() => setDraft({ ...draft, conditions: without(draft.conditions, index) })}
            />
          ))}
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              setDraft({ ...draft, conditions: [...draft.conditions, newCondition()] })
            }
          >
            <Plus aria-hidden />
            Add condition
          </Button>
        </section>

        <section className="space-y-2" aria-label="Actions">
          <p className="text-sm">Then:</p>
          {draft.actions.map((action, index) => (
            <div
              // biome-ignore lint/suspicious/noArrayIndexKey: rows are only edited in place
              key={index}
              className="flex items-center gap-2"
            >
              <Choice<ActionType>
                label={`Action ${index + 1}`}
                value={action.type}
                className="w-44"
                options={toOptions(ACTION_LABELS)}
                onChange={(type) => setAction(index, newAction(type))}
              />
              <ActionValue
                position={index + 1}
                action={action}
                categoryLabels={categoryLabels}
                merchantLabels={merchantLabels}
                onChange={(next) => setAction(index, next)}
              />
              {draft.actions.length > 1 && (
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Remove action ${index + 1}`}
                  onClick={() => setDraft({ ...draft, actions: without(draft.actions, index) })}
                >
                  <X aria-hidden />
                </Button>
              )}
            </div>
          ))}
          <Button
            variant="outline"
            size="sm"
            onClick={() => setDraft({ ...draft, actions: [...draft.actions, newAction()] })}
          >
            <Plus aria-hidden />
            Add action
          </Button>
          <Label className="gap-2 pt-2 font-normal">
            <Switch
              size="sm"
              checked={draft.stop_processing}
              onCheckedChange={(stop_processing) => setDraft({ ...draft, stop_processing })}
            />
            Stop processing: later rules skip what this one matches
          </Label>
        </section>

        <Preview match={draft.match} conditions={draft.conditions} />

        {saveError && (
          <Alert variant="destructive">
            <AlertDescription>{errorMessage(saveError)}</AlertDescription>
          </Alert>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!input || saving} onClick={save}>
            Save rule
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ConditionRow({
  position,
  condition,
  accounts,
  removable,
  onChange,
  onRemove,
}: {
  position: number;
  condition: ConditionDraft;
  accounts: { value: string; label: string }[] | undefined;
  removable: boolean;
  onChange: (condition: ConditionDraft) => void;
  onRemove: () => void;
}) {
  const field = fieldSpec(condition.field);
  const textLike = ['description', 'counterparty', 'bank_counterparty', 'bank_code'].includes(
    field.value,
  );

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Choice<Field>
        label={`Condition ${position} field`}
        value={condition.field}
        className="w-52"
        options={FIELDS.map(({ value, label }) => ({ value, label }))}
        onChange={(next) => onChange(newCondition(next))}
      />
      <Choice<Op>
        label={`Condition ${position} operator`}
        value={condition.op}
        className="w-32"
        options={field.ops.map((op) => ({ value: op, label: OP_LABELS[op] }))}
        onChange={(op) => onChange({ ...condition, op })}
      />
      {textLike && (
        <Input
          aria-label={`Condition ${position} value`}
          className="min-w-40 flex-1"
          value={condition.value}
          onChange={(event) => onChange({ ...condition, value: event.target.value })}
        />
      )}
      {field.value === 'account' && (
        <Choice<string>
          label={`Condition ${position} value`}
          value={condition.value}
          placeholder="Choose an account"
          className="w-52"
          options={accounts ?? []}
          onChange={(value) => onChange({ ...condition, value })}
        />
      )}
      {field.value === 'direction' && (
        <Choice<'in' | 'out'>
          label={`Condition ${position} value`}
          value={condition.value as 'in' | 'out'}
          className="w-36"
          options={toOptions(DIRECTION_LABELS)}
          onChange={(value) => onChange({ ...condition, value })}
        />
      )}
      {field.value === 'amount' && (
        <>
          <Input
            aria-label={`Condition ${position} value`}
            inputMode="decimal"
            className="w-28"
            placeholder="0.00"
            value={condition.value}
            onChange={(event) => onChange({ ...condition, value: event.target.value })}
          />
          {condition.op === 'between' && (
            <>
              and
              <Input
                aria-label={`Condition ${position} upper value`}
                inputMode="decimal"
                className="w-28"
                placeholder="0.00"
                value={condition.high}
                onChange={(event) => onChange({ ...condition, high: event.target.value })}
              />
            </>
          )}
        </>
      )}
      {removable && (
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={`Remove condition ${position}`}
          onClick={onRemove}
        >
          <X aria-hidden />
        </Button>
      )}
    </div>
  );
}

function ActionValue({
  position,
  action,
  categoryLabels,
  merchantLabels,
  onChange,
}: {
  position: number;
  action: ActionDraft;
  categoryLabels: Map<string, string>;
  merchantLabels: Map<string, string>;
  onChange: (action: ActionDraft) => void;
}): ReactNode {
  switch (action.type) {
    case 'set_category':
      return (
        <CategoryPicker
          noneLabel={null}
          value={action.category_id}
          className="h-8 border"
          onChange={(category_id) => onChange({ ...action, category_id })}
        >
          {(action.category_id && categoryLabels.get(action.category_id)) || 'Choose a category'}
        </CategoryPicker>
      );
    case 'set_counterparty':
      return (
        <MerchantPicker
          creatable
          onChange={(counterparty_id) => onChange({ ...action, counterparty_id })}
        >
          {(action.counterparty_id && merchantLabels.get(action.counterparty_id)) ||
            'Choose a merchant'}
        </MerchantPicker>
      );
    case 'add_tag':
      return (
        <Input
          aria-label={`Action ${position} tag`}
          className="flex-1"
          maxLength={40}
          value={action.tag}
          onChange={(event) => onChange({ ...action, tag: event.target.value })}
        />
      );
    case 'set_kind':
      return (
        <Choice<TransactionKind>
          label={`Action ${position} kind`}
          value={action.kind}
          className="w-40"
          options={toOptions(KIND_LABELS)}
          onChange={(kind) => onChange({ ...action, kind })}
        />
      );
  }
}

function Preview({ match, conditions }: { match: RuleMatch; conditions: ConditionDraft[] }) {
  const inputs = conditionInputs(conditions);
  const body = useDebounced(
    inputs && JSON.stringify({ match, conditions: inputs }),
    PREVIEW_DELAY_MS,
  );
  const preview = useQuery({
    queryKey: ['rule-preview', body],
    queryFn: async ({ signal }) => {
      const { data } = await previewRule({
        body: JSON.parse(body ?? 'null'),
        signal,
        throwOnError: true,
      });
      return data;
    },
    enabled: body !== null,
    placeholderData: keepPreviousData,
  });

  return (
    <section className="space-y-2 rounded-lg bg-muted/50 p-3 text-sm" aria-label="Preview">
      {body === null && (
        <p className="text-muted-foreground">Fill in every condition to see what it matches.</p>
      )}
      {body !== null && preview.isError && (
        <p className="text-destructive">Couldn't preview: {errorMessage(preview.error)}</p>
      )}
      {body !== null && preview.data && (
        <>
          <p className="font-medium">
            Matches {preview.data.matches}{' '}
            {preview.data.matches === 1 ? 'transaction' : 'transactions'}
            {preview.isPlaceholderData && <span className="text-muted-foreground"> …</span>}
          </p>
          <ul className="space-y-0.5 text-muted-foreground">
            {preview.data.examples.map((example) => (
              <li key={example.id} className="flex justify-between gap-4">
                <span className="truncate">
                  {formatDate(example.occurred_on)} ·{' '}
                  {example.counterparty?.name ??
                    example.counterparty_name ??
                    example.description ??
                    'No description'}
                </span>
                <span className="shrink-0 tabular-nums">
                  {formatMoney(example.amount, example.currency)}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
