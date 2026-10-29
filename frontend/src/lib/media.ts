import { useEffect, useState } from 'react';

const DESKTOP = '(min-width: 768px)';

/** True from 768px: the sidebar's breakpoint. Below it, the phone's layout. */
export function useIsDesktop(): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(DESKTOP).matches);
  useEffect(() => {
    const list = window.matchMedia(DESKTOP);
    const update = () => setMatches(list.matches);
    list.addEventListener('change', update);
    return () => list.removeEventListener('change', update);
  }, []);
  return matches;
}
