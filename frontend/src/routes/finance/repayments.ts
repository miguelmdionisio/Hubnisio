import type { TransactionOut } from '@/api/types.gen';

/** Money in that sits in an expense category: it lowers that category's spending (ADR-0007). */
export function isRepayment(transaction: TransactionOut): boolean {
  return transaction.kind === 'expense' && Number(transaction.amount) > 0;
}

/** A bank's card refund (Revolut `CARD_REFUND`, BPI "dev. compra"), else a repayment. */
export function repaymentLabel(transaction: TransactionOut): 'Refund' | 'Repayment' {
  const refund =
    transaction.bank_code === 'CARD_REFUND' ||
    /\bdev\.? compra\b/i.test(transaction.description ?? '');
  return refund ? 'Refund' : 'Repayment';
}
