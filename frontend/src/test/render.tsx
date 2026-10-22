import { QueryClientProvider } from '@tanstack/react-query';
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router';
import { render } from '@testing-library/react';
import { StrictMode } from 'react';
import { vi } from 'vitest';
import { client } from '@/api/client.gen';
import { createQueryClient } from '@/lib/query-client';
import { createAppRouter } from '@/router';

/** Render the whole app at `path`, in strict mode like the real entrypoint. */
export function renderAt(path: string) {
  // Node's fetch can't resolve the relative URLs a browser would.
  client.setConfig({ baseUrl: 'http://localhost' });
  const queryClient = createQueryClient({ retry: false });
  const router = createAppRouter(createMemoryHistory({ initialEntries: [path] }));
  const view = render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </StrictMode>,
  );
  return { router, queryClient, ...view };
}

export type ApiCall = { method: string; path: string; search: URLSearchParams; body: unknown };
type Handler = (request: Request) => unknown;

/** Stub fetch with handlers keyed by "METHOD /path". Returns the list of calls made. */
export function mockApi(handlers: Record<string, Handler>): ApiCall[] {
  const calls: ApiCall[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      const url = new URL(request.url);
      const text = await request.clone().text();
      calls.push({
        method: request.method,
        path: url.pathname,
        search: url.searchParams,
        body: text ? JSON.parse(text) : undefined,
      });
      const handler = handlers[`${request.method} ${url.pathname}`];
      if (!handler) return Response.json({ detail: 'Not mocked' }, { status: 404 });
      const result = await handler(request);
      return result instanceof Response ? result : Response.json(result);
    }),
  );
  return calls;
}
