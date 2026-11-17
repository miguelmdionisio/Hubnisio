import { QueryCache, QueryClient } from '@tanstack/react-query';
import { noteQueryError, noteQuerySuccess } from './reachability';

const MAX_RETRIES = 3;

/**
 * Hub data only changes when a sync runs, and finished syncs invalidate what they touched
 * (see routes/finance/use-connections.ts), so data can be reused for a while instead of being
 * refetched on every mount.
 *
 * Only network failures are retried. An error the API answered with (a JSON body with a
 * `detail`) won't change on retry, so it's shown at once.
 */
export function createQueryClient(options: { retry?: boolean } = {}) {
  const retryNetworkErrors = options.retry ?? true;
  return new QueryClient({
    // Whether the hub answers, for the shell's "can't reach the hub" bar (lib/reachability.ts).
    queryCache: new QueryCache({ onError: noteQueryError, onSuccess: noteQuerySuccess }),
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: (failures, error) =>
          retryNetworkErrors && error instanceof TypeError && failures < MAX_RETRIES,
      },
    },
  });
}
