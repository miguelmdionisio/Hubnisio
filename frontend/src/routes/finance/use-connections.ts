import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import {
  listAccountsQueryKey,
  listConnectionsOptions,
  listTransactionsInfiniteQueryKey,
  startConnectionMutation,
} from '@/api/@tanstack/react-query.gen';
import type { ProviderName } from '@/api/types.gen';

const POLL_MS = 3000;

/**
 * The user's bank connections. Polls while a sync is running, or until `pollUntil` (a
 * timestamp: a sync was just queued and hasn't started), and refreshes accounts and
 * transactions whenever a sync finishes.
 */
export function useConnections(pollUntil = 0) {
  const queryClient = useQueryClient();
  const query = useQuery({
    ...listConnectionsOptions(),
    refetchInterval: (current) =>
      current.state.data?.some((connection) => connection.syncing) || Date.now() < pollUntil
        ? POLL_MS
        : false,
  });

  const syncedAt = query.data
    ?.map((connection) => `${connection.id}:${connection.last_synced_at}`)
    .join(',');
  const previous = useRef(syncedAt);
  useEffect(() => {
    if (syncedAt === undefined) return;
    if (previous.current !== undefined && previous.current !== syncedAt) {
      queryClient.invalidateQueries({ queryKey: listAccountsQueryKey() });
      queryClient.invalidateQueries({ queryKey: listTransactionsInfiniteQueryKey() });
    }
    previous.current = syncedAt;
  }, [syncedAt, queryClient]);

  return query;
}

/** Start linking a bank: on success the browser leaves for the bank's authorization page. */
export function useStartConnection() {
  return useMutation({
    ...startConnectionMutation(),
    onSuccess: (started) => window.location.assign(started.url),
  });
}

/** What a sync error code means, in words. */
export function describeSyncError(code: string, provider: ProviderName = 'enable_banking'): string {
  switch (code) {
    case 'ASPSP_RATE_LIMIT_EXCEEDED':
      return "the bank's daily limit on automatic syncs was reached; it retries in a few hours";
    case 'EXPIRED_SESSION':
    case 'CLOSED_SESSION':
    case 'REVOKED_SESSION':
      return 'the bank ended the consent';
    case 'KEY_REJECTED':
      return 'Trading 212 rejected the API key';
    case 'MISSING_PERMISSION':
      return 'the API key lacks a permission (it needs account data, history and portfolio)';
    case 'RATE_LIMITED':
      return "Trading 212's rate limit was reached; it retries in a few minutes";
    case 'KEY_FILE':
      return "the hub couldn't read the API key's file";
    case 'WRONG_ACCOUNT':
      return 'the API key is for another Trading 212 account';
    case 'NETWORK':
      return provider === 'trading212'
        ? "Trading 212 couldn't be reached"
        : "Enable Banking couldn't be reached";
    case 'APPLY_FAILED':
    case 'UNEXPECTED_RESPONSE':
      return "the hub couldn't read the bank's data";
    default:
      return code;
  }
}
