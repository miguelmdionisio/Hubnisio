import { useQuery } from '@tanstack/react-query';
import { useNavigate, useSearch } from '@tanstack/react-router';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import type { ReactNode } from 'react';
import { getSleepNightOptions, getSleepTrendsOptions } from '@/api/@tanstack/react-query.gen';
import type { NightOut, ReadingOut, SleepNight, SleepTrends } from '@/api/types.gen';
import { PageHeader } from '@/components/app-shell';
import { Segmented } from '@/components/segmented';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { formatDay, parseDate } from '@/lib/format';
import { cn } from '@/lib/utils';
import { QueryView } from '@/routes/overview/panel';
import {
  CorrelationChart,
  Gap,
  Legend,
  NIGHT_LEGEND,
  NightChart,
  NightsChart,
  ScheduleChart,
  SERIES,
  Sparkline,
  STAGE_LEGEND,
  WeekdayChart,
} from './charts';
import type { SleepSearch } from './search';
import { clock, hm, hmSeconds, STAGE_COLORS, STAGE_NAMES } from './units';

type Nights = 30 | 90 | 365;

const PERIODS = [
  { value: '30', label: '30 nights' },
  { value: '90', label: '90 nights' },
  { value: '365', label: '1 year' },
];

const iso = (date: Date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;

/** "Last night" for the night ending today or yesterday, else the day it ends. */
function nightLabel(day: string) {
  const now = new Date();
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  return day === iso(now) || day === iso(yesterday) ? 'Last night' : formatDay(day);
}

export function SleepPage() {
  const search = useSearch({ from: '/health/sleep' });
  const navigate = useNavigate();
  const set = (changes: Partial<SleepSearch>) =>
    navigate({
      to: '/health/sleep',
      search: (previous: SleepSearch) => ({ ...previous, ...changes }),
      replace: true,
    } as never);
  const nights: Nights = search.nights ?? 30;
  const night = useQuery(getSleepNightOptions({ query: { date: search.date } }));
  const trends = useQuery(getSleepTrendsOptions({ query: { nights } }));
  return (
    <>
      <PageHeader
        title="Sleep"
        actions={
          <>
            <NightStepper data={night.data} onStep={(date) => set({ date })} />
            <Segmented
              label="Trend period"
              options={PERIODS}
              value={String(nights)}
              onChange={(value) =>
                set({ nights: value === '30' ? undefined : (Number(value) as 90 | 365) })
              }
            />
          </>
        }
      />
      <div className="flex flex-col gap-4 pb-6 md:gap-5">
        <QueryView query={night} skeleton="h-72 rounded-[18px]">
          {(data) =>
            data.night ? (
              <Night night={data.night} />
            ) : (
              <NoNight data={data} onStep={(d) => set({ date: d })} />
            )
          }
        </QueryView>
        <QueryView query={trends} skeleton="h-72 rounded-[18px]">
          {(data) => <Trends data={data} />}
        </QueryView>
      </div>
    </>
  );
}

/** "‹ Last night ›": steps between the nights that exist, never past the latest. */
function NightStepper({
  data,
  onStep,
}: {
  data: SleepNight | undefined;
  onStep: (date: string) => void;
}) {
  const step =
    'grid h-[30px] w-8 place-items-center rounded-full text-muted-foreground hover:bg-surface-2 hover:text-foreground disabled:pointer-events-none disabled:opacity-30 [&>svg]:size-4';
  return (
    <div className="inline-flex h-[34px] shrink-0 items-center rounded-full bg-surface px-1 text-[13.5px] font-semibold md:h-9 md:text-sm">
      <button
        type="button"
        className={step}
        aria-label="Previous night"
        disabled={!data?.previous_day}
        onClick={() => data?.previous_day && onStep(data.previous_day)}
      >
        <ChevronLeft aria-hidden />
      </button>
      <span
        aria-live="polite"
        className="border-x px-2 text-center leading-5 tabular-nums md:min-w-[110px] md:px-3"
      >
        {data?.day ? nightLabel(data.day) : 'No nights'}
      </span>
      <button
        type="button"
        className={step}
        aria-label="Next night"
        disabled={!data?.next_day}
        onClick={() => data?.next_day && onStep(data.next_day)}
      >
        <ChevronRight aria-hidden />
      </button>
    </div>
  );
}

function NoNight({ data, onStep }: { data: SleepNight; onStep: (date: string) => void }) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>
          {data.day ? `${formatDay(data.day)}: no night recorded` : 'No nights yet'}
        </CardTitle>
      </CardHeader>
      {data.day && data.previous_day && (
        <CardContent>
          <button
            type="button"
            className="text-sm font-semibold text-primary"
            onClick={() => data.previous_day && onStep(data.previous_day)}
          >
            Latest earlier night
          </button>
        </CardContent>
      )}
    </Card>
  );
}

function Figure({
  label,
  value,
  unit,
  sub,
  tone,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  sub?: ReactNode;
  tone?: 'good' | 'bad';
}) {
  return (
    <Card size="sm">
      <CardContent>
        <p className="text-[13px] text-muted-foreground">{label}</p>
        <p
          className={cn(
            'my-0.5 text-3xl font-bold tracking-[-0.02em] tabular-nums md:text-[34px]',
            tone === 'bad' && 'text-destructive',
          )}
        >
          {value}
          {unit && (
            <small className="ml-1 text-base font-semibold text-muted-foreground">{unit}</small>
          )}
        </p>
        {sub && (
          <p className={cn('text-[13px] text-muted-foreground', tone === 'good' && 'text-good')}>
            {sub}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function Night({ night }: { night: NightOut }) {
  const debt = night.debt;
  const delta = night.score_vs_baseline;
  const quality = night.score_qualifier
    ? night.score_qualifier.toLowerCase().replaceAll('_', ' ')
    : null;
  const qualityText = quality ? quality.charAt(0).toUpperCase() + quality.slice(1) : null;
  return (
    <>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Figure
          label="Score"
          value={night.score ?? '–'}
          tone={delta !== null && delta > 0 ? 'good' : undefined}
          sub={
            [
              qualityText,
              delta !== null &&
                `${delta > 0 ? '▲' : '▼'} ${Math.abs(Math.round(delta))} vs 30-night`,
            ]
              .filter(Boolean)
              .join(' · ') || undefined
          }
        />
        <Figure
          label="Slept"
          value={night.slept_s === null ? '–' : hmSeconds(night.slept_s)}
          sub={[
            night.need_minutes !== null && `Need ${hm(night.need_minutes)}`,
            night.average_slept_minutes !== null && `7-day avg ${hm(night.average_slept_minutes)}`,
          ]
            .filter(Boolean)
            .join(' · ')}
        />
        <Figure
          label="In bed"
          value={clock(night.bed_min)}
          sub={`Up ${clock(night.wake_min)}${night.awake_count === null ? '' : ` · ${night.awake_count} ${night.awake_count === 1 ? 'wake' : 'wakes'}`}`}
        />
        {debt.nights > 0 ? (
          <Figure
            label="Sleep debt, 7 days"
            value={`${debt.debt_minutes > 0 ? '−' : debt.debt_minutes < 0 ? '+' : ''}${hm(debt.debt_minutes)}`}
            tone={debt.debt_minutes > 0 ? 'bad' : debt.debt_minutes < 0 ? 'good' : undefined}
            sub={`Need ${hm(debt.need_minutes)} · slept ${hm(debt.slept_minutes)}${debt.missing > 0 ? ` · ${debt.missing} missing` : ''}`}
          />
        ) : (
          <Figure label="Sleep debt, 7 days" value="–" sub="No nights to count" />
        )}
      </div>

      <Card size="sm">
        <CardHeader>
          <CardTitle>{nightTitle(night)}</CardTitle>
          <Legend items={[...STAGE_LEGEND.slice(0, 4), ...NIGHT_LEGEND]} />
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <Stages night={night} />
          <NightChart night={night} />
        </CardContent>
      </Card>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Mini
          name="Heart rate"
          unit="bpm"
          color={SERIES.hr.color}
          reading={night.heart_rate}
          note={lowNote(night, night.heart_rate, 'Low')}
        />
        <Mini
          name="HRV"
          unit="ms"
          color={SERIES.hrv.color}
          reading={night.hrv}
          note={highNote(night, night.hrv)}
        />
        <Mini
          name="Respiration"
          unit="brpm"
          color="var(--faint)"
          reading={night.respiration}
          note={
            night.respiration.low !== null && night.respiration.high !== null
              ? `Range ${Math.round(night.respiration.low)}–${Math.round(night.respiration.high)}`
              : 'No range'
          }
        />
        <Mini
          name="SpO2"
          unit="%"
          color={SERIES.spo2.color}
          reading={night.spo2}
          note={night.spo2.low !== null ? `Low ${Math.round(night.spo2.low)}` : 'No reading'}
        />
      </div>
    </>
  );
}

function nightTitle(night: NightOut) {
  const start = night.started_at.slice(0, 10);
  const end = night.ended_at.slice(0, 10);
  const day = (value: string) =>
    new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric' }).format(parseDate(value));
  const month = new Intl.DateTimeFormat('en-GB', { month: 'short' }).format(parseDate(end));
  return start === end ? `${day(end)} ${month}` : `${day(start)} → ${day(end)} ${month}`;
}

function minutesNote(night: NightOut, at: number | null) {
  return at === null ? '' : ` at ${clock(night.bed_min + at)}`;
}

function lowNote(night: NightOut, reading: ReadingOut, word: string) {
  return reading.low === null
    ? 'No readings'
    : `${word} ${Math.round(reading.low)}${minutesNote(night, reading.low_at)}`;
}

function highNote(night: NightOut, reading: ReadingOut) {
  return reading.high === null
    ? 'No readings'
    : `Peak ${Math.round(reading.high)}${minutesNote(night, reading.high_at)}`;
}

/** The split by stage: a bar, then each stage's time, share and typical range. */
function Stages({ night }: { night: NightOut }) {
  if (night.stages.length === 0) return <Gap>No stage split for this night</Gap>;
  const order = ['awake', 'rem', 'light', 'deep'] as const;
  const stages = order.flatMap((name) => night.stages.filter((s) => s.stage === name));
  return (
    <div>
      <div className="flex h-3.5 gap-0.5 overflow-hidden rounded-full" role="presentation">
        {night.stages.map((stage) => (
          <span
            key={stage.stage}
            style={{ flex: stage.seconds, background: STAGE_COLORS[stage.stage] }}
          />
        ))}
      </div>
      <dl className="mt-3.5 grid grid-cols-2 gap-3 md:grid-cols-4">
        {stages.map((stage) => (
          <div key={stage.stage}>
            <dt className="text-[13px] text-muted-foreground">{STAGE_NAMES[stage.stage]}</dt>
            <dd className="text-[22px] font-bold tabular-nums">
              {stage.seconds >= 3600
                ? hmSeconds(stage.seconds)
                : `${Math.round(stage.seconds / 60)}m`}
              <small className="ml-1 text-xs font-semibold text-muted-foreground">
                {Math.round(stage.share * 100)}%
              </small>
            </dd>
            <dd className="text-[13px] text-muted-foreground">
              {stage.typical_low !== null && stage.typical_high !== null
                ? `Typical ${Math.round(stage.typical_low * 100)}–${Math.round(stage.typical_high * 100)}%`
                : night.awake_count === null
                  ? 'Awake in bed'
                  : `${night.awake_count} ${night.awake_count === 1 ? 'wake' : 'wakes'}`}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function Mini({
  name,
  unit,
  color,
  reading,
  note,
}: {
  name: string;
  unit: string;
  color: string;
  reading: ReadingOut;
  note: string;
}) {
  return (
    <Card size="sm">
      <CardContent>
        <p className="text-[13px] text-muted-foreground">{name}</p>
        <p className="text-[22px] font-bold tabular-nums">
          {reading.avg === null ? '–' : Math.round(reading.avg * 10) / 10}
          {reading.avg !== null && (
            <small className="ml-1 text-xs font-semibold text-muted-foreground">{unit}</small>
          )}
        </p>
        {reading.series.length > 1 && (
          <Sparkline series={reading.series} color={color} label={name} />
        )}
        <p className="text-[13px] text-muted-foreground">{note}</p>
      </CardContent>
    </Card>
  );
}

function Trends({ data }: { data: SleepTrends }) {
  if (data.nights_worn === 0) {
    return (
      <Card size="sm">
        <CardHeader>
          <CardTitle>No nights in these {data.nights}</CardTitle>
        </CardHeader>
      </Card>
    );
  }
  const gaps = data.nights - data.nights_worn;
  const spread = data.schedule;
  const r = data.correlation.r;
  const label = data.nights === 365 ? '1 year' : `${data.nights} nights`;
  return (
    <>
      <div className="grid gap-4 md:gap-5 lg:grid-cols-2">
        <Card size="sm">
          <CardHeader>
            <CardTitle className="flex flex-wrap items-baseline gap-x-2.5">
              {label}
              {data.average_slept_minutes !== null && (
                <span className="text-[13px] font-normal text-muted-foreground">
                  avg {hm(data.average_slept_minutes)}
                </span>
              )}
            </CardTitle>
            <Legend
              items={[
                ...STAGE_LEGEND,
                {
                  name:
                    data.average_need_minutes === null
                      ? 'Need'
                      : `Need ${hm(data.average_need_minutes)}`,
                  color: 'var(--faint)',
                },
              ]}
            />
          </CardHeader>
          <CardContent>
            <NightsChart points={data.points} needMinutes={data.average_need_minutes} />
            {gaps > 0 && (
              <p className="mt-2 text-[13px] text-muted-foreground">
                {gaps} {gaps === 1 ? 'night' : 'nights'} not worn
              </p>
            )}
          </CardContent>
        </Card>
        <Card size="sm">
          <CardHeader>
            <CardTitle className="flex flex-wrap items-baseline gap-x-2.5">
              Schedule
              {spread.bed_sd !== null && spread.wake_sd !== null && (
                <span className="text-[13px] font-normal text-muted-foreground">
                  bedtime ± {Math.round(spread.bed_sd)} min · wake ± {Math.round(spread.wake_sd)}{' '}
                  min
                </span>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {spread.nights > 0 ? (
              <>
                <ScheduleChart points={data.points} spread={spread} />
                <p className="mt-2 text-[13px] text-muted-foreground">
                  {spread.weekend_bed_avg !== null && spread.weekday_bed_avg !== null
                    ? `Weekend bed ${clock(spread.weekend_bed_avg)}, up ${clock(spread.weekend_wake_avg ?? 0)} · weekday bed ${clock(spread.weekday_bed_avg)}, up ${clock(spread.weekday_wake_avg ?? 0)}`
                    : 'Weekends in lighter bars'}
                </p>
              </>
            ) : (
              <Gap>No bedtimes in this period</Gap>
            )}
          </CardContent>
        </Card>
      </div>
      <div className="grid gap-4 md:gap-5 lg:grid-cols-2">
        <Card size="sm">
          <CardHeader>
            <CardTitle className="flex flex-wrap items-baseline gap-x-2.5">
              Sleep and next morning's HRV
              <span className="text-[13px] font-normal text-muted-foreground">
                {label}
                {r !== null && ` · r = ${r.toFixed(2)}`}
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            {r !== null ? (
              <CorrelationChart correlation={data.correlation} />
            ) : (
              <Gap>{`Needs 20 nights with HRV, ${data.correlation.pairs.length} so far`}</Gap>
            )}
          </CardContent>
        </Card>
        <Card size="sm">
          <CardHeader>
            <CardTitle className="flex flex-wrap items-baseline gap-x-2.5">
              Score by weekday
              <span className="text-[13px] font-normal text-muted-foreground">{label}</span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <WeekdayChart scores={data.weekday_scores} />
          </CardContent>
        </Card>
      </div>
    </>
  );
}
