import {
  Baby,
  Banknote,
  Bike,
  Briefcase,
  Car,
  CarTaxiFront,
  CircleDashed,
  Clapperboard,
  Coffee,
  Coins,
  Dumbbell,
  Film,
  Flower2,
  Fuel,
  Gift,
  GraduationCap,
  HeartPulse,
  House,
  Lamp,
  Landmark,
  type LucideIcon,
  Package,
  Palette,
  PawPrint,
  Percent,
  Pill,
  Plane,
  Receipt,
  Repeat,
  Scissors,
  Shield,
  ShieldCheck,
  ShieldPlus,
  Shirt,
  ShoppingBag,
  ShoppingCart,
  Smartphone,
  SquareParking,
  Stethoscope,
  Tag,
  Ticket,
  TramFront,
  Undo2,
  User,
  Users,
  Utensils,
  UtensilsCrossed,
  Wallet,
  Wifi,
  Wrench,
  Zap,
} from 'lucide-react';
import { useMemo } from 'react';
import { cn } from '@/lib/utils';
import { useCategories } from '@/routes/finance/category-picker';

type Hue =
  | 'indigo'
  | 'green'
  | 'orange'
  | 'sky'
  | 'pink'
  | 'purple'
  | 'red'
  | 'gold'
  | 'grey'
  | 'teal'
  | 'brown';

const HUES: Hue[] = ['indigo', 'green', 'orange', 'sky', 'pink', 'purple', 'red', 'gold', 'teal'];

/**
 * The seeded categories (backend `finance/defaults.py`) by name: an icon and a hue. A category
 * the household made itself takes its group's, then a hue picked from its name.
 */
const SEEDED: Record<string, [LucideIcon, Hue]> = {
  Housing: [House, 'indigo'],
  'Rent & mortgage': [House, 'indigo'],
  Utilities: [Zap, 'teal'],
  'Internet & phone': [Wifi, 'sky'],
  'Home & garden': [Flower2, 'green'],
  'Home insurance': [ShieldCheck, 'grey'],
  Food: [Utensils, 'green'],
  Groceries: [ShoppingCart, 'green'],
  Restaurants: [UtensilsCrossed, 'orange'],
  'Cafés & snacks': [Coffee, 'brown'],
  'Food delivery': [Bike, 'red'],
  Transport: [Car, 'sky'],
  Fuel: [Fuel, 'gold'],
  'Public transport': [TramFront, 'sky'],
  'Taxi & ride-hailing': [CarTaxiFront, 'teal'],
  'Parking & tolls': [SquareParking, 'grey'],
  'Car maintenance': [Wrench, 'brown'],
  'Car insurance': [ShieldCheck, 'indigo'],
  Shopping: [ShoppingBag, 'pink'],
  Clothing: [Shirt, 'pink'],
  Electronics: [Smartphone, 'indigo'],
  'Household items': [Lamp, 'teal'],
  'Online shopping': [Package, 'orange'],
  Health: [HeartPulse, 'red'],
  Pharmacy: [Pill, 'red'],
  'Doctors & dentist': [Stethoscope, 'sky'],
  'Sport & fitness': [Dumbbell, 'green'],
  'Health insurance': [ShieldPlus, 'grey'],
  Leisure: [Film, 'gold'],
  Entertainment: [Clapperboard, 'gold'],
  Subscriptions: [Repeat, 'purple'],
  Travel: [Plane, 'sky'],
  Hobbies: [Palette, 'pink'],
  'Events & tickets': [Ticket, 'orange'],
  'Bills & fees': [Receipt, 'grey'],
  'Bank fees': [Landmark, 'grey'],
  Taxes: [Receipt, 'brown'],
  'Other insurance': [Shield, 'grey'],
  Personal: [User, 'pink'],
  'Personal care': [Scissors, 'pink'],
  'Gifts & donations': [Gift, 'red'],
  Education: [GraduationCap, 'indigo'],
  Family: [Users, 'orange'],
  Children: [Baby, 'orange'],
  Pets: [PawPrint, 'brown'],
  Cash: [Banknote, 'teal'],
  'Cash withdrawals': [Banknote, 'teal'],
  Income: [Wallet, 'green'],
  Salary: [Briefcase, 'green'],
  Refunds: [Undo2, 'green'],
  Interest: [Percent, 'green'],
  Dividends: [Coins, 'green'],
  'Other income': [Wallet, 'green'],
};

export type CategoryStyle = { name: string; icon: LucideIcon; color: string };

export const UNCATEGORIZED: CategoryStyle = {
  name: 'Uncategorized',
  icon: CircleDashed,
  color: 'var(--cat-grey)',
};

function hueOf(name: string): Hue {
  let hash = 0;
  for (const char of name) hash = (hash * 31 + char.charCodeAt(0)) | 0;
  return HUES[Math.abs(hash) % HUES.length] ?? 'grey';
}

export function categoryStyle(name: string, groupName?: string): CategoryStyle {
  const [icon, hue] = SEEDED[name] ??
    (groupName ? SEEDED[groupName] : undefined) ?? [Tag, hueOf(name)];
  return { name, icon, color: `var(--cat-${hue})` };
}

/** Every category and group by ID with its icon and colour; `null` is Uncategorized. */
export function useCategoryStyles(): (id: string | null | undefined) => CategoryStyle {
  const { data } = useCategories();
  return useMemo(() => {
    const styles = new Map<string, CategoryStyle>();
    for (const group of data ?? []) {
      styles.set(group.id, categoryStyle(group.name));
      for (const child of group.children) {
        styles.set(child.id, categoryStyle(child.name, group.name));
      }
    }
    return (id) => (id ? (styles.get(id) ?? { ...UNCATEGORIZED, name: '…' }) : UNCATEGORIZED);
  }, [data]);
}

/** A round chip: the category's icon on its colour, or a letter (a merchant's initial). */
export function Chip({
  style,
  letter,
  size = 'md',
  className,
}: {
  style?: CategoryStyle;
  letter?: string;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}) {
  const Icon = style?.icon;
  return (
    <span
      aria-hidden
      className={cn(
        'grid shrink-0 place-items-center rounded-full font-bold text-white',
        className,
        size === 'sm' && 'size-[34px] text-[13px] [&>svg]:size-4',
        size === 'md' && 'size-10 text-[15px] [&>svg]:size-[19px]',
        size === 'lg' && 'size-14 text-xl [&>svg]:size-6',
        !style && 'bg-surface-2 text-foreground',
      )}
      style={style ? { background: style.color } : undefined}
    >
      {letter ? letter.slice(0, 1).toUpperCase() : Icon && <Icon strokeWidth={2.1} />}
    </span>
  );
}
