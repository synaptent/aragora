export async function register() {
  // OTel registration is added here by m6-live-otel, independently of Sentry.
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
