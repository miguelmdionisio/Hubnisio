/**
 * Page transitions (M9 P5): a detail page slides in from the right and back out to the right;
 * every other change (tabs, filters, the sidebar) is instant. Off with reduced motion. The
 * animations are in index.css, keyed by these view-transition types.
 */
const DETAIL_PAGES = [
  /^\/finance\/spending\/(category|merchant)\/[^/]+\/?$/,
  /^\/health\/activities\/[^/]+\/?$/,
];

export function isDetailPage(pathname: string): boolean {
  return DETAIL_PAGES.some((pattern) => pattern.test(pathname));
}

export type SlideType = 'slide-forward' | 'slide-back';

/** Which slide a move from one path to another gets, if any. */
export function slideFor(from: string | undefined, to: string): SlideType | undefined {
  if (from === undefined || from === to) return undefined;
  const fromDetail = isDetailPage(from);
  const toDetail = isDetailPage(to);
  if (toDetail && !fromDetail) return 'slide-forward';
  if (fromDetail && !toDetail) return 'slide-back';
  return undefined;
}

function reducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
  );
}

/** TanStack Router's `defaultViewTransition.types`: a slide, or no transition at all. */
export function viewTransitionTypes({
  fromLocation,
  toLocation,
  pathChanged,
}: {
  fromLocation?: { pathname: string };
  toLocation: { pathname: string };
  pathChanged: boolean;
}): string[] | false {
  if (!pathChanged || reducedMotion()) return false;
  const slide = slideFor(fromLocation?.pathname, toLocation.pathname);
  return slide ? [slide] : false;
}
