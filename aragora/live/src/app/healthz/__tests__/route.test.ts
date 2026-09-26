/** @jest-environment node */

import packageInfo from '../../../../package.json';
import { dynamic, GET } from '../route';
import { logger } from '@/lib/logger';

jest.mock('@/lib/logger', () => ({ logger: { info: jest.fn() } }));

describe('GET /healthz/', () => {
  const { version } = packageInfo;
  const originalBuildSha = process.env.NEXT_PUBLIC_BUILD_SHA;
  const originalApiUrl = process.env.NEXT_PUBLIC_API_URL;

  afterEach(() => {
    if (originalBuildSha === undefined) delete process.env.NEXT_PUBLIC_BUILD_SHA;
    else process.env.NEXT_PUBLIC_BUILD_SHA = originalBuildSha;
    if (originalApiUrl === undefined) delete process.env.NEXT_PUBLIC_API_URL;
    else process.env.NEXT_PUBLIC_API_URL = originalApiUrl;
  });

  it('returns compact JSON with the package version and no-store caching', async () => {
    const response = GET();
    const body = await response.text();

    expect(response.status).toBe(200);
    expect(response.headers.get('content-type')).toContain('application/json');
    expect(response.headers.get('cache-control')).toBe('no-store');
    expect(JSON.parse(body)).toMatchObject({ status: 'ok', app: 'aragora-live', version });
    expect(body).toBe(JSON.stringify(JSON.parse(body)));
    expect(body).toContain('"app":"aragora-live"');
  });

  it('includes the configured build commit', async () => {
    process.env.NEXT_PUBLIC_BUILD_SHA = 'healthz-test-sha';

    expect(await GET().json()).toMatchObject({ commit: 'healthz-test-sha' });
  });

  it.each([undefined, ''])('uses unknown for an absent build commit (%s)', async (sha) => {
    if (sha === undefined) delete process.env.NEXT_PUBLIC_BUILD_SHA;
    else process.env.NEXT_PUBLIC_BUILD_SHA = sha;

    expect(await GET().json()).toMatchObject({ commit: 'unknown' });
  });

  it('does not fetch the backend even when its URL is unreachable', async () => {
    process.env.NEXT_PUBLIC_API_URL = 'http://127.0.0.1:9';

    expect(await GET().json()).toMatchObject({ status: 'ok', app: 'aragora-live', version });
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('opts into static generation for export builds', () => {
    expect(dynamic).toBe('force-static');
  });

  it('logs exactly one structured request record without request secrets', () => {
    jest.mocked(logger.info).mockClear();
    GET();
    expect(logger.info).toHaveBeenCalledTimes(1);
    expect(logger.info).toHaveBeenCalledWith({ req: { url: '/healthz/' } }, 'request');
  });
});
