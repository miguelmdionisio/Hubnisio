import { useCanGoBack, useRouter } from '@tanstack/react-router';
import { ChevronLeft } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { isStandalone } from '@/lib/standalone';

const EDGE = 24; // px from the left edge where the swipe must start
const THRESHOLD = 80; // px across to go back

/**
 * Swipe in from the left edge to go back (M9 P4), in the installed app only: Safari's own tab
 * has the system gesture. If iOS turns out to give installed apps the gesture too, switch this
 * off (SWIPE_BACK) so a swipe doesn't go back twice.
 */
const SWIPE_BACK = true;

export function EdgeSwipeBack() {
  const router = useRouter();
  const canGoBack = useCanGoBack();
  const [shift, setShift] = useState(0);
  const state = useRef({ x: 0, y: 0, active: false, dx: 0 });
  const enabled = SWIPE_BACK && canGoBack && isStandalone();

  useEffect(() => {
    if (!enabled) return;
    const s = state.current;
    const onStart = (event: TouchEvent) => {
      const touch = event.touches[0];
      s.active =
        !!touch &&
        event.touches.length === 1 &&
        touch.clientX <= EDGE &&
        !document.body.hasAttribute('data-scroll-locked');
      s.dx = 0;
      if (touch) {
        s.x = touch.clientX;
        s.y = touch.clientY;
      }
    };
    const onMove = (event: TouchEvent) => {
      const touch = event.touches[0];
      if (!s.active || !touch) return;
      const dx = touch.clientX - s.x;
      const dy = touch.clientY - s.y;
      if (Math.abs(dy) > Math.abs(dx) && Math.abs(dy) > 8) {
        s.active = false;
        setShift(0);
        return;
      }
      if (dx <= 0) return;
      event.preventDefault();
      s.dx = dx;
      setShift(Math.min(dx, THRESHOLD * 1.4));
    };
    const onEnd = () => {
      if (!s.active) return;
      s.active = false;
      setShift(0);
      if (s.dx >= THRESHOLD) router.history.back();
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
  }, [enabled, router]);

  if (shift === 0) return null;
  const ready = shift >= THRESHOLD;
  return (
    <div
      aria-hidden
      className="pointer-events-none fixed top-1/2 left-0 z-40 grid size-10 place-items-center rounded-full bg-popover shadow-pop transition-colors"
      style={{ transform: `translate(${shift / 2 - 20}px, -50%)` }}
    >
      <ChevronLeft className={ready ? 'size-5 text-primary' : 'size-5 text-muted-foreground'} />
    </div>
  );
}
