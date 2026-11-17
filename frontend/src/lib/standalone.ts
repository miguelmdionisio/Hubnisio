/**
 * Whether the hub runs as the installed app (added to the iPhone's home screen) rather than in a
 * browser tab. Installed, there is no browser back button or pull to refresh, so the app gives
 * its own.
 */
export function isStandalone(): boolean {
  if (typeof window === 'undefined') return false;
  const iosStandalone = (navigator as Navigator & { standalone?: boolean }).standalone === true;
  return iosStandalone || window.matchMedia?.('(display-mode: standalone)').matches === true;
}
