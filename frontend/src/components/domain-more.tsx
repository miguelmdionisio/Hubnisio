import { Link } from '@tanstack/react-router';
import { Bell, Check, ChevronRight, type LucideIcon, Palette, Search } from 'lucide-react';
import type { ReactNode } from 'react';
import { DomainMark, PageHeader } from '@/components/app-shell';
import { DOMAINS, type Domain } from '@/components/domains';
import { useOpenSearch } from '@/components/search';
import { ThemeSwitch } from '@/components/theme-switch';

const rowClass =
  'grid w-full grid-cols-[34px_1fr_auto] items-center gap-3.5 min-h-11 rounded-[14px] px-3 py-2.5 text-left text-[15px] font-semibold';

function Chip({ icon: Icon }: { icon: LucideIcon }) {
  return (
    <span className="grid size-[34px] place-items-center rounded-full bg-surface-2" aria-hidden>
      <Icon className="size-4" />
    </span>
  );
}

function Group({ label, children }: { label?: string; children: ReactNode }) {
  return (
    <section className="mt-4 first:mt-0">
      {label && <h2 className="mb-1 px-1 text-[13px] font-semibold text-faint">{label}</h2>}
      <ul className="rounded-[18px] bg-surface p-1.5">{children}</ul>
    </section>
  );
}

/**
 * On a phone, the domains to switch between, the pages the tab bar leaves out in the sidebar's
 * groups, plus search and theme. Every domain's More page is this, given its domain.
 */
export function DomainMore({ domain }: { domain: Domain }) {
  const openSearch = useOpenSearch();
  return (
    <>
      <PageHeader title="More" />
      <div className="max-w-xl">
        <Group label="Domains">
          {DOMAINS.map((option) => (
            <li key={option.id}>
              <Link to={option.home} className={`${rowClass} hover:bg-surface-2`}>
                <DomainMark domain={option} />
                {option.name}
                {option.id === domain.id ? (
                  <Check className="size-4 text-primary" aria-hidden />
                ) : (
                  <ChevronRight className="size-4 text-faint" aria-hidden />
                )}
              </Link>
            </li>
          ))}
        </Group>
        {domain.groups.map((group) => {
          const items = group.items.filter((item) => !domain.tabs.includes(item.to));
          if (items.length === 0) return null;
          return (
            <Group key={group.label ?? ''} label={group.label}>
              {items.map((item) => (
                <li key={item.to}>
                  <Link to={item.to} className={`${rowClass} hover:bg-surface-2`}>
                    <Chip icon={item.icon} />
                    {item.label}
                    <ChevronRight className="size-4 text-faint" aria-hidden />
                  </Link>
                </li>
              ))}
            </Group>
          );
        })}
        <Group>
          <li>
            <Link to="/settings/notifications" className={`${rowClass} hover:bg-surface-2`}>
              <Chip icon={Bell} />
              Notifications
              <ChevronRight className="size-4 text-faint" aria-hidden />
            </Link>
          </li>
          <li>
            <button type="button" onClick={openSearch} className={`${rowClass} hover:bg-surface-2`}>
              <Chip icon={Search} />
              Search
              <ChevronRight className="size-4 text-faint" aria-hidden />
            </button>
          </li>
          <li className={rowClass}>
            <Chip icon={Palette} />
            Theme
            <ThemeSwitch />
          </li>
        </Group>
      </div>
    </>
  );
}
