import { useQuery } from '@tanstack/react-query';
import { listAccountsOptions } from '@/api/@tanstack/react-query.gen';
import type { AccountOut } from '@/api/types.gen';

const NONE: AccountOut[] = [];

/**
 * Every account the user can see, hidden ones included: their past transactions, and rules
 * that name them, still show their names. Pickers and filters offer `listed`, the accounts
 * that aren't hidden (ADR-0007, "Retiring an account").
 */
export function useAccounts() {
  const query = useQuery(listAccountsOptions({ query: { include_hidden: true } }));
  const all = query.data ?? NONE;
  return {
    ...query,
    listed: all.filter((account) => !account.hidden_at),
    hidden: all.filter((account) => account.hidden_at),
    names: new Map(all.map((account) => [account.id, account.name])),
  };
}
