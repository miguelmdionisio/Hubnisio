import type { TransactionCategory, TransactionOut } from '@/api/types.gen';
import { transactionTitle } from './transaction-sheet';

/** One card of the review: a merchant's open transactions in one section, or one on its own. */
export type ReviewGroup = {
  key: string;
  title: string;
  section: 'this-month' | 'earlier';
  transactions: TransactionOut[]; // newest first
  /** The AI's category when every suggestion in the group agrees; `mixed` when they don't. */
  suggestion: TransactionCategory | 'mixed' | null;
  /** The sum when they share a currency, else null. */
  total: { amount: number; currency: string } | null;
};

/**
 * What the weekly review still has to decide: uncategorized transactions and AI suggestions,
 * grouped by merchant, this month's first. Within a section the biggest groups come first, then
 * the newest. `split` holds transactions taken out of their group to decide on their own.
 */
export function reviewGroups(
  open: TransactionOut[],
  monthStart: string,
  split: ReadonlySet<string> = new Set(),
): ReviewGroup[] {
  const byKey = new Map<string, TransactionOut[]>();
  const seen = new Set<string>();
  for (const transaction of open) {
    if (seen.has(transaction.id)) continue;
    seen.add(transaction.id);
    const section = transaction.occurred_on >= monthStart ? 'this-month' : 'earlier';
    const merchant = split.has(transaction.id) ? null : transaction.counterparty?.id;
    const key = merchant ? `${section}:${merchant}` : `${section}:tx:${transaction.id}`;
    byKey.set(key, [...(byKey.get(key) ?? []), transaction]);
  }

  const groups = [...byKey.entries()].map(([key, transactions]): ReviewGroup => {
    const sorted = [...transactions].sort((a, b) => b.occurred_on.localeCompare(a.occurred_on));
    const first = sorted[0] as TransactionOut;
    return {
      key,
      title: transactionTitle(first),
      section: key.startsWith('this-month') ? 'this-month' : 'earlier',
      transactions: sorted,
      suggestion: suggestionOf(sorted),
      total: totalOf(sorted),
    };
  });
  const order = (group: ReviewGroup) => (group.section === 'this-month' ? 0 : 1);
  return groups.sort(
    (a, b) =>
      order(a) - order(b) ||
      b.transactions.length - a.transactions.length ||
      (b.transactions[0]?.occurred_on ?? '').localeCompare(a.transactions[0]?.occurred_on ?? ''),
  );
}

function suggestionOf(transactions: TransactionOut[]): ReviewGroup['suggestion'] {
  const suggested = transactions
    .map((transaction) => transaction.category)
    .filter((category): category is TransactionCategory => category?.source === 'ai');
  const [first] = suggested;
  if (!first) return null;
  return suggested.every((category) => category.id === first.id) ? first : 'mixed';
}

function totalOf(transactions: TransactionOut[]): ReviewGroup['total'] {
  const currency = transactions[0]?.currency;
  if (!currency || transactions.some((transaction) => transaction.currency !== currency)) {
    return null;
  }
  const amount = transactions.reduce((sum, transaction) => sum + Number(transaction.amount), 0);
  return { amount, currency };
}

/** Skipped groups go to the end, in the order they were skipped. */
export function withSkippedLast(groups: ReviewGroup[], skipped: string[]): ReviewGroup[] {
  const rank = new Map(skipped.map((key, index) => [key, index]));
  return [
    ...groups.filter((group) => !rank.has(group.key)),
    ...groups
      .filter((group) => rank.has(group.key))
      .sort((a, b) => (rank.get(a.key) ?? 0) - (rank.get(b.key) ?? 0)),
  ];
}
