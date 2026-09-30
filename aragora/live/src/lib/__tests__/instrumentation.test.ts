/** @jest-environment node */

import { version } from '../../../package.json';

const mockSentryInit = jest.fn();
const mockPosthogInit = jest.fn();
const mockLoadSentry = jest.fn();
const mockLoadPosthog = jest.fn();
const mockLoadOtel = jest.fn();
const mockRegisterOTel = jest.fn();
jest.mock('@vercel/otel', () => {
  mockLoadOtel();
  return { registerOTel: mockRegisterOTel };
});
jest.mock('@sentry/nextjs', () => {
  mockLoadSentry();
  return { init: mockSentryInit };
});
jest.mock('posthog-js', () => {
  mockLoadPosthog();
  return { __esModule: true, default: { init: mockPosthogInit } };
});

describe('telemetry instrumentation', () => {
  const originalEnv = process.env;

  beforeEach(() => {
    jest.resetModules();
    jest.clearAllMocks();
    process.env = { ...originalEnv };
    for (const key of [
      'SENTRY_DSN',
      'SENTRY_ENVIRONMENT',
      'NEXT_PUBLIC_SENTRY_DSN',
      'NEXT_PUBLIC_BUILD_SHA',
      'NEXT_PUBLIC_POSTHOG_KEY',
      'NEXT_PUBLIC_POSTHOG_HOST',
      'OTEL_EXPORTER_OTLP_ENDPOINT',
      'NEXT_RUNTIME',
    ]) {
      delete process.env[key];
    }
  });

  afterEach(() => {
    process.env = originalEnv;
  });

  it('imports neither client SDK without public keys', async () => {
    const { telemetryReady } = await import('../../../instrumentation-client');
    await telemetryReady;
    expect(mockLoadSentry).not.toHaveBeenCalled();
    expect(mockLoadPosthog).not.toHaveBeenCalled();
    expect(mockSentryInit).not.toHaveBeenCalled();
    expect(mockPosthogInit).not.toHaveBeenCalled();
  });

  it('initializes Sentry alone with the build SHA and environment', async () => {
    process.env.NEXT_PUBLIC_SENTRY_DSN = 'http://public@localhost:3141/1';
    process.env.NEXT_PUBLIC_BUILD_SHA = 'build-sha';
    const { telemetryReady } = await import('../../../instrumentation-client');
    await telemetryReady;
    expect(mockSentryInit).toHaveBeenCalledWith(
      expect.objectContaining({
        dsn: 'http://public@localhost:3141/1',
        release: 'build-sha',
        environment: 'test',
      }),
    );
    expect(mockLoadPosthog).not.toHaveBeenCalled();
  });

  it('falls back to the package version for the client release', async () => {
    process.env.NEXT_PUBLIC_SENTRY_DSN = 'http://public@localhost:3141/1';
    const { telemetryReady } = await import('../../../instrumentation-client');
    await telemetryReady;
    expect(mockSentryInit).toHaveBeenCalledWith(
      expect.objectContaining({ release: version, environment: 'test' }),
    );
  });

  it('initializes PostHog alone with the host and pageview capture', async () => {
    process.env.NEXT_PUBLIC_POSTHOG_KEY = 'phc_test';
    process.env.NEXT_PUBLIC_POSTHOG_HOST = 'http://localhost:3142';
    const { telemetryReady } = await import('../../../instrumentation-client');
    await telemetryReady;
    expect(mockPosthogInit).toHaveBeenCalledWith(
      'phc_test',
      expect.objectContaining({
        api_host: 'http://localhost:3142',
        capture_pageview: true,
        disable_compression: true,
      }),
    );
    expect(mockLoadSentry).not.toHaveBeenCalled();
  });

  it.each(['nodejs', 'edge'])('register skips Sentry for %s without a DSN', async (runtime) => {
    process.env.NEXT_RUNTIME = runtime;
    const { register } = await import('../../../instrumentation');
    await register();
    expect(mockLoadSentry).not.toHaveBeenCalled();
    expect(mockSentryInit).not.toHaveBeenCalled();
  });

  it.each([undefined, ''])('register skips the OTel import with endpoint %s', async (endpoint) => {
    if (endpoint !== undefined) process.env.OTEL_EXPORTER_OTLP_ENDPOINT = endpoint;
    const { register } = await import('../../../instrumentation');
    await register();
    expect(mockLoadOtel).not.toHaveBeenCalled();
    expect(mockRegisterOTel).not.toHaveBeenCalled();
  });

  it.each(['nodejs', 'edge'])(
    'register enables OTel alone in %s with an endpoint',
    async (runtime) => {
      process.env.NEXT_RUNTIME = runtime;
      process.env.OTEL_EXPORTER_OTLP_ENDPOINT = 'http://localhost:4318';
      const { register } = await import('../../../instrumentation');
      expect(mockLoadOtel).not.toHaveBeenCalled();
      await register();
      expect(mockLoadOtel).toHaveBeenCalledTimes(1);
      expect(mockRegisterOTel).toHaveBeenCalledTimes(1);
      expect(mockRegisterOTel).toHaveBeenCalledWith({ serviceName: 'aragora-live' });
      expect(mockLoadSentry).not.toHaveBeenCalled();
    },
  );

  it.each(['nodejs', 'edge'])('register enables both SDKs independently in %s', async (runtime) => {
    process.env.NEXT_RUNTIME = runtime;
    process.env.OTEL_EXPORTER_OTLP_ENDPOINT = 'http://localhost:4318';
    process.env.SENTRY_DSN = 'http://public@localhost:3141/1';
    const { register } = await import('../../../instrumentation');
    await register();
    expect(mockRegisterOTel).toHaveBeenCalledTimes(1);
    expect(mockRegisterOTel).toHaveBeenCalledWith({ serviceName: 'aragora-live' });
    expect(mockSentryInit).toHaveBeenCalledTimes(1);
  });

  it('server and edge configs are safe to import directly without a DSN', async () => {
    await (
      await import('../../../sentry.server.config')
    ).sentryReady;
    await (
      await import('../../../sentry.edge.config')
    ).sentryReady;
    expect(mockLoadSentry).not.toHaveBeenCalled();
    expect(mockSentryInit).not.toHaveBeenCalled();
  });

  it.each(['nodejs', 'edge'])('register initializes %s only with a DSN', async (runtime) => {
    process.env.NEXT_RUNTIME = runtime;
    process.env.SENTRY_DSN = 'http://public@localhost:3141/1';
    process.env.SENTRY_ENVIRONMENT = 'staging';
    const { register } = await import('../../../instrumentation');
    await register();
    expect(mockLoadOtel).not.toHaveBeenCalled();
    expect(mockRegisterOTel).not.toHaveBeenCalled();
    expect(mockSentryInit).toHaveBeenCalledTimes(1);
    expect(mockSentryInit).toHaveBeenCalledWith(
      expect.objectContaining({
        dsn: 'http://public@localhost:3141/1',
        release: version,
        environment: 'staging',
      }),
    );
  });
});
