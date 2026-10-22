import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // In Docker Compose the API is reachable as "api"; locally it's on localhost.
    proxy: { '/api': process.env.API_PROXY_TARGET ?? 'http://localhost:8000' },
    // A Windows host's file events don't reach the container, so Compose turns on polling.
    watch: process.env.WATCH_POLLING ? { usePolling: true } : undefined,
  },
  test: {
    environment: 'jsdom',
  },
});
