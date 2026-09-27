/**
 * A bundle built with a production NEXT_PUBLIC_API_URL but a localhost
 * NEXT_PUBLIC_WS_URL makes `_isProductionBuild` true regardless of serving host.
 * The localhost-rescue in resolveWsUrl must not fire for such a bundle when the
 * browser is itself on localhost — a localhost WebSocket endpoint is correct
 * there, and rewriting it would produce `wss://api.localhost/ws`.
 *
 * jsdom's default environment URL (http://localhost/) is the serving host here.
 */

const originalApiUrl = process.env.NEXT_PUBLIC_API_URL;
const originalWsUrl = process.env.NEXT_PUBLIC_WS_URL;

describe('config resolution for a mixed-origin bake served from localhost', () => {
  beforeEach(() => {
    jest.resetModules();
    jest.spyOn(console, 'warn').mockImplementation(() => {});
    jest.spyOn(console, 'error').mockImplementation(() => {});
    process.env.NEXT_PUBLIC_API_URL = 'https://api.aragora.ai';
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

  it('honours the baked localhost WebSocket endpoint when the browser is on localhost', async () => {
    const config = await import('../config');

    expect(config.WS_URL).toBe('ws://localhost:8765/ws');
  });

  it('never derives an api.localhost endpoint', async () => {
    const config = await import('../config');

    expect(config.WS_URL).not.toContain('api.localhost');
  });
});
