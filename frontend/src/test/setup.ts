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
