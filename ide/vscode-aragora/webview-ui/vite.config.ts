import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    // VS Code 1.85 uses Electron 25 / Chromium 114; keep this aligned with engines.vscode.
    target: 'chrome114',
    lib: {
      entry: 'src/main.tsx',
      name: 'AragoraWebview',
      // Extension panels load main.js with a classic <script>; do not emit ESM.
      formats: ['iife'],
      fileName: () => 'main.js',
      cssFileName: 'main',
    },
    rollupOptions: { output: { assetFileNames: 'main.[ext]' } },
    sourcemap: true,
    // Reduce chunk size for webview
    chunkSizeWarningLimit: 500,
  },
  // Ensure assets are relative for webview
  base: './',
});
