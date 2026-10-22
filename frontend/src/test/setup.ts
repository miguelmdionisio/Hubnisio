import { configure } from '@testing-library/react';

// Tests render the whole app, so the first lookup in a file includes loading every page.
// Testing Library's 1 s default is too tight for that on a busy machine or CI runner.
configure({ asyncUtilTimeout: 5000 });
