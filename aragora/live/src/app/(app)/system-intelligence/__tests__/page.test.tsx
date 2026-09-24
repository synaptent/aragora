import React from 'react';
import { render, screen } from '@testing-library/react';

import SystemIntelligencePage from '../page';

const mockUseSWRFetch = jest.fn();
const mockAddGoal = jest.fn();

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

jest.mock('@/components/MatrixRain', () => ({ Scanlines: () => null, CRTVignette: () => null }));

jest.mock('@/components/AsciiBanner', () => ({
  AsciiBannerCompact: () => <div data-testid="ascii-banner" />,
}));

jest.mock('@/components/ThemeToggle', () => ({
  ThemeToggle: () => <div data-testid="theme-toggle" />,
}));

jest.mock('@/components/BackendSelector', () => ({
  BackendSelector: () => <div data-testid="backend-selector" />,
}));

jest.mock('@/components/PanelErrorBoundary', () => ({
  PanelErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

jest.mock('@/hooks/useSystemIntelligence', () => ({
  useSystemIntelligence: () => ({
    overview: {
      totalCycles: 12,
      successRate: 0.75,
      activeAgents: 4,
      knowledgeItems: 128,
      topAgents: [{ id: 'claude', elo: 1700, wins: 12 }],
      recentImprovements: [],
    },
    isLoading: false,
  }),
  useAgentPerformance: () => ({
    agents: [
      {
        id: 'claude',
        name: 'claude',
        elo: 1700,
        eloHistory: [
          { date: '2026-03-24T00:00:00Z', elo: 1680 },
          { date: '2026-03-25T00:00:00Z', elo: 1700 },
        ],
        calibration: 0.83,
        winRate: 0.67,
        domains: ['security', 'architecture'],
      },
    ],
    isLoading: false,
  }),
  useInstitutionalMemory: () => ({
    memory: {
      totalInjections: 18,
      retrievalCount: 9,
      topPatterns: [{ pattern: 'Use receipts', frequency: 5, confidence: 0.9 }],
      confidenceChanges: [{ topic: 'receipts', before: 0.7, after: 0.9 }],
    },
    isLoading: false,
  }),
  useImprovementQueue: () => ({
    items: [
      {
        id: 'imp-1',
        goal: 'Reduce latency',
        priority: 90,
        source: 'debate',
        status: 'pending',
        createdAt: '2026-03-25T00:00:00Z',
      },
    ],
    isLoading: false,
    addGoal: mockAddGoal,
  }),
}));

jest.mock('@/hooks/useSystemHealth', () => ({
  useSystemHealth: () => ({
    health: {
      overall_status: 'healthy',
      subsystems: {},
      circuit_breakers: { available: true, breakers: [], total: 0 },
      slos: { available: true, overall_healthy: true },
      agents: { available: true, agents: [], total: 2, active: 1 },
      budget: { available: true, utilization: 0.42, forecast: { eom: 1000, trend: 'stable' } },
      last_check: '2026-03-25T00:00:00Z',
      collection_time_ms: 18,
    },
    isLoading: false,
  }),
  useAgentPoolHealth: () => ({
    agents: [{ agent_id: 'claude', type: 'anthropic-api', status: 'active' }],
    total: 2,
    active: 1,
    available: true,
  }),
}));

jest.mock('@/hooks/useSWRFetch', () => ({
  useSWRFetch: (...args: unknown[]) => mockUseSWRFetch(...args),
}));

describe('SystemIntelligencePage', () => {
  beforeEach(() => {
    jest.clearAllMocks();

    mockUseSWRFetch.mockImplementation((endpoint: string) => {
      if (endpoint === '/api/v1/autonomous/monitoring/anomalies?hours=24') {
        return {
          data: {
            anomalies: [
              {
                id: 'an-1',
                severity: 'critical',
                metric_name: 'latency',
                description: 'Latency spike detected',
                timestamp: '2026-03-25T00:00:00Z',
              },
            ],
          },
          error: null,
          isLoading: false,
        };
      }

      if (endpoint === '/api/history/events?limit=30') {
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

      if (endpoint === '/api/v1/knowledge/mound/dashboard/health') {
        return {
          data: {
            success: true,
            data: {
              status: 'healthy',
              checks: { adapters: true },
              timestamp: '2026-03-25T00:00:00Z',
            },
          },
          error: null,
          isLoading: false,
        };
      }

      if (endpoint === '/api/v1/knowledge/mound/dashboard/adapters') {
        return {
          data: {
            success: true,
            data: {
              total: 4,
              enabled: 3,
              last_sync: '2026-03-25T00:00:00Z',
              adapters: [
                { name: 'continuum', enabled: true },
                { name: 'consensus', enabled: true },
                { name: 'receipt', enabled: true },
                { name: 'ranking', enabled: false },
              ],
            },
          },
          error: null,
          isLoading: false,
        };
      }

      if (endpoint === '/api/v1/nomic/state') {
        return {
          data: { state: 'running', cycle: 12, phase: 'verify' },
          error: null,
          isLoading: false,
        };
      }

      if (endpoint === '/api/control-plane/queue/metrics') {
        return {
          data: { pending: 2, running: 1, completed_today: 5, avg_execution_time_ms: 4500 },
          error: null,
          isLoading: false,
        };
      }

      return { data: null, error: null, isLoading: false };
    });
  });

  it('uses live backend routes for overview data and renders normalized results', () => {
    render(<SystemIntelligencePage />);

    const endpoints = mockUseSWRFetch.mock.calls.map(([endpoint]) => endpoint);

    expect(endpoints).toEqual(
      expect.arrayContaining([
        '/api/v1/autonomous/monitoring/anomalies?hours=24',
        '/api/history/events?limit=30',
        '/api/v1/knowledge/mound/dashboard/health',
        '/api/v1/knowledge/mound/dashboard/adapters',
        '/api/v1/nomic/state',
        '/api/control-plane/queue/metrics',
      ]),
    );

    expect(endpoints).not.toContain('/api/v1/system-intelligence/anomalies');
    expect(endpoints).not.toContain('/api/v1/system-intelligence/events?limit=30');
    expect(endpoints).not.toContain('/api/v1/system-intelligence/km-sync');
    expect(endpoints).not.toContain('/api/v1/system-intelligence/nomic-status');
    expect(endpoints).not.toContain('/api/v1/system-intelligence/debate-queue');

    expect(screen.getByText('Latency spike detected')).toBeInTheDocument();
    expect(screen.getByText('Debate completed successfully')).toBeInTheDocument();
    expect(screen.getByText('Verification')).toBeInTheDocument();
    expect(screen.getByText('3/4')).toBeInTheDocument();
    expect(screen.getByText('4.5s')).toBeInTheDocument();
  });
});
