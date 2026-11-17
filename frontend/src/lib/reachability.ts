import { useSyncExternalStore } from 'react';

/**
 * Whether the hub's API answered lately. On the phone the hub is reachable only while the PC and
 * the stack run; when they don't, the app still opens (its shell is kept) and says so.
 *
 * A fetch that fails outright (TypeError) means no route to the PC; a reply that isn't the API's
 * JSON (a bare 502 from `tailscale serve` while the stack is down) means the PC is on but the
 * hub isn't. An error the API answered with is an ordinary error, not this.
 */
let unreachable = false;
const listeners = new Set<() => void>();

function set(next: boolean) {
  if (next === unreachable) return;
  unreachable = next;
  for (const listener of listeners) listener();
}

export function isUnreachableError(error: unknown): boolean {
  return error instanceof TypeError || typeof error === 'string' || error == null;
}

export function noteQueryError(error: unknown) {
  if (isUnreachableError(error)) set(true);
}

export function noteQuerySuccess() {
  set(false);
}

export function useHubUnreachable(): boolean {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => unreachable,
  );
}
