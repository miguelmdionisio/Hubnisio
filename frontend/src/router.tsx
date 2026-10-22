import { createRootRoute, createRoute, createRouter, Outlet } from '@tanstack/react-router';
import { HomePage } from './routes/home';

const rootRoute = createRootRoute({
  component: () => (
    <div className="min-h-screen bg-neutral-50 text-neutral-900">
      <header className="border-b border-neutral-200 bg-white px-6 py-4">
        <h1 className="text-lg font-semibold">Hubnisio</h1>
      </header>
      <main className="p-6">
        <Outlet />
      </main>
    </div>
  ),
});

const homeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: HomePage,
});

export const router = createRouter({ routeTree: rootRoute.addChildren([homeRoute]) });

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}
