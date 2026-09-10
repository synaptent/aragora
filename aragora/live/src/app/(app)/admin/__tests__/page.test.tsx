import React from 'react';

import { renderWithProviders, screen, waitFor } from '@/test-utils';

import AdminOverviewPage from '../page';

const mockFetch = jest.fn();

global.fetch = mockFetch as typeof fetch;

jest.mock('next/link', () => {
  return function MockLink({ children, href }: { children: React.ReactNode; href: string }) {
    return <a href={href}>{children}</a>;
  };
});

jest.mock('@/components/admin/AdminLayout', () => ({
  AdminLayout: ({
    title,
    description,
    actions,
    children,
  }: {
    title: string;
    description: string;
    actions?: React.ReactNode;
    children: React.ReactNode;
  }) => (
    <div>
      <h1>{title}</h1>
      <p>{description}</p>
      {actions}
      {children}
    </div>
  ),
}));

jest.mock('@/components/admin/UsageChart', () => ({
  UsageChart: ({ title }: { title: string }) => <div>{title}</div>,
}));

jest.mock('@/components/BackendSelector', () => ({
  buildHealthCheckUrl: (api: string) => `${api}/api/health`,
  useBackend: () => ({ config: { api: 'http://backend.test' } }),
}));

jest.mock('@/hooks/useAragoraClient', () => ({
  useAragoraClient: () => ({ admin: { stats: jest.fn() } }),
}));

function jsonResponse(data: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    json: async () => data,
  } as Response;
}

function mockAdminFetch(healthData: unknown) {
  mockFetch.mockImplementation((input: RequestInfo | URL) => {
    const url = String(input);

    if (url === 'http://backend.test/api/health') {
      return Promise.resolve(jsonResponse(healthData));
    }

    if (url.includes('/api/v1/dashboard/activity')) {
      return Promise.resolve(jsonResponse({ activities: [] }));
    }

    if (url.includes('/api/analytics/debates/trends')) {
      return Promise.resolve(jsonResponse({ data_points: [] }));
    }

    if (url.includes('/api/analytics/usage/tokens')) {
      return Promise.resolve(jsonResponse({ data_points: [] }));
    }

    return Promise.resolve(jsonResponse({}));
  });
}

describe('AdminOverviewPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders flat health payloads without nested components', async () => {
    mockAdminFetch({
      status: 'healthy',
      uptime_seconds: 3600,
      version: '1.0.0',
      timestamp: '2026-03-31T12:00:00Z',
      agents_available: 4,
      agents_total: 6,
      websocket_connections: 12,
      database_status: 'healthy',
    });

    renderWithProviders(<AdminOverviewPage />);

    await waitFor(() => {
      expect(screen.getByText('4/6')).toBeInTheDocument();
    });

    expect(screen.getByText('12 conn')).toBeInTheDocument();
    expect(screen.getAllByText('HEALTHY').length).toBeGreaterThan(0);
  });

  it('renders placeholder component state when health details are absent', async () => {
    mockAdminFetch({
      status: 'healthy',
      uptime_seconds: 60,
      version: '1.0.0',
      timestamp: '2026-03-31T12:00:00Z',
    });

    renderWithProviders(<AdminOverviewPage />);

    await waitFor(() => {
      expect(screen.getByText('UNKNOWN')).toBeInTheDocument();
    });

    expect(screen.getByText('1m')).toBeInTheDocument();
    expect(screen.getByText('System Health')).toBeInTheDocument();
  });
});
