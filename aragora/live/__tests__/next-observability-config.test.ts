/** @jest-environment node */

const mockWithSentryConfig = jest.fn((config) => config);
const mockLoadSentry = jest.fn();
jest.mock('@sentry/nextjs', () => {
  mockLoadSentry();
  return { withSentryConfig: mockWithSentryConfig };
});
jest.mock('@next/bundle-analyzer', () => () => (config: unknown) => config);
jest.mock('child_process', () => ({ execSync: () => 'test-build-sha' }));

describe('Next observability build wiring', () => {
  const originalEnv = process.env;

  beforeEach(() => {
    jest.resetModules();
    jest.clearAllMocks();
    process.env = { ...originalEnv };
    for (const key of [
      'SENTRY_DSN',
      'SENTRY_AUTH_TOKEN',
      'NEXT_PUBLIC_SENTRY_DSN',
      'NEXT_PUBLIC_POSTHOG_KEY',
    ]) {
      delete process.env[key];
    }
  });

  afterEach(() => {
    process.env = originalEnv;
  });

  it('inlines empty public keys so default bundles can eliminate the SDK imports', () => {
    const config = require('../next.config');
    expect(config.env.NEXT_PUBLIC_SENTRY_DSN).toBe('');
    expect(config.env.NEXT_PUBLIC_POSTHOG_KEY).toBe('');
    expect(mockLoadSentry).not.toHaveBeenCalled();
  });

  it('preserves public keys without loading the server build wrapper', () => {
    process.env.NEXT_PUBLIC_SENTRY_DSN = 'http://public@localhost:3141/1';
    process.env.NEXT_PUBLIC_POSTHOG_KEY = 'phc_test';
    const config = require('../next.config');
    expect(config.env.NEXT_PUBLIC_SENTRY_DSN).toBe('http://public@localhost:3141/1');
    expect(config.env.NEXT_PUBLIC_POSTHOG_KEY).toBe('phc_test');
    expect(mockLoadSentry).not.toHaveBeenCalled();
  });

  it.each([undefined, 'test-upload-token'])('gates source maps on the auth token (%s)', (token) => {
    process.env.SENTRY_DSN = 'http://public@localhost:3141/1';
    if (token) process.env.SENTRY_AUTH_TOKEN = token;
    require('../next.config');
    expect(mockWithSentryConfig).toHaveBeenCalledWith(expect.any(Object), {
      silent: true,
      sourcemaps: { disable: !token },
      authToken: token,
    });
  });
});
