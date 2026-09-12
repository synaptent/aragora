import React from 'react';

import { act, fireEvent, renderWithProviders, screen, waitFor } from '@/test-utils';

import SecurityAdminPage from '../page';
import { buildSecretsScanUrl } from '../secretsScan';

const mockFetch = jest.fn();

global.fetch = mockFetch as typeof fetch;

jest.mock('next/link', () => {
  return function MockLink({
    children,
    href,
    className,
  }: {
    children: React.ReactNode;
    href: string;
    className?: string;
  }) {
    return (
      <a href={href} className={className}>
        {children}
      </a>
    );
  };
});

jest.mock('@/components/MatrixRain', () => ({ Scanlines: () => null, CRTVignette: () => null }));

jest.mock('@/components/ThemeToggle', () => ({ ThemeToggle: () => <div>ThemeToggle</div> }));

jest.mock('@/components/BackendSelector', () => ({
  BackendSelector: () => <div>BackendSelector</div>,
  useBackend: () => ({ config: { api: 'http://backend.test' } }),
}));

function jsonResponse(data: unknown, ok = true, status = ok ? 200 : 500): Response {
  return {
    ok,
    status,
    headers: { get: () => 'application/json' },
    json: async () => data,
  } as Response;
}

function mockSecurityBootstrap() {
  return {
    status: {
      encryption_enabled: true,
      active_key_id: 'key_test_123',
      key_version: 1,
      key_created_at: '2026-04-01T00:00:00Z',
      key_rotation_due: false,
      algorithm: 'AES-256-GCM',
    },
    health: {
      status: 'healthy',
      encryption_service: { available: true, latency_ms: 12 },
      key_age_days: 7,
      rotation_recommended: false,
      compliance: { soc2_compliant: true, key_rotation_policy: '90 days' },
    },
    keys: { keys: [] },
  };
}

function installFetchMock(options?: { startResponse?: unknown; pollResponse?: unknown }) {
  const bootstrap = mockSecurityBootstrap();
  const startResponse = options?.startResponse ?? { scan_id: 'scan-123' };
  const pollResponse = options?.pollResponse ?? {
    scan_result: {
      scan_id: 'scan-123',
      repository: '/tmp/repo',
      status: 'completed',
      files_scanned: 42,
      scanned_history: false,
      secrets: [],
      summary: {
        total_secrets: 0,
        critical_count: 0,
        high_count: 0,
        medium_count: 0,
        low_count: 0,
      },
    },
  };

  mockFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);

    if (url === 'http://backend.test/api/v1/admin/security/status') {
      return Promise.resolve(jsonResponse(bootstrap.status));
    }

    if (url === 'http://backend.test/api/v1/admin/security/health') {
      return Promise.resolve(jsonResponse(bootstrap.health));
    }

    if (url === 'http://backend.test/api/v1/admin/security/keys') {
      return Promise.resolve(jsonResponse(bootstrap.keys));
    }

    if (url === buildSecretsScanUrl('http://backend.test') && init?.method === 'POST') {
      return Promise.resolve(jsonResponse(startResponse));
    }

    if (url === buildSecretsScanUrl('http://backend.test', 'scan-123')) {
      return Promise.resolve(jsonResponse(pollResponse));
    }

    throw new Error(`Unexpected fetch: ${url}`);
  });
}

describe('SecurityAdminPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.runOnlyPendingTimers();
    jest.useRealTimers();
  });

  it('builds secrets scan URLs with the required repo segment', () => {
    expect(buildSecretsScanUrl('http://backend.test')).toBe(
      'http://backend.test/api/v1/codebase/default/scan/secrets',
    );
    expect(buildSecretsScanUrl('http://backend.test', 'scan-123')).toBe(
      'http://backend.test/api/v1/codebase/default/scan/secrets/scan-123',
    );
  });

  it('starts and polls secrets scans through the codebase repo route', async () => {
    installFetchMock();

    renderWithProviders(<SecurityAdminPage />);

    const repoInput = await screen.findByPlaceholderText('/path/to/repository');
    fireEvent.change(repoInput, { target: { value: '/tmp/repo' } });
    fireEvent.click(screen.getByRole('button', { name: 'Scan for Secrets' }));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        buildSecretsScanUrl('http://backend.test'),
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            repo_path: '/tmp/repo',
            include_history: false,
            history_depth: 100,
          }),
        }),
      );
    });

    await act(async () => {
      jest.advanceTimersByTime(2000);
    });

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        buildSecretsScanUrl('http://backend.test', 'scan-123'),
        expect.objectContaining({
          headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
        }),
      );
    });

    expect(await screen.findByText('No secrets detected in repository')).toBeInTheDocument();

    const calledUrls = mockFetch.mock.calls.map(([input]) => String(input));
    expect(calledUrls).not.toContain('http://backend.test/api/v1/codebase/scan/secrets');
    expect(calledUrls).not.toContain('http://backend.test/api/v1/codebase/scan/secrets/scan-123');
  });

  it('shows an error when the secrets scan start response omits a scan id', async () => {
    installFetchMock({ startResponse: {} });

    renderWithProviders(<SecurityAdminPage />);

    const repoInput = await screen.findByPlaceholderText('/path/to/repository');
    fireEvent.change(repoInput, { target: { value: '/tmp/repo' } });
    fireEvent.click(screen.getByRole('button', { name: 'Scan for Secrets' }));

    expect(await screen.findByText('Secrets scan did not return a scan ID')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Scan for Secrets' })).toBeEnabled();
  });
});
