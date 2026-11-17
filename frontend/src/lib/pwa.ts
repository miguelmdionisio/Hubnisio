import { registerSW } from 'virtual:pwa-register';
import { toast } from 'sonner';

/**
 * Registers the shell-only service worker (sw/sw.ts) in the built app, and offers a reload when
 * a newer build has been installed. The dev server registers none.
 */
export function registerServiceWorker() {
  if (!import.meta.env.PROD || !('serviceWorker' in navigator)) return;
  const update = registerSW({
    // Look for a new build whenever the app comes back to the front: an installed app may stay
    // open for days.
    onRegisteredSW(_url, registration) {
      if (!registration) return;
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') void registration.update();
      });
    },
    onNeedRefresh() {
      toast('New version', {
        id: 'new-version',
        duration: Number.POSITIVE_INFINITY,
        action: { label: 'Reload', onClick: () => void update(true) },
      });
    },
  });
}
