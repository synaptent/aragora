export async function register() {
  if (process.env.OTEL_EXPORTER_OTLP_ENDPOINT) {
    const { registerOTel } = await import('@vercel/otel');
    registerOTel({ serviceName: 'aragora-live' });
  }

  if (process.env.SENTRY_DSN) {
    if (process.env.NEXT_RUNTIME === 'nodejs') {
      const { sentryReady } = await import('./sentry.server.config');
      await sentryReady;
    }
    if (process.env.NEXT_RUNTIME === 'edge') {
      const { sentryReady } = await import('./sentry.edge.config');
      await sentryReady;
    }
  }
}
