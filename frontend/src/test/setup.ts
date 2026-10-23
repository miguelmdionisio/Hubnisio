import { configure } from '@testing-library/react';

// Tests render the whole app, so the first lookup in a file includes loading every page.
// Testing Library's 1 s default is too tight for that on a busy machine or CI runner.
configure({ asyncUtilTimeout: 5000 });

// jsdom has no matchMedia; toasts use it to follow the system's light/dark setting.
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
}

// Nor ResizeObserver or scrollIntoView, which popovers and searchable lists use.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
Element.prototype.scrollIntoView ??= () => {};

// jsdom doesn't implement scrolling; navigating logs "not implemented" noise without this.
window.scrollTo = () => {};

// jsdom lays nothing out, so Recharts measures every chart as 0 x 0 and draws nothing.
const measure = Element.prototype.getBoundingClientRect;
Element.prototype.getBoundingClientRect = function getBoundingClientRect() {
  if (!this.classList.contains('recharts-responsive-container')) return measure.call(this);
  return {
    x: 0,
    y: 0,
    left: 0,
    top: 0,
    width: 800,
    height: 300,
    right: 800,
    bottom: 300,
  } as DOMRect;
};
