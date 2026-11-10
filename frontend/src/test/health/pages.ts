/** Health's pages as the sidebar lists them: URL and title. */
export const HEALTH_PAGES = [
  { to: '/health', title: 'Today' },
  { to: '/health/activities', title: 'Activities' },
  { to: '/health/training', title: 'Training' },
  { to: '/health/performance', title: 'Performance' },
  { to: '/health/recovery', title: 'Recovery' },
  { to: '/health/sleep', title: 'Sleep' },
  { to: '/health/body', title: 'Body' },
  { to: '/health/garmin', title: 'Garmin' },
] as const;
