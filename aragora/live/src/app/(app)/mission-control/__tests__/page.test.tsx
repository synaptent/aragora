import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import MissionControlPage from '../page';

const mockPush = jest.fn();
const mockShowToast = jest.fn();
const mockUseSWRFetch = jest.fn();
const mockUseSystemHealth = jest.fn();
const mockUseCircuitBreakers = jest.fn();
const mockUseAgentPoolHealth = jest.fn();
const mockUseBudgetStatus = jest.fn();
const mockUseAuth = jest.fn();
const mockFetch = jest.fn();

jest.mock('next/navigation', () => ({ useRouter: () => ({ push: mockPush }) }));

jest.mock('@/components/BackendSelector', () => ({
  useBackend: () => ({ config: { api: 'http://backend.test' } }),
}));

jest.mock('@/context/ToastContext', () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));

jest.mock('@/context/AuthContext', () => ({ useAuth: () => mockUseAuth() }));

jest.mock('@/hooks/useSystemHealth', () => ({
  useSystemHealth: () => mockUseSystemHealth(),
  useCircuitBreakers: () => mockUseCircuitBreakers(),
  useAgentPoolHealth: () => mockUseAgentPoolHealth(),
  useBudgetStatus: () => mockUseBudgetStatus(),
}));

jest.mock('@/hooks/useSWRFetch', () => ({
  useSWRFetch: (...args: unknown[]) => mockUseSWRFetch(...args),
}));

jest.mock('@/components/MatrixRain', () => ({
  Scanlines: () => <div data-testid="scanlines" />,
  CRTVignette: () => <div data-testid="crt-vignette" />,
}));

describe('MissionControlPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    global.fetch = mockFetch as typeof global.fetch;

    mockUseAuth.mockReturnValue({ tokens: { access_token: 'token-123' } });

    mockUseSystemHealth.mockReturnValue({
      health: {
        overall_status: 'healthy',
        subsystems: {},
        last_check: '2026-03-25T00:00:00Z',
        collection_time_ms: 18,
      },
    });
    mockUseCircuitBreakers.mockReturnValue({ breakers: [] });
    mockUseAgentPoolHealth.mockReturnValue({ agents: [], total: 4, active: 3 });
    mockUseBudgetStatus.mockReturnValue({
      budget: { utilization: 0.42, forecast: { eom: 321, trend: 'stable' } },
    });

    mockUseSWRFetch.mockImplementation((endpoint: string) => {
      if (endpoint === '/api/debates?status=running&limit=10') {
        return {
          data: {
            data: {
              debates: [
                {
                  id: 'deb-1',
                  task: 'Test debate',
                  status: 'running',
                  agents: 3,
                  round: 1,
                  total_rounds: 3,
                  created_at: '2026-03-25T00:00:00Z',
                },
              ],
            },
          },
          error: null,
          isLoading: false,
        };
      }
      if (endpoint === '/api/control-plane/queue/metrics') {
        return {
          data: { pending: 2, running: 1, completed_today: 5, failed_today: 1 },
          error: null,
          isLoading: false,
        };
      }
      if (endpoint === '/api/history/events?limit=10') {
        return {
          data: {
            events: [
              {
                id: 'evt-1',
                event_type: 'debate_completed',
                agent: 'codex',
                timestamp: '2026-03-25T00:00:00Z',
                event_data: { message: 'Debate completed successfully' },
              },
            ],
          },
          error: null,
          isLoading: false,
        };
      }
      return { data: null, error: null, isLoading: false };
    });

    mockFetch.mockResolvedValue({ ok: true, json: async () => ({}) });
  });

  it('reads queue metrics and history events from current endpoints', () => {
    render(<MissionControlPage />);

    expect(mockUseSWRFetch).toHaveBeenCalledWith(
      '/api/control-plane/queue/metrics',
      expect.objectContaining({ refreshInterval: 10000 }),
    );
    expect(mockUseSWRFetch).toHaveBeenCalledWith(
      '/api/history/events?limit=10',
      expect.objectContaining({ refreshInterval: 15000 }),
    );
    expect(screen.getByText('Debate completed successfully')).toBeInTheDocument();
    expect(screen.getByText('codex')).toBeInTheDocument();
  });

  it('routes setup-heavy quick actions to the correct workflow pages', async () => {
    const user = userEvent.setup();
    render(<MissionControlPage />);

    await user.click(screen.getByRole('button', { name: /\[START DEBATE\]/i }));
    await user.click(screen.getByRole('button', { name: /\[RUN GAUNTLET\]/i }));
    await user.click(screen.getByRole('button', { name: /\[SELF-IMPROVE SCAN\]/i }));

    expect(mockPush).toHaveBeenNthCalledWith(1, '/arena');
    expect(mockPush).toHaveBeenNthCalledWith(2, '/gauntlet');
    expect(mockPush).toHaveBeenNthCalledWith(3, '/self-improve');
  });

  it('resets breakers through the admin nomic endpoint with auth', async () => {
    const user = userEvent.setup();
    jest.spyOn(window, 'confirm').mockReturnValue(true);

    render(<MissionControlPage />);

    await user.click(screen.getByRole('button', { name: /\[RESET BREAKERS\]/i }));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        'http://backend.test/api/v1/admin/nomic/circuit-breakers/reset',
        expect.objectContaining({
          method: 'POST',
          headers: expect.objectContaining({
            Authorization: 'Bearer token-123',
            'Content-Type': 'application/json',
          }),
        }),
      );
    });
    expect(mockShowToast).toHaveBeenCalledWith(
      'Circuit breaker reset initiated successfully',
      'success',
    );
  });
});
