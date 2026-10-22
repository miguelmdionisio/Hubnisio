import path from 'node:path';
import tailwindcss from '@tailwindcss/vite';
import basicSsl from '@vitejs/plugin-basic-ssl';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    // HTTPS with a self-signed certificate: Enable Banking only redirects back to https URLs.
    // Tests don't serve pages, so they skip it.
    ...(process.env.VITEST ? [] : [basicSsl()]),
  ],
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, 'src') },
  },
  server: {
    // In Docker Compose the API is reachable as "api"; locally it's on localhost.
    proxy: { '/api': process.env.API_PROXY_TARGET ?? 'http://localhost:8000' },
    // A Windows host's file events don't reach the container, so Compose turns on polling.
    watch: process.env.WATCH_POLLING ? { usePolling: true } : undefined,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['src/test/setup.ts'],
  },
});
