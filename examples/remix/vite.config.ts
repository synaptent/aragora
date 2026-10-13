import { vitePlugin as remix } from '@remix-run/dev';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [remix({ ignoredRouteFiles: ['**/*.md'] })],
  optimizeDeps: { include: ['@aragora/sdk', '@remix-run/node'] },
});
