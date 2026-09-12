import { version } from './package.json';

async function initializeTelemetry() {
  if (process.env.NEXT_PUBLIC_SENTRY_DSN) {
    const Sentry = await import('@sentry/nextjs');
    Sentry.init({
      dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
      release: process.env.NEXT_PUBLIC_BUILD_SHA || version,
      environment: process.env.NODE_ENV,
      sendDefaultPii: false,
    });
  }

  if (process.env.NEXT_PUBLIC_POSTHOG_KEY) {
    const { default: posthog } = await import('posthog-js');
    posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY, {
      api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST || 'https://us.i.posthog.com',
      capture_pageview: true,
      // Keep event payloads inspectable by self-hosted ingestion proxies and capture stubs.
      disable_compression: true,
      autocapture: false,
      disable_session_recording: true,
      person_profiles: 'identified_only',
    });
  }
}

// Optional telemetry must not prevent the app from starting if an SDK fails to load.
export const telemetryReady = initializeTelemetry().catch(() => {});
