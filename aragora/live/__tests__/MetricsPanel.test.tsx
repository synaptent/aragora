/**
 * Tests for MetricsPanel component
 */

import { renderWithProviders, screen, fireEvent, waitFor, act } from '@/test-utils';
import { MetricsPanel } from '../src/components/MetricsPanel';

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

const mockMetricsData = {
  uptime_seconds: 86400,
  uptime_human: '1 day, 0:00:00',
  requests: {
    total: 15000,
    errors: 150,
    error_rate: 0.01,
    top_endpoints: [
      { endpoint: '/api/debate', count: 5000 },
      { endpoint: '/api/leaderboard', count: 3000 },
    ],
  },
  cache: { entries: 256 },
  databases: {
    'debates.db': { bytes: 1048576, human: '1.0 MB' },
    'rankings.db': { bytes: 524288, human: '512 KB' },
  },
  timestamp: '2026-01-05T12:00:00Z',
};

const mockHealthData = {
  status: 'healthy' as const,
  checks: {
    database: { status: 'healthy', path: '/data/debates.db' },
    memory: { status: 'healthy' },
    disk: { status: 'healthy' },
  },
};

const mockCacheData = {
  total_entries: 256,
  max_entries: 1000,
  hit_rate: 0.85,
  hits: 850,
  misses: 150,
  entries_by_prefix: { debate_: 100, agent_: 80, ranking_: 76 },
  oldest_entry_age_seconds: 3600,
  newest_entry_age_seconds: 10,
};

const mockSystemData = {
  python_version: '3.11.11',
  platform: 'Darwin',
  machine: 'arm64',
  processor: 'arm',
  pid: 12345,
  memory: { rss_mb: 256, vms_mb: 512 },
};

function setupSuccessfulFetch() {
  mockFetch.mockImplementation((url: string) => {
    if (url.includes('/api/metrics/health')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockHealthData) });
    }
    if (url.includes('/api/metrics/cache')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockCacheData) });
    }
    if (url.includes('/api/metrics/system')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockSystemData) });
    }
    if (url.includes('/api/metrics')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockMetricsData) });
    }
    return Promise.resolve({ ok: false });
  });
}

describe('MetricsPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders summary metrics after load', async () => {
    setupSuccessfulFetch();
    renderWithProviders(<MetricsPanel apiBase="http://localhost:8080" />);

    await waitFor(() => {
      expect(screen.getByText('1 day, 0:00:00')).toBeInTheDocument();
    });

    expect(screen.getByText('15,000')).toBeInTheDocument();
    expect(screen.getByText('1.00%')).toBeInTheDocument();
    expect(screen.getByText('85.0% hit')).toBeInTheDocument();
    expect(screen.getByText('HEALTHY')).toBeInTheDocument();
  });

  it('shows loading copy for the overview tab when pending', () => {
    mockFetch.mockImplementation(() => new Promise(() => {}));
    renderWithProviders(<MetricsPanel apiBase="http://localhost:8080" />);

    expect(screen.getByText('Server Metrics')).toBeInTheDocument();
    expect(screen.getByText('Loading metrics...')).toBeInTheDocument();
  });

  it('switches tabs and shows tab-specific content', async () => {
    setupSuccessfulFetch();
    renderWithProviders(<MetricsPanel apiBase="http://localhost:8080" />);

    await waitFor(() => {
      expect(screen.getByText('1 day, 0:00:00')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'HEALTH' }));
    expect(screen.getByText(/overall status/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'CACHE' }));
    expect(screen.getByText(/hit rate/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'SYSTEM' }));
    expect(screen.getByText(/python/i)).toBeInTheDocument();
  });

  it('shows partial error when some endpoints fail', async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/api/metrics/health')) {
        return Promise.resolve({ ok: false });
      }
      if (url.includes('/api/metrics/cache')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockCacheData) });
      }
      if (url.includes('/api/metrics/system')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockSystemData) });
      }
      if (url.includes('/api/metrics')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockMetricsData) });
      }
      return Promise.resolve({ ok: false });
    });

    renderWithProviders(<MetricsPanel apiBase="http://localhost:8080" />);

    await waitFor(() => {
      expect(screen.getByText(/some metrics failed to load/i)).toBeInTheDocument();
    });

    expect(screen.getByText('1 day, 0:00:00')).toBeInTheDocument();
  });

  it('collapses the panel and shows the compact summary', async () => {
    setupSuccessfulFetch();
    renderWithProviders(<MetricsPanel apiBase="http://localhost:8080" />);

    await waitFor(() => {
      expect(screen.getByText('1 day, 0:00:00')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: /\[-\]/ }));

    expect(screen.queryByRole('button', { name: 'OVERVIEW' })).not.toBeInTheDocument();
    expect(screen.getByText(/uptime:/i, { selector: 'p span' })).toBeInTheDocument();
  });

  it('refreshes data when the refresh button is clicked', async () => {
    setupSuccessfulFetch();
    renderWithProviders(<MetricsPanel apiBase="http://localhost:8080" />);

    await waitFor(() => {
      expect(screen.getByText('1 day, 0:00:00')).toBeInTheDocument();
    });

    const initialCalls = mockFetch.mock.calls.length;
    fireEvent.click(screen.getByRole('button', { name: /\[refresh\]/i }));

    await waitFor(() => {
      expect(mockFetch.mock.calls.length).toBeGreaterThan(initialCalls);
    });
  });

  it('auto-refreshes every 30 seconds', async () => {
    jest.useFakeTimers();
    setupSuccessfulFetch();

    renderWithProviders(<MetricsPanel apiBase="http://localhost:8080" />);

    await act(async () => {
      await Promise.resolve();
    });

    const initialCalls = mockFetch.mock.calls.length;

    await act(async () => {
      jest.advanceTimersByTime(30000);
    });

    await waitFor(() => {
      expect(mockFetch.mock.calls.length).toBeGreaterThan(initialCalls);
    });

    jest.useRealTimers();
  });
});
