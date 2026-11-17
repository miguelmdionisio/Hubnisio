import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { BellRing } from 'lucide-react';
import { useEffect, useState } from 'react';
import {
  getPushSettingsOptions,
  getPushSettingsQueryKey,
  sendTestPushMutation,
  setAlertMutation,
  subscribePushMutation,
  unsubscribePushMutation,
} from '@/api/@tanstack/react-query.gen';
import type { PushSettings } from '@/api/types.gen';
import { PageHeader } from '@/components/app-shell';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { errorMessage } from '@/lib/errors';
import {
  type DeviceState,
  deviceState,
  subscribeDevice,
  unsubscribeDevice,
} from '@/lib/push-device';
import { QueryView } from '../overview/panel';

/**
 * Push alerts on the phone (M9 P6): this device on or off, which alerts, and a test. Alerts come
 * from the PC, so only while it and its worker run, and only by day.
 */
export function NotificationsPage() {
  const settings = useQuery(getPushSettingsOptions());
  return (
    <>
      <PageHeader title="Notifications" />
      <div className="max-w-xl">
        <QueryView query={settings} skeleton="h-72 rounded-[18px]">
          {(data) => (
            <>
              <ThisDevice settings={data} />
              <Alerts settings={data} />
              <p className="mt-4 px-1 text-[13px] text-muted-foreground">
                Alerts come from the PC: they arrive while it runs, between 08:00 and 22:00, and
                each one once.
              </p>
            </>
          )}
        </QueryView>
      </div>
    </>
  );
}

function useDeviceState() {
  const [state, setState] = useState<DeviceState | undefined>();
  useEffect(() => {
    let live = true;
    void deviceState().then((next) => live && setState(next));
    return () => {
      live = false;
    };
  }, []);
  return [state, setState] as const;
}

const DEVICE_NOTES: Record<DeviceState, string> = {
  unsupported:
    'This browser can’t get notifications. On the iPhone, add Hubnisio to the Home Screen and open it from there.',
  'no-worker': 'Notifications work in the installed app, not on the dev server.',
  denied:
    'Notifications are blocked for Hubnisio. Allow them in the phone’s Settings, then come back.',
  off: 'This device gets no alerts.',
  on: 'This device gets the alerts below.',
};

function ThisDevice({ settings }: { settings: PushSettings }) {
  const queryClient = useQueryClient();
  const [state, setState] = useDeviceState();
  const [error, setError] = useState<string>();
  const refresh = () => queryClient.invalidateQueries({ queryKey: getPushSettingsQueryKey() });
  const subscribe = useMutation({ ...subscribePushMutation(), onSuccess: refresh });
  const unsubscribe = useMutation({ ...unsubscribePushMutation(), onSuccess: refresh });
  const test = useMutation(sendTestPushMutation());
  const [busy, setBusy] = useState(false);

  const turnOn = async () => {
    if (!settings.public_key) return;
    setBusy(true);
    setError(undefined);
    try {
      const subscription = await subscribeDevice(settings.public_key);
      if (!subscription?.endpoint || !subscription.keys) {
        setState(await deviceState());
        return;
      }
      await subscribe.mutateAsync({
        body: {
          endpoint: subscription.endpoint,
          keys: { p256dh: subscription.keys.p256dh ?? '', auth: subscription.keys.auth ?? '' },
        },
      });
      setState('on');
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const turnOff = async () => {
    setBusy(true);
    setError(undefined);
    try {
      const endpoint = await unsubscribeDevice();
      if (endpoint) await unsubscribe.mutateAsync({ body: { endpoint } });
      setState('off');
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="this-device" className="rounded-[18px] bg-surface p-4">
      <div className="flex items-center gap-3">
        <span
          className="grid size-[34px] shrink-0 place-items-center rounded-full bg-surface-2"
          aria-hidden
        >
          <BellRing className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 id="this-device" className="text-[15px] font-semibold">
            This device
          </h2>
          <p className="text-[13px] text-muted-foreground">
            {state ? DEVICE_NOTES[state] : 'Checking…'}
          </p>
        </div>
      </div>
      {!settings.public_key ? (
        <p className="mt-3 text-[13px] text-muted-foreground">
          The hub has no push key yet. On the PC run <code>cli push-keys</code>.
        </p>
      ) : (
        <div className="mt-3 flex flex-wrap gap-2">
          {state === 'off' && (
            <Button onClick={() => void turnOn()} disabled={busy}>
              Turn on
            </Button>
          )}
          {state === 'on' && (
            <>
              <Button
                variant="secondary"
                onClick={() => test.mutate({})}
                disabled={test.isPending || busy}
              >
                Send a test
              </Button>
              <Button variant="ghost" onClick={() => void turnOff()} disabled={busy}>
                Turn off
              </Button>
            </>
          )}
        </div>
      )}
      {test.data && (
        <p role="status" className="mt-2 text-[13px] text-muted-foreground">
          {test.data.sent > 0 ? 'Sent. It should arrive in a moment.' : 'No device took it.'}
        </p>
      )}
      {(error || test.error) && (
        <p role="alert" className="mt-2 text-[13px] text-destructive">
          {error ?? errorMessage(test.error)}
        </p>
      )}
      <p className="mt-3 text-[13px] text-muted-foreground">
        {settings.devices === 1
          ? '1 device gets alerts.'
          : `${settings.devices} devices get alerts.`}
      </p>
    </section>
  );
}

function Alerts({ settings }: { settings: PushSettings }) {
  const queryClient = useQueryClient();
  const change = useMutation({
    ...setAlertMutation(),
    onSuccess: (next) => queryClient.setQueryData(getPushSettingsQueryKey(), next),
  });
  return (
    <section aria-labelledby="alerts" className="mt-4">
      <h2 id="alerts" className="mb-1 px-1 text-[13px] font-semibold text-faint">
        Alerts
      </h2>
      <ul className="rounded-[18px] bg-surface p-1.5">
        {settings.alerts.map((alert) => (
          <li key={alert.kind} className="flex min-h-11 items-center gap-3 px-3 py-2.5">
            <span className="flex-1 text-[15px] font-medium">{alert.label}</span>
            <Switch
              aria-label={alert.label}
              checked={alert.enabled}
              disabled={change.isPending}
              onCheckedChange={(enabled) =>
                change.mutate({ path: { kind: alert.kind }, body: { enabled } })
              }
            />
          </li>
        ))}
      </ul>
    </section>
  );
}
