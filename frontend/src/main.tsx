import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from '@tanstack/react-router';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { registerServiceWorker } from './lib/pwa';
import { createQueryClient } from './lib/query-client';
import { router } from './router';
import './index.css';

const queryClient = createQueryClient();

const root = document.getElementById('root');
if (!root) throw new Error('Missing #root element');

registerServiceWorker();
// iOS Safari applies :active (the pressed dim in index.css) only once a touch listener exists.
document.addEventListener('touchstart', () => {}, { passive: true });

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
