/**
 * Images built from `deploy/Dockerfile.frontend` without NEXT_PUBLIC_* build-args
 * inherit the Dockerfile's localhost ARG defaults, and Next.js inlines those into
 * the client bundle at build time. Once such a bundle is served from a real
 * hostname the baked values are unusable, so the resolvers in `config.ts` must
 * fall back to deriving from the serving host.
 *
 * These cases pin the serving hostname via the jsdom environment URL — jsdom's
 * `window.location` is non-configurable, so it cannot be stubbed per-test.
 *
 * @jest-environment-options {"url": "https://aragora.ai/"}
 */

const originalApiUrl = process.env.NEXT_PUBLIC_API_URL;
const originalWsUrl = process.env.NEXT_PUBLIC_WS_URL;
const originalControlPlaneUrl = process.env.NEXT_PUBLIC_CONTROL_PLANE_WS_URL;

/** Reproduce a bundle built with the Dockerfile's localhost ARG defaults. */
function bakeLocalhostDefaults(): void {
  process.env.NEXT_PUBLIC_API_URL = 'http://localhost:8080';
  process.env.NEXT_PUBLIC_WS_URL = 'ws://localhost:8765/ws';
}

describe('config resolution for a localhost-baked bundle served from a production host', () => {
  beforeEach(() => {
    jest.resetModules();
    delete process.env.NEXT_PUBLIC_API_URL;
    delete process.env.NEXT_PUBLIC_WS_URL;
    delete process.env.NEXT_PUBLIC_CONTROL_PLANE_WS_URL;
    jest.spyOn(console, 'warn').mockImplementation(() => {});
    jest.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  afterAll(() => {
    const restore: ReadonlyArray<readonly [string, string | undefined]> = [
      ['NEXT_PUBLIC_API_URL', originalApiUrl],
      ['NEXT_PUBLIC_WS_URL', originalWsUrl],
      ['NEXT_PUBLIC_CONTROL_PLANE_WS_URL', originalControlPlaneUrl],
    ];
    for (const [key, value] of restore) {
      if (value === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = value;
      }
    }
  });

  it('derives the WebSocket URL from the serving host instead of the baked localhost value', async () => {
    bakeLocalhostDefaults();

    const config = await import('../config');

    expect(config.WS_URL).toBe('wss://api.aragora.ai/ws');
  });

  it('already derives the API base URL from the serving host', async () => {
    bakeLocalhostDefaults();

    const config = await import('../config');

    expect(config.API_BASE_URL).toBe('https://api.aragora.ai');
  });

  it('derives the control-plane WebSocket URL from the serving host too', async () => {
    bakeLocalhostDefaults();
    process.env.NEXT_PUBLIC_CONTROL_PLANE_WS_URL =
      'ws://localhost:8766/api/control-plane/stream';

    const config = await import('../config');

    expect(config.CONTROL_PLANE_WS_URL).toBe(
      'wss://api.aragora.ai/api/control-plane/stream',
    );
  });

  it('carries the correction through URLs derived from WS_URL', async () => {
    bakeLocalhostDefaults();

    const config = await import('../config');

    expect(config.ORACLE_WS_URL).toBe('wss://api.aragora.ai/ws/oracle');
    expect(config.PROMPT_ENGINE_WS_URL).toBe('wss://api.aragora.ai/ws/prompt-engine');
  });

  it('honours an explicitly configured production WebSocket URL verbatim', async () => {
    process.env.NEXT_PUBLIC_API_URL = 'https://api.aragora.ai';
    process.env.NEXT_PUBLIC_WS_URL = 'wss://ws.aragora.ai/ws';

    const config = await import('../config');

    expect(config.WS_URL).toBe('wss://ws.aragora.ai/ws');
  });
});
