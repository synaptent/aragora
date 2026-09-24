import { version } from './package.json';

export const sentryReady = process.env.SENTRY_DSN
  ? import('@sentry/nextjs').then((Sentry) => {
      Sentry.init({
        dsn: process.env.SENTRY_DSN,
        release: process.env.NEXT_PUBLIC_BUILD_SHA || version,
        environment: process.env.SENTRY_ENVIRONMENT || process.env.NODE_ENV,
        sendDefaultPii: false,
      });
    })
  : Promise.resolve();
