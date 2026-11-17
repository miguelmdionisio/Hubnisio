import path from 'node:path';
import tailwindcss from '@tailwindcss/vite';
import basicSsl from '@vitejs/plugin-basic-ssl';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// The PC's Tailscale name (README, "On the iPhone"): the dev server and the phone's build answer
// to it as well as to localhost. Unset, they answer to localhost only.
const phoneHost = process.env.HUBNISIO_PHONE_HOST?.trim();
const allowedHosts = phoneHost ? [phoneHost] : [];

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    // HTTPS with a self-signed certificate: Enable Banking only redirects back to https URLs.
    // Tests don't serve pages, so they skip it, and so does the phone's build: `tailscale serve`
    // gives it a real certificate in front of plain HTTP.
    ...(process.env.VITEST || process.env.PLAIN_HTTP ? [] : [basicSsl()]),
  ],
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, 'src') },
  },
  server: {
    // In Docker Compose the API is reachable as "api"; locally it's on localhost.
    proxy: { '/api': process.env.API_PROXY_TARGET ?? 'http://localhost:8000' },
    // A Windows host's file events don't reach the container, so Compose turns on polling.
    watch: process.env.WATCH_POLLING ? { usePolling: true } : undefined,
    allowedHosts,
  },
  // `vite preview`, the phone's build: it reuses server.proxy for /api.
  preview: { allowedHosts },
  test: {
    environment: 'jsdom',
    setupFiles: ['src/test/setup.ts'],
  },
});
