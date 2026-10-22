import { defineConfig } from '@hey-api/openapi-ts';

// Generates the typed API client from the backend's exported schema.
// Regenerate with `pnpm generate:api` after `uv run python scripts/export_openapi.py`.
export default defineConfig({
  input: '../backend/openapi.json',
  output: 'src/api',
  plugins: ['@hey-api/client-fetch', '@tanstack/react-query'],
});
