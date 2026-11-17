/**
 * This device's side of push alerts (M9 P6): whether it can get them, and subscribing it. On an
 * iPhone only the installed app (added to the Home Screen) can; Safari's tab can't.
 */

export type DeviceState =
  | 'unsupported' // no push here: on an iPhone, open the installed app instead
  | 'no-worker' // the dev server, which registers no service worker
  | 'denied' // the member said no; only the system settings can undo that
  | 'off'
  | 'on';

export function pushSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    'serviceWorker' in navigator &&
    'PushManager' in window &&
    'Notification' in window
  );
}

async function registration(): Promise<ServiceWorkerRegistration | undefined> {
  return navigator.serviceWorker.getRegistration();
}

export async function currentSubscription(): Promise<PushSubscription | null> {
  if (!pushSupported()) return null;
  return (await (await registration())?.pushManager.getSubscription()) ?? null;
}

export async function deviceState(): Promise<DeviceState> {
  if (!pushSupported()) return 'unsupported';
  if (!(await registration())) return 'no-worker';
  if (Notification.permission === 'denied') return 'denied';
  return (await currentSubscription()) ? 'on' : 'off';
}

/** The VAPID public key (base64url) as the bytes `subscribe` wants. */
export function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const base64 = (base64url + '='.repeat((4 - (base64url.length % 4)) % 4))
    .replace(/-/g, '+')
    .replace(/_/g, '/');
  const raw = atob(base64);
  const bytes = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

/**
 * Ask for permission (it must come from a tap) and subscribe this device. Returns the
 * subscription for the hub to keep, or null when permission wasn't given.
 */
export async function subscribeDevice(publicKey: string): Promise<PushSubscriptionJSON | null> {
  const permission = await Notification.requestPermission();
  if (permission !== 'granted') return null;
  const worker = await registration();
  if (!worker) return null;
  const subscription =
    (await worker.pushManager.getSubscription()) ??
    (await worker.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: keyBytes(publicKey),
    }));
  return subscription.toJSON();
}

/** Unsubscribe this device; returns its endpoint for the hub to forget. */
export async function unsubscribeDevice(): Promise<string | null> {
  const subscription = await currentSubscription();
  if (!subscription) return null;
  await subscription.unsubscribe();
  return subscription.endpoint;
}
