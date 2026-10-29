import { type QueryClient, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  approveSuggestionsMutation,
  getSpendingMonthQueryKey,
  listBudgetsQueryKey,
  listCategoriesQueryKey,
  listCounterpartiesQueryKey,
  listTransactionsInfiniteQueryKey,
  listTransactionsQueryKey,
  unlinkTransferMutation,
  updateCounterpartyMutation,
  updateTransactionMutation,
} from '@/api/@tanstack/react-query.gen';
import type { Source } from '@/api/types.gen';
import { errorMessage } from '@/lib/errors';

/** Who decided something, in words. */
export const SOURCE_LABELS: Record<Source, string> = {
  manual: 'set by you',
  rule: 'set by a rule',
  counterparty: "the merchant's default",
  ai: 'suggested by AI',
  bank: 'from the bank',
  auto: 'matched automatically',
};

/** Everything that shows transactions, categories or merchants may have changed. */
export function invalidateUserLayer(queryClient: QueryClient) {
  queryClient.invalidateQueries({ queryKey: listTransactionsInfiniteQueryKey() });
  queryClient.invalidateQueries({ queryKey: listTransactionsQueryKey() }); // the overview's counts
  queryClient.invalidateQueries({ queryKey: listCategoriesQueryKey() });
  queryClient.invalidateQueries({ queryKey: listCounterpartiesQueryKey() });
  queryClient.invalidateQueries({ queryKey: getSpendingMonthQueryKey() });
  queryClient.invalidateQueries({ queryKey: listBudgetsQueryKey() });
}

/**
 * Change a transaction's category, merchant, kind, note or tags. After a category is set by
 * hand, offers it as the merchant's default for all its transactions.
 */
export function useUpdateTransaction() {
  const queryClient = useQueryClient();
  const applyToMerchant = useMutation({
    ...updateCounterpartyMutation(),
    onSuccess: (merchant) => {
      invalidateUserLayer(queryClient);
      toast.success(`Applied to everything from ${merchant.name}.`);
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  return useMutation({
    ...updateTransactionMutation(),
    onSuccess: ({ offer }) => {
      invalidateUserLayer(queryClient);
      if (!offer) return;
      const others = offer.other_transactions;
      toast(`Use this category for everything from ${offer.counterparty_name}?`, {
        description: `${others} other ${others === 1 ? 'transaction' : 'transactions'}, and future ones. Rules still come first.`,
        duration: 12_000,
        action: {
          label: 'Apply to all',
          onClick: () =>
            applyToMerchant.mutate({
              path: { counterparty_id: offer.counterparty_id },
              body: { default_category_id: offer.category_id },
            }),
        },
      });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
}

/** Keep categories an AI suggested: each becomes the user's own, as if picked by hand. */
export function useApproveSuggestions() {
  const queryClient = useQueryClient();
  return useMutation({
    ...approveSuggestionsMutation(),
    onSuccess: ({ approved }) => {
      invalidateUserLayer(queryClient);
      toast.success(approved === 1 ? 'Suggestion approved.' : `${approved} suggestions approved.`);
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
}

export function useUnlinkTransfer() {
  const queryClient = useQueryClient();
  return useMutation({
    ...unlinkTransferMutation(),
    onSuccess: () => invalidateUserLayer(queryClient),
    onError: (error) => toast.error(errorMessage(error)),
  });
}
