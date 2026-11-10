import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, LoaderCircle, RefreshCw, TriangleAlert, Watch } from 'lucide-react';
import { useState } from 'react';
import {
  getHealthConnectionOptions,
  getHealthConnectionQueryKey,
  syncHealthMutation,
} from '@/api/@tanstack/react-query.gen';
import type { HealthConnection } from '@/api/types.gen';
import { PageHeader } from '@/components/app-shell';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { errorMessage } from '@/lib/errors';
import { formatDate, formatRelative, parseDate } from '@/lib/format';
import { cn } from '@/lib/utils';
import { QueryView } from '@/routes/overview/panel';

const POLL_MS = 4_000;
const POLL_AFTER_QUEUE_MS = 60_000;

/** What each stored kind is called; the API keys them by table, or `samples.<kind>`. */
const KINDS: Record<string, string> = {
  daily_summaries: 'Daily summaries',
  sleeps: 'Sleep',
  hrv_nights: 'HRV nights',
  'samples.heart_rate': 'Heart rate',
  'samples.hrv': 'HRV readings',
  'samples.spo2': 'SpO2',
  'samples.body_battery': 'Body Battery',
  heart_rate_zones: 'Heart-rate zones',
  fitness_ages: 'Fitness age',
  weights: 'Weigh-ins',
  weight_goals: 'Weight goal',
};

function kindLabel(key: string): string {
  const known = KINDS[key];
  if (known) return known;
  const words = key.replace(/^samples\./, '').replaceAll('_', ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Whole days from today to a calendar date; negative once it has passed. */
export function daysUntil(isoDate: string, now = new Date()): number {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((parseDate(isoDate).getTime() - today.getTime()) / 86_400_000);
}

export function GarminPage() {
  const queryClient = useQueryClient();
  const [pollUntil, setPollUntil] = useState(0);
  const query = useQuery({
    ...getHealthConnectionOptions(),
    refetchInterval: (q) => (q.state.data?.syncing || Date.now() < pollUntil ? POLL_MS : false),
  });
  const sync = useMutation({
    ...syncHealthMutation(),
    onSuccess: () => setPollUntil(Date.now() + POLL_AFTER_QUEUE_MS),
    // A 404 (not linked) or 409 (key expired) means the page's picture is stale.
    onError: () => queryClient.invalidateQueries({ queryKey: getHealthConnectionQueryKey() }),
  });
  return (
    <>
      <PageHeader title="Garmin" />
      <QueryView query={query} skeleton="h-72 max-w-2xl rounded-[18px]">
        {(data) =>
          data.linked ? (
            <Linked
              data={data}
              syncing={Boolean(data.syncing) || sync.isPending}
              error={sync.isError ? errorMessage(sync.error) : null}
              onSync={() => sync.mutate({})}
            />
          ) : (
            <NotLinked />
          )
        }
      </QueryView>
    </>
  );
}

function NotLinked() {
  return (
    <Card size="sm" className="max-w-2xl gap-3 px-(--card-spacing)">
      <h2 className="flex items-center gap-2 text-[15px] font-semibold">
        <Watch className="size-4 text-muted-foreground" aria-hidden />
        Not linked
      </h2>
      <code className="w-fit max-w-full overflow-x-auto rounded-lg bg-surface px-3 py-2 font-mono text-[13px]">
        cli garmin-link
      </code>
    </Card>
  );
}

function Linked({
  data,
  syncing,
  error,
  onSync,
}: {
  data: HealthConnection;
  syncing: boolean;
  error: string | null;
  onSync: () => void;
}) {
  const expired =
    data.status === 'expired' || (data.key_expires_on ? daysUntil(data.key_expires_on) < 0 : false);
  const run = data.last_run;
  const stored = Object.entries(data.counts ?? {})
    .filter(([, count]) => count > 0)
    .sort(([a], [b]) => kindLabel(a).localeCompare(kindLabel(b)));
  return (
    <Card size="sm" className="max-w-2xl gap-4 px-(--card-spacing)">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h2 className="flex items-center gap-2 text-[15px] font-semibold">
          <Watch className="size-4 text-muted-foreground" aria-hidden />
          Linked
        </h2>
        <div className="ml-auto">
          <Button
            variant="outline"
            disabled={syncing || expired}
            onClick={onSync}
            className="rounded-full"
          >
            {syncing ? (
              <LoaderCircle className="animate-spin" aria-hidden />
            ) : (
              <RefreshCw aria-hidden />
            )}
            {syncing ? 'Syncing' : 'Sync now'}
          </Button>
        </div>
      </div>

      {error && (
        <p role="alert" className="text-[13px] text-destructive">
          {error}
        </p>
      )}

      <dl className="divide-y text-sm">
        <Row label="Last sync">
          {data.last_synced_at ? (
            <span className="inline-flex flex-wrap items-center justify-end gap-x-2">
              {formatRelative(data.last_synced_at)}
              {run && <RunState run={run} />}
            </span>
          ) : (
            <span className="text-muted-foreground">Never</span>
          )}
        </Row>
        {run && run.skipped.length > 0 && (
          <Row label="Skipped">
            <span className="text-muted-foreground">{run.skipped.map(kindLabel).join(', ')}</span>
          </Row>
        )}
        <Row label="Key">
          <KeyState expiresOn={data.key_expires_on ?? null} expired={expired} />
        </Row>
      </dl>

      <div>
        <h2 className="mb-1 text-[15px] font-semibold">Stored</h2>
        {stored.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">Nothing stored yet</p>
        ) : (
          <ul className="divide-y text-sm">
            {stored.map(([key, count]) => {
              const range = data.ranges?.[key];
              return (
                <li
                  key={key}
                  className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-3 py-2"
                >
                  <span className="min-w-0">
                    <span className="block font-medium">{kindLabel(key)}</span>
                    {range && (
                      <span className="block text-[13px] text-muted-foreground">
                        {formatDate(range.first)} – {formatDate(range.last)}
                      </span>
                    )}
                  </span>
                  <span className="tabular-nums">{count.toLocaleString('en-GB')}</span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </Card>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-2">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-right">{children}</dd>
    </div>
  );
}

function RunState({ run }: { run: NonNullable<HealthConnection['last_run']> }) {
  if (run.status === 'running') {
    return (
      <span className="inline-flex items-center gap-1 text-muted-foreground">
        <LoaderCircle className="size-3.5 animate-spin" aria-hidden />
        Running
      </span>
    );
  }
  if (run.status === 'failed') {
    return (
      <span className="inline-flex items-center gap-1 text-destructive">
        <TriangleAlert className="size-3.5" aria-hidden />
        Failed{run.error_code ? ` (${run.error_code})` : ''}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-good">
      <Check className="size-3.5" aria-hidden />
      Succeeded
    </span>
  );
}

function KeyState({ expiresOn, expired }: { expiresOn: string | null; expired: boolean }) {
  if (expiresOn === null) {
    return expired ? (
      <span className="inline-flex items-center gap-1 text-destructive">
        <TriangleAlert className="size-3.5" aria-hidden />
        Expired
      </span>
    ) : (
      <span className="text-muted-foreground">No expiry date</span>
    );
  }
  const left = daysUntil(expiresOn);
  const soon = !expired && left <= 14;
  return (
    <span
      className={cn(
        'inline-flex flex-wrap items-center justify-end gap-x-2',
        (soon || expired) && 'text-destructive',
      )}
    >
      {(soon || expired) && <TriangleAlert className="size-3.5" aria-hidden />}
      {expired ? 'Expired' : formatDate(expiresOn)}
      {expired && ` ${formatDate(expiresOn)}`}
      {!expired && (
        <span className={soon ? undefined : 'text-muted-foreground'}>
          {left === 0 ? 'today' : `in ${left} ${left === 1 ? 'day' : 'days'}`}
        </span>
      )}
    </span>
  );
}
