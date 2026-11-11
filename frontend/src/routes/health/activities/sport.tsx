import { Activity, Bike, Dumbbell, Footprints, Layers, type LucideIcon, Waves } from 'lucide-react';
import type { ActivityLeg } from '@/api/types.gen';
import { cn } from '@/lib/utils';

export type Group = ActivityLeg['group'];

type Sport = { label: string; icon: LucideIcon; color: string; ink: string };

/** Each sport's name, icon and colour (`--sport-*` in index.css); the ink is the icon's colour. */
export const SPORTS: Record<Group, Sport> = {
  swim: { label: 'Swim', icon: Waves, color: 'var(--sport-swim)', ink: '#0b1b2b' },
  bike: { label: 'Bike', icon: Bike, color: 'var(--sport-bike)', ink: '#1c1230' },
  run: { label: 'Run', icon: Footprints, color: 'var(--sport-run)', ink: '#2b2105' },
  strength: { label: 'Strength', icon: Dumbbell, color: 'var(--sport-strength)', ink: '#10131a' },
  other: { label: 'Other', icon: Activity, color: 'var(--surface-2)', ink: 'var(--foreground)' },
};

/** The sport's icon on its colour; a multisport activity (`multi`) gets the layers instead. */
export function SportChip({
  group,
  multi,
  size = 'md',
}: {
  group: Group;
  multi?: boolean;
  size?: 'xs' | 'md';
}) {
  const sport = SPORTS[group];
  const Icon = multi ? Layers : sport.icon;
  return (
    <span
      aria-hidden
      className={cn(
        'grid shrink-0 place-items-center rounded-full',
        size === 'md' ? 'size-10 [&>svg]:size-[19px]' : 'size-[22px] [&>svg]:size-3',
      )}
      style={{ background: multi ? 'var(--surface-2)' : sport.color, color: sport.ink }}
    >
      <Icon strokeWidth={2.1} />
    </span>
  );
}

/** The activity's own name, else its sport's. */
export function activityTitle(activity: { name: string | null; group: Group }): string {
  return activity.name || SPORTS[activity.group].label;
}
