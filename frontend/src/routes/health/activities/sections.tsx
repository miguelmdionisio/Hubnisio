import { Link } from '@tanstack/react-router';
import { ArrowDown, ArrowUp } from 'lucide-react';
import type {
  ActivityClimb,
  ActivityDetail,
  ActivityDurability,
  ActivityForm,
  ActivityLeg,
  ActivityPair,
  ActivityPool,
  ActivitySplits,
  ActivityZones,
} from '@/api/types.gen';
import { formatDistance, formatDuration, formatPace } from '@/lib/format';
import { cn } from '@/lib/utils';
import { SwolfBars } from './charts';
import { Figure, Mini, number, Section, Table, td, th } from './parts';
import { activityTitle, type Group, SPORTS, SportChip } from './sport';

const KM_PER_H = 3.6;

function distanceParts(metres: number): [string, string] {
  return metres < 1000 ? [String(Math.round(metres)), 'm'] : [number(metres / 1000, 1), 'km'];
}

type Fig = { label: string; value: string; unit?: string; note?: string };

/** The strip of figures an activity opens with: what its sport is read by; none that is missing. */
export function figuresFor(a: ActivityDetail): Fig[] {
  const s = a.summary;
  const group = a.group;
  const out: (Fig | null)[] = [];
  const distance = s.distance_m ? distanceParts(s.distance_m) : null;
  const time: Fig | null = s.duration_s
    ? {
        label: 'Time',
        value: formatDuration(s.duration_s),
        note:
          s.moving_s && s.moving_s < s.duration_s * 0.97
            ? `Moving ${formatDuration(s.moving_s)}`
            : undefined,
      }
    : null;
  const dist: Fig | null = distance
    ? { label: 'Distance', value: distance[0], unit: distance[1] }
    : null;
  const hr: Fig | null = s.avg_hr
    ? {
        label: 'Heart rate',
        value: String(s.avg_hr),
        unit: 'bpm',
        note: s.max_hr ? `Max ${s.max_hr}` : undefined,
      }
    : null;
  const load: Fig | null =
    a.loads.ours !== null || a.loads.garmin !== null
      ? {
          label: 'Load',
          value: number(a.loads.ours ?? a.loads.garmin),
          note:
            a.loads.ours !== null && a.loads.garmin !== null
              ? `Garmin ${number(a.loads.garmin)}`
              : undefined,
        }
      : null;
  const effect: Fig | null =
    a.loads.aerobic_te !== null
      ? {
          label: 'Training effect',
          value: number(a.loads.aerobic_te, 1),
          note:
            a.loads.anaerobic_te !== null
              ? `Aerobic · ${number(a.loads.anaerobic_te, 1)} anaerobic`
              : 'Aerobic',
        }
      : null;
  const perKm = s.distance_m && s.duration_s ? (s.duration_s / s.distance_m) * 1000 : null;
  switch (group) {
    case 'run':
      out.push(
        dist,
        time,
        perKm === null
          ? null
          : {
              label: 'Pace',
              value: formatPace(perKm),
              unit: '/km',
              note: s.graded_speed ? `Graded ${formatPace(1000 / s.graded_speed)}` : undefined,
            },
        hr,
        load,
        effect,
      );
      break;
    case 'bike': {
      const speed = s.distance_m && s.duration_s ? (s.distance_m / s.duration_s) * KM_PER_H : null;
      out.push(
        dist,
        time,
        speed === null
          ? null
          : {
              label: 'Speed',
              value: number(speed, 1),
              unit: 'km/h',
              note: s.max_speed ? `Max ${number(s.max_speed * KM_PER_H, 1)}` : undefined,
            },
        s.elevation_gain_m === null
          ? null
          : {
              label: 'Elevation',
              value: `+${number(s.elevation_gain_m)}`,
              unit: 'm',
              note: s.elevation_loss_m === null ? undefined : `−${number(s.elevation_loss_m)} m`,
            },
        s.avg_power
          ? {
              label: 'Power',
              value: String(s.avg_power),
              unit: 'W',
              note: s.norm_power ? `Normalized ${s.norm_power}` : undefined,
            }
          : null,
        hr,
        load,
        effect,
      );
      break;
    }
    case 'swim': {
      const per100 = s.distance_m && s.duration_s ? (s.duration_s / s.distance_m) * 100 : null;
      out.push(
        dist,
        time,
        per100 === null ? null : { label: 'Pace', value: formatPace(per100), unit: '/100 m' },
        hr,
        load,
        s.avg_swolf
          ? {
              label: 'SWOLF',
              value: number(s.avg_swolf),
              note: s.lengths ? `${s.lengths} lengths` : undefined,
            }
          : effect,
      );
      break;
    }
    default:
      out.push(
        time,
        dist,
        hr,
        load,
        s.calories ? { label: 'Calories', value: number(s.calories), unit: 'kcal' } : null,
        effect,
      );
  }
  return out.filter((fig): fig is Fig => fig !== null);
}

export function Figures({ activity }: { activity: ActivityDetail }) {
  const figures = figuresFor(activity);
  if (figures.length === 0) return null;
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      {figures.map((fig) => (
        <Figure
          key={fig.label}
          label={fig.label}
          value={fig.value}
          unit={fig.unit}
          note={fig.note}
        />
      ))}
    </div>
  );
}

function paceBars(splits: ActivitySplits) {
  const speeds = splits.rows.map((row) =>
    row.duration_s > 0 ? row.distance_m / row.duration_s : 0,
  );
  return {
    speeds,
    fastest: Math.max(...speeds, 0),
    slowest: Math.min(...speeds.filter((s) => s > 0)),
  };
}

/** Per kilometre (a run) or per lap: pace as a bar, heart rate and the climb. */
export function Splits({ splits, group }: { splits: ActivitySplits; group: Group }) {
  const { speeds, fastest } = paceBars(splits);
  const km = splits.kind === 'km';
  const unit = group === 'swim' ? 100 : 1000;
  const hasPower = splits.rows.some((row) => row.avg_power !== null);
  const color = SPORTS[group].color;
  return (
    <Section title={km ? 'Splits' : 'Laps'} aside={km ? 'per km' : undefined}>
      <Table label={km ? 'Splits per kilometre' : 'Laps'}>
        <thead>
          <tr>
            <th className={th}>{km ? 'Km' : 'Lap'}</th>
            {!km && <th className={th}>Distance</th>}
            {!km && <th className={th}>Time</th>}
            <th className={th}>
              {group === 'bike' ? 'Speed' : `Pace /${unit === 100 ? '100 m' : 'km'}`}
            </th>
            <th className={th}>Heart rate</th>
            {hasPower && <th className={th}>Power</th>}
            <th className={th}>Elevation</th>
          </tr>
        </thead>
        <tbody>
          {splits.rows.map((row, index) => {
            const speed = speeds[index] ?? 0;
            const full = km && row.distance_m < 1000 ? ` (${formatDistance(row.distance_m)})` : '';
            return (
              <tr key={row.index} className="border-t">
                <td className={td}>
                  {row.index}
                  {full}
                </td>
                {!km && <td className={td}>{formatDistance(row.distance_m)}</td>}
                {!km && <td className={td}>{formatDuration(row.duration_s)}</td>}
                <td className={td}>
                  <span className="flex min-w-36 items-center gap-2">
                    <span className="w-10 text-right font-semibold">
                      {speed === 0
                        ? '–'
                        : group === 'bike'
                          ? number(speed * KM_PER_H, 1)
                          : formatPace(unit / speed)}
                    </span>
                    {km && (
                      <span aria-hidden className="h-2 min-w-12 flex-1 rounded-full bg-surface-2">
                        <span
                          className="block h-2 rounded-full"
                          style={{
                            width: `${fastest > 0 ? Math.max(8, (speed / fastest) * 100) : 0}%`,
                            background: color,
                          }}
                        />
                      </span>
                    )}
                  </span>
                </td>
                <td className={td}>{row.avg_hr === null ? '–' : number(row.avg_hr)}</td>
                {hasPower && (
                  <td className={td}>{row.avg_power === null ? '–' : number(row.avg_power)}</td>
                )}
                <td className={td}>
                  {row.elevation_change_m === null
                    ? '–'
                    : `${row.elevation_change_m > 0 ? '+' : row.elevation_change_m < 0 ? '−' : ''}${number(Math.abs(row.elevation_change_m))} m`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </Table>
    </Section>
  );
}

const ZONE_COLORS = [
  'var(--zone-1)',
  'var(--zone-2)',
  'var(--zone-3)',
  'var(--zone-4)',
  'var(--zone-5)',
];

export function Zones({ zones }: { zones: ActivityZones }) {
  const total = zones.seconds.reduce((sum, s) => sum + s, 0) + zones.below_s;
  const rows = [
    ...(zones.below_s > 0 ? [{ name: '<Z1', seconds: zones.below_s, color: 'var(--faint)' }] : []),
    ...zones.seconds.map((seconds, i) => ({
      name: `Z${i + 1}`,
      seconds,
      color: ZONE_COLORS[i] ?? 'var(--primary)',
    })),
  ];
  return (
    <Section
      title="Heart-rate zones"
      aside={
        zones.source === 'garmin'
          ? 'Garmin zones'
          : zones.threshold
            ? `Threshold ${Math.round(zones.threshold)}`
            : undefined
      }
    >
      <ul>
        {rows.map((row) => (
          <li
            key={row.name}
            className="grid grid-cols-[34px_minmax(0,1fr)_92px] items-center gap-3 py-1.5 text-[13px] tabular-nums"
          >
            <span className="font-semibold">{row.name}</span>
            <span aria-hidden className="h-3 overflow-hidden rounded-full bg-surface-2">
              <span
                className="block h-3 rounded-full"
                style={{
                  width: `${total > 0 ? (row.seconds / total) * 100 : 0}%`,
                  background: row.color,
                }}
              />
            </span>
            <span className="text-right text-muted-foreground">
              {formatDuration(row.seconds)} ·{' '}
              {total > 0 ? Math.round((row.seconds / total) * 100) : 0}%
            </span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

export function Durability({
  durability,
  group,
}: {
  durability: ActivityDurability;
  group: Group;
}) {
  const bike = group === 'bike';
  const { first, second, efficiency_90d: baseline } = durability;
  const better = baseline !== null && durability.efficiency_factor >= baseline;
  const pace = (speed: number | null | undefined) =>
    speed
      ? bike
        ? `${number(speed * KM_PER_H, 1)} km/h`
        : `${formatPace(1000 / speed)} /km`
      : '–';
  return (
    <Section title="Aerobic durability">
      <div className="grid grid-cols-2 gap-2.5">
        <Mini
          label="Decoupling"
          value={number(durability.decoupling_pct, 1)}
          unit="%"
          note={
            durability.steady === null ? undefined : (
              <span
                className={cn(durability.steady && durability.decoupling_pct < 5 && 'text-good')}
              >
                {durability.steady ? 'Steady' : 'Variable effort'}
              </span>
            )
          }
        />
        <Mini
          label="Efficiency"
          value={number(durability.efficiency_factor, 2)}
          note={
            baseline !== null && (
              <span
                className={cn('inline-flex items-center gap-1', better ? 'text-good' : undefined)}
              >
                {better ? (
                  <ArrowUp className="size-3.5" aria-hidden />
                ) : (
                  <ArrowDown className="size-3.5" aria-hidden />
                )}
                vs {number(baseline, 2)} 90-day
              </span>
            )
          }
        />
      </div>
      {first && second && (
        <Table label="First and second half">
          <thead>
            <tr>
              <th className={th}>
                <span className="sr-only">Half</span>
              </th>
              <th className={th}>{bike ? 'Speed' : 'Pace'}</th>
              <th className={th}>Heart rate</th>
              <th className={th}>Efficiency</th>
            </tr>
          </thead>
          <tbody>
            {[
              ['First half', first],
              ['Second half', second],
            ].map(([name, half]) => {
              const h = half as typeof first;
              return (
                <tr key={name as string} className="border-t">
                  <td className={cn(td, 'text-muted-foreground')}>{name as string}</td>
                  <td className={td}>{pace(h.speed)}</td>
                  <td className={td}>{h.heart_rate === null ? '–' : number(h.heart_rate)}</td>
                  <td className={td}>{h.efficiency === null ? '–' : number(h.efficiency, 2)}</td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      )}
    </Section>
  );
}

function FormFigure({
  label,
  unit,
  pair,
  places = 0,
  scale = 1,
}: {
  label: string;
  unit: string;
  pair: ActivityPair;
  places?: number;
  scale?: number;
}) {
  if (pair.value === null) return null;
  return (
    <Mini
      label={label}
      value={number(pair.value * scale, places)}
      unit={unit}
      note={pair.avg_90d === null ? undefined : `90-day ${number(pair.avg_90d * scale, places)}`}
    />
  );
}

/** Running form, each average beside the member's 90-day average of runs. */
export function RunningForm({ form }: { form: ActivityForm }) {
  return (
    <Section title="Running form" aside="vs 90-day average">
      <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3 xl:grid-cols-6">
        <FormFigure label="Cadence" unit="spm" pair={form.cadence} />
        <FormFigure label="Stride" unit="m" pair={form.stride_cm} places={2} scale={0.01} />
        <FormFigure label="Ground contact" unit="ms" pair={form.ground_contact_ms} />
        <FormFigure
          label="Vertical oscillation"
          unit="cm"
          pair={form.vertical_oscillation_cm}
          places={1}
        />
        <FormFigure label="Vertical ratio" unit="%" pair={form.vertical_ratio_pct} places={1} />
        <FormFigure label="Power" unit="W" pair={form.power} />
      </div>
    </Section>
  );
}

const stroke = (name: string | null) =>
  name ? name.charAt(0).toUpperCase() + name.slice(1).replaceAll('_', ' ') : '–';

/** A pool swim: its sets with rest and SWOLF, and the SWOLF of every length. */
export function PoolSets({ pool, poolLength }: { pool: ActivityPool; poolLength: number | null }) {
  return (
    <>
      <Section title="Sets" aside={poolLength ? `${number(poolLength)} m pool` : undefined}>
        <Table label="Sets">
          <thead>
            <tr>
              <th className={th}>Set</th>
              <th className={th}>Lengths</th>
              <th className={th}>Distance</th>
              <th className={th}>Time</th>
              <th className={th}>Pace /100 m</th>
              <th className={th}>Rest</th>
              <th className={th}>SWOLF</th>
              <th className={th}>Stroke</th>
            </tr>
          </thead>
          <tbody>
            {pool.sets.map((set) => (
              <tr key={set.index} className="border-t">
                <td className={td}>{set.index}</td>
                <td className={td}>{set.lengths}</td>
                <td className={td}>{formatDistance(set.distance_m)}</td>
                <td className={td}>{formatDuration(set.duration_s)}</td>
                <td className={td}>
                  {set.distance_m > 0 ? formatPace((set.duration_s / set.distance_m) * 100) : '–'}
                </td>
                <td className={td}>{set.rest_s > 0 ? formatDuration(set.rest_s) : '–'}</td>
                <td className={td}>{set.swolf === null ? '–' : number(set.swolf)}</td>
                <td className={td}>{stroke(set.stroke)}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Section>
      {pool.lengths.some((length) => length.swolf !== null) && (
        <Section title="SWOLF by length">
          <SwolfBars lengths={pool.lengths} />
        </Section>
      )}
    </>
  );
}

export function Climbs({ climbs, bestVam }: { climbs: ActivityClimb[]; bestVam: number | null }) {
  return (
    <Section title="Climbs" aside={bestVam ? `Best ${number(bestVam)} m/h` : undefined}>
      <Table label="Climbs">
        <thead>
          <tr>
            <th className={th}>Climb</th>
            <th className={th}>Distance</th>
            <th className={th}>Gain</th>
            <th className={th}>Grade</th>
            <th className={th}>Time</th>
            <th className={th}>Climbing speed</th>
          </tr>
        </thead>
        <tbody>
          {climbs.map((climb, index) => (
            <tr key={climb.start_s} className="border-t">
              <td className={td}>{index + 1}</td>
              <td className={td}>{formatDistance(climb.distance_m)}</td>
              <td className={td}>+{number(climb.gain_m)} m</td>
              <td className={td}>{number(climb.grade * 100, 1)}%</td>
              <td className={td}>{formatDuration(climb.duration_s)}</td>
              <td className={td}>{number(climb.vam)} m/h</td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Section>
  );
}

/** A multisport activity's legs, each its own activity. */
export function Legs({ legs }: { legs: ActivityLeg[] }) {
  return (
    <Section title="Legs">
      <ul>
        {legs.map((leg) => (
          <li key={leg.id}>
            <Link
              to="/health/activities/$id"
              params={{ id: String(leg.id) }}
              className="grid grid-cols-[40px_minmax(0,1fr)_auto] items-center gap-3.5 rounded-[14px] px-2 py-2 hover:bg-surface-2"
            >
              <SportChip group={leg.group} />
              <span className="min-w-0 truncate text-[15px] font-semibold">
                {activityTitle(leg)}
              </span>
              <span className="text-right text-[13px] text-muted-foreground tabular-nums">
                {leg.distance_m ? `${formatDistance(leg.distance_m)} · ` : ''}
                {leg.duration_s ? formatDuration(leg.duration_s) : '–'}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </Section>
  );
}
