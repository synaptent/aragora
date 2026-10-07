describe('config local dev API fallback', () => {
  const originalApiUrl = process.env.NEXT_PUBLIC_API_URL;
  const originalWsUrl = process.env.NEXT_PUBLIC_WS_URL;

  beforeEach(() => {
    jest.resetModules();
    delete process.env.NEXT_PUBLIC_API_URL;
    delete process.env.NEXT_PUBLIC_WS_URL;
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  afterAll(() => {
    if (originalApiUrl === undefined) {
      delete process.env.NEXT_PUBLIC_API_URL;
    } else {
      process.env.NEXT_PUBLIC_API_URL = originalApiUrl;
    }
    if (originalWsUrl === undefined) {
      delete process.env.NEXT_PUBLIC_WS_URL;
    } else {
      process.env.NEXT_PUBLIC_WS_URL = originalWsUrl;
    }
  });

  it('uses the same-origin API proxy on localhost when NEXT_PUBLIC_API_URL is unset', async () => {
    const warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {});

    const config = await import('../config');

    expect(config.API_BASE_URL).toBe('');
    expect(config.getEnvWarnings()).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          key: 'NEXT_PUBLIC_API_URL',
          message: 'API URL not set, using same-origin /api proxy',
        }),
      ]),
    );
    expect(warnSpy).toHaveBeenCalledWith(
      '[Aragora] NEXT_PUBLIC_API_URL not set, using same-origin /api proxy (local dev mode).'
    );
  });

  it('treats only local dev hosts as same-origin proxy candidates', async () => {
    const config = await import('../config');

    expect(config.isLocalDevHostname('localhost')).toBe(true);
    expect(config.isLocalDevHostname('127.0.0.1')).toBe(true);
    expect(config.isLocalDevHostname('192.168.1.24')).toBe(true);
    expect(config.isLocalDevHostname('preview.example.test')).toBe(false);
  });
});

describe('config apiFetch runtime backend selection', () => {
  const originalApiUrl = process.env.NEXT_PUBLIC_API_URL;
  const originalWsUrl = process.env.NEXT_PUBLIC_WS_URL;
  const mockFetch = jest.fn();

  beforeEach(() => {
    jest.resetModules();
    delete process.env.NEXT_PUBLIC_API_URL;
    delete process.env.NEXT_PUBLIC_WS_URL;
    localStorage.clear();
    mockFetch.mockReset();
    global.fetch = mockFetch as typeof fetch;
    jest.spyOn(console, 'warn').mockImplementation(() => {});
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  afterAll(() => {
    if (originalApiUrl === undefined) {
      delete process.env.NEXT_PUBLIC_API_URL;
    } else {
      process.env.NEXT_PUBLIC_API_URL = originalApiUrl;
    }
    if (originalWsUrl === undefined) {
      delete process.env.NEXT_PUBLIC_WS_URL;
    } else {
      process.env.NEXT_PUBLIC_WS_URL = originalWsUrl;
    }
  });

  it('uses the saved runtime backend for helper requests', async () => {
    localStorage.setItem('aragora-backend', 'production');
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ jobs: [] }),
    });

    const config = await import('../config');
    await config.apiFetch('/api/scheduler/jobs');

    expect(mockFetch).toHaveBeenCalledWith(
      'https://api.aragora.ai/api/scheduler/jobs',
      expect.objectContaining({
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
        }),
      }),
    );
  });

  it('keeps absolute helper endpoints intact', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    });

    const config = await import('../config');
    await config.apiFetch('https://custom.example/api/health');

    expect(mockFetch).toHaveBeenCalledWith(
      'https://custom.example/api/health',
      expect.any(Object),
    );
  });
});

describe('config local dev is unaffected by the localhost-baked fallback', () => {
  // jsdom serves these from http://localhost/, matching a developer running the
  // container locally: the baked localhost values are correct there and must be
  // honoured verbatim rather than rewritten to an api.<host> derivation.
  const originalApiUrl = process.env.NEXT_PUBLIC_API_URL;
  const originalWsUrl = process.env.NEXT_PUBLIC_WS_URL;

  beforeEach(() => {
    jest.resetModules();
    jest.spyOn(console, 'warn').mockImplementation(() => {});
    process.env.NEXT_PUBLIC_API_URL = 'http://localhost:8080';
    process.env.NEXT_PUBLIC_WS_URL = 'ws://localhost:8765/ws';
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  afterAll(() => {
    if (originalApiUrl === undefined) {
      delete process.env.NEXT_PUBLIC_API_URL;
    } else {
      process.env.NEXT_PUBLIC_API_URL = originalApiUrl;
    }
    if (originalWsUrl === undefined) {
      delete process.env.NEXT_PUBLIC_WS_URL;
    } else {
      process.env.NEXT_PUBLIC_WS_URL = originalWsUrl;
    }
  });

  it('keeps the baked localhost endpoints when served from localhost', async () => {
    const config = await import('../config');

    expect(config.API_BASE_URL).toBe('http://localhost:8080');
    expect(config.WS_URL).toBe('ws://localhost:8765/ws');
  });
});
