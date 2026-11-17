import { defineConfig, minimal2023Preset } from '@vite-pwa/assets-generator/config';

// The app's icons (M9 P2), all from one square SVG: public/app-icon.svg. Draw it full-bleed
// with its subject inside the middle 80% (iOS rounds the corners, Android crops a circle).
// After replacing it: corepack pnpm icons
const ground = { background: '#0d0e13' };

export default defineConfig({
  headLinkOptions: { preset: '2023' },
  preset: {
    ...minimal2023Preset,
    maskable: { ...minimal2023Preset.maskable, padding: 0, resizeOptions: ground },
    apple: { ...minimal2023Preset.apple, padding: 0, resizeOptions: ground },
  },
  images: ['public/app-icon.svg'],
});
