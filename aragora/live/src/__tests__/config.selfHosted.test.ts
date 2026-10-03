/**
 * A self-hosted deployment serves the same image from its own domain. Resolution
 * must derive from that domain, never from a vendor-pinned constant — otherwise a
 * self-hoster's browser would send API and WebSocket traffic to Aragora's own
 * production backend.
 *
 * This is also why `deploy/Dockerfile.frontend` must not default its
 * NEXT_PUBLIC_* ARGs to production URLs: a baked `https://api.aragora.ai` is
 * indistinguishable from a deliberate choice and would be honoured verbatim here.
 *
 * @jest-environment-options {"url": "https://aragora.acme.com/"}
 */

const originalApiUrl = process.env.NEXT_PUBLIC_API_URL;
const originalWsUrl = process.env.NEXT_PUBLIC_WS_URL;

describe('config resolution for a self-hosted deployment on its own domain', () => {
  beforeEach(() => {
    jest.resetModules();
    jest.spyOn(console, 'warn').mockImplementation(() => {});
    jest.spyOn(console, 'error').mockImplementation(() => {});
    // The Dockerfile's localhost ARG defaults, as inlined by Next.js.
    process.env.NEXT_PUBLIC_API_URL = 'http://localhost:8080';
    process.env.NEXT_PUBLIC_WS_URL = 'ws://localhost:8765/ws';
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  afterAll(() => {
    const restore: ReadonlyArray<readonly [string, string | undefined]> = [
      ['NEXT_PUBLIC_API_URL', originalApiUrl],
      ['NEXT_PUBLIC_WS_URL', originalWsUrl],
    ];
    for (const [key, value] of restore) {
      if (value === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = value;
      }
    }
  });

  it('derives both endpoints from the self-hosted domain', async () => {
    const config = await import('../config');

    expect(config.API_BASE_URL).toBe('https://api.aragora.acme.com');
    expect(config.WS_URL).toBe('wss://api.aragora.acme.com/ws');
  });

  it('does not route the self-hosted deployment to the vendor backend', async () => {
    const config = await import('../config');

    expect(config.API_BASE_URL).not.toContain('aragora.ai');
    expect(config.WS_URL).not.toContain('aragora.ai');
  });
});
