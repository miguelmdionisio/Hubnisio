import { useQueryClient } from '@tanstack/react-query';
import { RotateCw } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { cn } from '@/lib/utils';

/** How far the page must be pulled before letting go refreshes it. */
const THRESHOLD = 72; // px
const MAX_PULL = 110; // px

/**
 * Pull down at the top of a page to refetch its data (M9 P4): the installed app has no browser
 * reload. It refetches what the page shows, nothing more: a bank sync has its own button and
 * limits. Touch only; nothing happens while a sheet or dialog is open (they lock the page).
 */
export function PullToRefresh() {
  const queryClient = useQueryClient();
  const [pull, setPull] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const state = useRef({ startY: 0, startX: 0, active: false, pulling: false, pull: 0 });

  useEffect(() => {
    const s = state.current;
    const locked = () =>
      document.body.hasAttribute('data-scroll-locked') ||
      document.body.style.pointerEvents === 'none';

    const onStart = (event: TouchEvent) => {
      const touch = event.touches[0];
      s.active = !!touch && event.touches.length === 1 && window.scrollY <= 0 && !locked();
      s.pulling = false;
      s.pull = 0;
      if (touch) {
        s.startY = touch.clientY;
        s.startX = touch.clientX;
      }
    };
    const onMove = (event: TouchEvent) => {
      const touch = event.touches[0];
      if (!s.active || !touch) return;
      const dy = touch.clientY - s.startY;
      const dx = touch.clientX - s.startX;
      if (!s.pulling) {
        if (dy <= 6 || Math.abs(dx) > dy || window.scrollY > 0) {
          if (Math.abs(dy) > 6 || Math.abs(dx) > 6) s.active = false;
          return;
        }
        s.pulling = true;
      }
      event.preventDefault();
      // Resists as it goes, like the system's.
      s.pull = Math.min(MAX_PULL, dy * 0.55);
      setPull(s.pull);
    };
    const onEnd = () => {
      if (!s.active) return;
      s.active = false;
      const go = s.pulling && s.pull >= THRESHOLD;
      s.pulling = false;
      setPull(0);
      if (!go) return;
      setRefreshing(true);
      void queryClient.refetchQueries({ type: 'active' }).finally(() => setRefreshing(false));
    };

    document.addEventListener('touchstart', onStart, { passive: true });
    document.addEventListener('touchmove', onMove, { passive: false });
    document.addEventListener('touchend', onEnd);
    document.addEventListener('touchcancel', onEnd);
    return () => {
      document.removeEventListener('touchstart', onStart);
      document.removeEventListener('touchmove', onMove);
      document.removeEventListener('touchend', onEnd);
      document.removeEventListener('touchcancel', onEnd);
    };
  }, [queryClient]);

  const shown = refreshing ? THRESHOLD : pull;
  if (shown === 0) return null;
  return (
    <div
      className="pointer-events-none fixed inset-x-0 top-[env(safe-area-inset-top)] z-40 flex justify-center"
      style={{ transform: `translateY(${shown - 28}px)` }}
    >
      {refreshing && (
        <span role="status" className="sr-only">
          Refreshing
        </span>
      )}
      <span className="grid size-9 place-items-center rounded-full bg-popover shadow-pop">
        <RotateCw
          className={cn('size-4 text-primary', refreshing && 'animate-spin')}
          style={refreshing ? undefined : { transform: `rotate(${(pull / THRESHOLD) * 270}deg)` }}
          aria-hidden
        />
      </span>
    </div>
  );
}
