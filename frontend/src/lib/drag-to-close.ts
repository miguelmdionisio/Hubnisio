import { useEffect } from 'react';

/** How far, or how fast, a sheet must be pulled down to close rather than spring back. */
const CLOSE_DISTANCE = 110; // px
const CLOSE_SPEED = 0.6; // px per ms

/**
 * A bottom sheet follows the finger down and closes when let go far or fast enough (M9 P4).
 * The pull starts on the handle, or anywhere while the sheet's own content is scrolled to the
 * top, so scrolling a long sheet still scrolls it. Touch only: the desktop has no bottom sheets.
 */
export function useDragToClose(sheet: HTMLElement | null, enabled: boolean, close: () => void) {
  useEffect(() => {
    if (!enabled || !sheet) return;
    let start: { y: number; x: number; time: number } | null = null;
    let offset = 0;
    let dragging = false;

    const move = (y: number, animate: boolean) => {
      sheet.style.transition = animate ? 'transform 200ms ease-out' : 'none';
      sheet.style.transform = y > 0 ? `translateY(${y}px)` : '';
    };

    const onStart = (event: TouchEvent) => {
      const touch = event.touches[0];
      if (!touch || event.touches.length > 1) return;
      const fromHandle =
        event.target instanceof Element && event.target.closest('[data-sheet-handle]');
      if (!fromHandle && sheet.scrollTop > 0) return;
      start = { y: touch.clientY, x: touch.clientX, time: event.timeStamp };
      offset = 0;
      dragging = false;
    };

    const onMove = (event: TouchEvent) => {
      const touch = event.touches[0];
      if (!start || !touch) return;
      const dy = touch.clientY - start.y;
      const dx = touch.clientX - start.x;
      if (!dragging) {
        // Only a downward, mostly vertical pull is ours; anything else scrolls as usual.
        if (dy <= 4 || Math.abs(dx) > dy) {
          if (Math.abs(dy) > 4 || Math.abs(dx) > 4) start = null;
          return;
        }
        dragging = true;
      }
      event.preventDefault();
      offset = Math.max(0, dy);
      move(offset, false);
    };

    const onEnd = (event: TouchEvent) => {
      if (!start) return;
      const speed = offset / Math.max(1, event.timeStamp - start.time);
      start = null;
      if (!dragging) return;
      dragging = false;
      if (offset > CLOSE_DISTANCE || (offset > 30 && speed > CLOSE_SPEED)) {
        move(sheet.offsetHeight, true);
        close();
      } else {
        move(0, true);
      }
    };

    sheet.addEventListener('touchstart', onStart, { passive: true });
    sheet.addEventListener('touchmove', onMove, { passive: false });
    sheet.addEventListener('touchend', onEnd);
    sheet.addEventListener('touchcancel', onEnd);
    return () => {
      sheet.removeEventListener('touchstart', onStart);
      sheet.removeEventListener('touchmove', onMove);
      sheet.removeEventListener('touchend', onEnd);
      sheet.removeEventListener('touchcancel', onEnd);
      sheet.style.transform = '';
      sheet.style.transition = '';
    };
  }, [sheet, enabled, close]);
}
