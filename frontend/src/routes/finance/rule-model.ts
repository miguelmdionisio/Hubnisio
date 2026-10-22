import type {
  ConditionInput,
  ConditionOutput,
  RuleIn,
  RuleMatch,
  RuleOut,
  TransactionKind,
} from '@/api/types.gen';

/** What the rule editor edits: fields as typed, before they're valid enough to send. */

export type Field = ConditionInput['field'];
export type Op = ConditionInput['op'];
export type ActionInput = RuleIn['actions'][number];

const TEXT_OPS: Op[] = ['contains', 'starts_with', 'equals'];

type FieldSpec = { value: Field; label: string; ops: Op[] };

const DESCRIPTION: FieldSpec = { value: 'description', label: 'Description', ops: TEXT_OPS };

export const FIELDS: FieldSpec[] = [
  DESCRIPTION,
  { value: 'counterparty', label: 'Merchant', ops: TEXT_OPS },
  { value: 'bank_counterparty', label: 'Merchant, as the bank names it', ops: TEXT_OPS },
  { value: 'bank_code', label: 'Bank code', ops: ['is'] },
  { value: 'account', label: 'Account', ops: ['is'] },
  { value: 'direction', label: 'Direction', ops: ['is'] },
  { value: 'amount', label: 'Amount (ignoring sign)', ops: ['equals', 'gte', 'lte', 'between'] },
];

export function fieldSpec(field: Field): FieldSpec {
  return FIELDS.find((item) => item.value === field) ?? DESCRIPTION;
}

export const OP_LABELS: Record<Op, string> = {
  contains: 'contains',
  starts_with: 'starts with',
  equals: 'equals',
  is: 'is',
  gte: 'is at least',
  lte: 'is at most',
  between: 'is between',
};

export const DIRECTION_LABELS = { in: 'money in', out: 'money out' } as const;

export const KIND_LABELS: Record<TransactionKind, string> = {
  expense: 'spending',
  income: 'income',
  transfer: 'a transfer',
};

export type ConditionDraft = { field: Field; op: Op; value: string; high: string };

export type ActionDraft =
  | { type: 'set_category'; category_id: string | null }
  | { type: 'set_counterparty'; counterparty_id: string | null }
  | { type: 'add_tag'; tag: string }
  | { type: 'set_kind'; kind: TransactionKind };

export type ActionType = ActionDraft['type'];

export const ACTION_LABELS: Record<ActionType, string> = {
  set_category: 'Set the category',
  set_counterparty: 'Set the merchant',
  add_tag: 'Add a tag',
  set_kind: 'Treat as',
};

export type RuleDraft = {
  name: string;
  match: RuleMatch;
  conditions: ConditionDraft[];
  actions: ActionDraft[];
  stop_processing: boolean;
};

export function newCondition(field: Field = 'description'): ConditionDraft {
  const [op = 'is'] = fieldSpec(field).ops;
  return { field, op, value: field === 'direction' ? 'out' : '', high: '' };
}

export function newAction(type: ActionType = 'set_category'): ActionDraft {
  switch (type) {
    case 'set_category':
      return { type, category_id: null };
    case 'set_counterparty':
      return { type, counterparty_id: null };
    case 'add_tag':
      return { type, tag: '' };
    case 'set_kind':
      return { type, kind: 'transfer' };
  }
}

export function blankRule(): RuleDraft {
  return {
    name: '',
    match: 'all',
    conditions: [newCondition()],
    actions: [newAction()],
    stop_processing: false,
  };
}

export function draftOf(rule: RuleOut): RuleDraft {
  return {
    name: rule.name,
    match: rule.match ?? 'all',
    conditions: rule.conditions.map((condition) => {
      const [value = '', high = ''] = [condition.value].flat();
      return { field: condition.field, op: condition.op, value, high };
    }),
    actions: rule.actions.map((action) => ({ ...action })),
    stop_processing: rule.stop_processing ?? false,
  };
}

// People in Portugal type 12,50.
const amount = (text: string) => text.trim().replace(',', '.');
const isAmount = (text: string) => amount(text) !== '' && Number.isFinite(Number(amount(text)));

/** The condition as the API takes it, or null while it's incomplete. */
export function conditionInput(draft: ConditionDraft): ConditionInput | null {
  const { field, op } = draft;
  if (field === 'amount') {
    if (!isAmount(draft.value)) return null;
    if (op !== 'between') return { field, op, value: amount(draft.value) };
    return isAmount(draft.high)
      ? { field, op, value: [amount(draft.value), amount(draft.high)] }
      : null;
  }
  const value = draft.value.trim();
  return value ? { field, op, value } : null;
}

function actionInput(draft: ActionDraft): ActionInput | null {
  switch (draft.type) {
    case 'set_category':
      return draft.category_id ? { type: draft.type, category_id: draft.category_id } : null;
    case 'set_counterparty':
      return draft.counterparty_id
        ? { type: draft.type, counterparty_id: draft.counterparty_id }
        : null;
    case 'add_tag':
      return draft.tag.trim() ? { type: draft.type, tag: draft.tag.trim() } : null;
    case 'set_kind':
      return { type: draft.type, kind: draft.kind };
  }
}

/** The conditions as the API takes them, or null while any is incomplete. */
export function conditionInputs(drafts: ConditionDraft[]): ConditionInput[] | null {
  const inputs = drafts.map(conditionInput);
  return inputs.length > 0 && inputs.every((input) => input !== null) ? inputs : null;
}

/** The whole rule as the API takes it, or null while anything is missing. */
export function ruleInput(draft: RuleDraft, enabled: boolean): RuleIn | null {
  const conditions = conditionInputs(draft.conditions);
  const actions = draft.actions.map(actionInput);
  if (!draft.name.trim() || !conditions || actions.length === 0) return null;
  if (!actions.every((action) => action !== null)) return null;
  return {
    name: draft.name.trim(),
    enabled,
    match: draft.match,
    conditions,
    actions,
    stop_processing: draft.stop_processing,
  };
}

/** A saved rule as the API takes it back, with some fields changed. */
export function ruleToInput(rule: RuleOut, changes: Partial<RuleIn> = {}): RuleIn {
  return {
    name: rule.name,
    enabled: rule.enabled,
    match: rule.match,
    conditions: rule.conditions,
    actions: rule.actions,
    stop_processing: rule.stop_processing,
    ...changes,
  };
}

/** Names to put to the IDs a rule holds. */
export type Names = {
  accounts: Map<string, string>;
  categories: Map<string, string>;
  merchants: Map<string, string>;
};

export function describeCondition(
  condition: Pick<ConditionOutput, 'field' | 'op' | 'value'>,
  names: Names,
): string {
  const field = fieldSpec(condition.field).label;
  const { value } = condition;
  const shown = Array.isArray(value)
    ? value.join(' and ')
    : condition.field === 'account'
      ? (names.accounts.get(value) ?? 'an account')
      : condition.field === 'direction'
        ? (DIRECTION_LABELS[value as keyof typeof DIRECTION_LABELS] ?? value)
        : condition.field === 'amount'
          ? value
          : `“${value}”`;
  return `${field} ${OP_LABELS[condition.op]} ${shown}`;
}

export function describeAction(action: ActionInput, names: Names): string {
  switch (action.type) {
    case 'set_category':
      return `category ${names.categories.get(action.category_id) ?? 'unknown'}`;
    case 'set_counterparty':
      return `merchant ${names.merchants.get(action.counterparty_id) ?? 'unknown'}`;
    case 'add_tag':
      return `tag “${action.tag}”`;
    case 'set_kind':
      return `treat as ${KIND_LABELS[action.kind]}`;
  }
}
