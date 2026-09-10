/** @type {import('next').NextConfig} */
const withBundleAnalyzer = require('@next/bundle-analyzer')({
  enabled: process.env.ANALYZE === 'true',
});

const liveDeployMode =
  process.env.LIVE_DEPLOY_MODE || process.env.ARAGORA_LIVE_DEPLOY_MODE || 'runtime';
const requestedOutput = process.env.NEXT_OUTPUT || process.env.ARAGORA_NEXT_OUTPUT;
const defaultOutput = liveDeployMode === 'static-export' ? 'export' : undefined;
const resolvedOutput = requestedOutput || defaultOutput;
const isExport = resolvedOutput === 'export';

// Embed build SHA at build time (set by CI/CD, falls back to git)
const { execSync } = require('child_process');
const buildSha =
  process.env.NEXT_PUBLIC_BUILD_SHA ||
  (() => {
    try {
      return execSync('git rev-parse HEAD', { encoding: 'utf-8' }).trim();
    } catch {
      return 'unknown';
    }
  })();
const buildTime = process.env.NEXT_PUBLIC_BUILD_TIME || new Date().toISOString();

const nextConfig = {
  // Output mode is controlled by NEXT_OUTPUT/ARAGORA_NEXT_OUTPUT.
  // Runtime deployments (e.g. Vercel) use Next.js default output.
  ...(resolvedOutput ? { output: resolvedOutput } : {}),
  // Fixed build ID eliminates the Next.js 16.1.x race condition where the
  // "finalizing page optimization" step reads _ssgManifest.js under one build ID
  // while it was written under another, causing ENOENT.  A deterministic ID based
  // on the git SHA ensures a single, consistent directory name throughout the build.
  generateBuildId: async () => {
    return buildSha.slice(0, 12) || 'build';
  },
  trailingSlash: true,
  images: { unoptimized: true },
  env: { NEXT_PUBLIC_BUILD_SHA: buildSha, NEXT_PUBLIC_BUILD_TIME: buildTime },
  // redirects and rewrites are not supported with output: 'export'.
  // When exporting statically, these are handled by the hosting platform
  // (e.g. Cloudflare Pages _redirects file, Vercel vercel.json, etc.)
  ...(isExport
    ? {}
    : {
        async redirects() {
          return [
            { source: '/', destination: '/landing/', permanent: false },
            { source: '/docs', destination: 'https://docs.aragora.ai', permanent: false },
            {
              source: '/docs/:path*',
              destination: 'https://docs.aragora.ai/docs/:path*',
              permanent: false,
            },
          ];
        },
        async rewrites() {
          const apiUrl =
            process.env.NEXT_PUBLIC_API_URL ||
            (process.env.NODE_ENV === 'production'
              ? 'https://api.aragora.ai'
              : 'http://localhost:8080');
          return [{ source: '/api/:path*', destination: `${apiUrl}/api/:path*` }];
        },
      }),
};

const config = withBundleAnalyzer(nextConfig);
if (process.env.SENTRY_DSN) {
  const { withSentryConfig } = require('@sentry/nextjs');
  module.exports = withSentryConfig(config, {
    silent: true,
    sourcemaps: { disable: !process.env.SENTRY_AUTH_TOKEN },
    authToken: process.env.SENTRY_AUTH_TOKEN,
  });
} else {
  module.exports = config;
}
