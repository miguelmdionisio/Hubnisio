import type { ApiCall } from '@/test/render';

/** The page's own API calls, leaving out the header's Garmin freshness. */
export function pageCalls(calls: ApiCall[]): ApiCall[] {
  return calls.filter((call) => call.path !== '/api/health/connection');
}
