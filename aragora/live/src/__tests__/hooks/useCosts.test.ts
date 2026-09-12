/**
 * Tests for useCosts hooks
 */

import { renderHook } from '@testing-library/react';
import {
  useCostSummary,
  useCostsBreakdown,
  useCostTimeline,
  useCostAlerts,
  useCostRecommendations,
  useCostEfficiency,
  useCostForecast,
  useSpendTrend,
  useAgentCostBreakdown,
  useModelCostBreakdown,
  useDebateCostBreakdown,
  useBudgetUtilization,
  useCosts,
} from '@/hooks/useCosts';

// Mock useSWRFetch
const mockMutate = jest.fn();
const defaultReturn = () => ({
  data: null,
  error: null,
  isLoading: false,
  isValidating: false,
  mutate: mockMutate,
});

jest.mock('@/hooks/useSWRFetch', () => ({
  useSWRFetch: jest.fn(() => defaultReturn()),
  invalidateCache: jest.fn(),
}));

// Mock useApi
const mockPost = jest.fn();
jest.mock('@/hooks/useApi', () => ({ useApi: () => ({ post: mockPost, get: jest.fn() }) }));

import { useSWRFetch, invalidateCache } from '@/hooks/useSWRFetch';

const mockUseSWRFetch = useSWRFetch as jest.Mock;

beforeEach(() => {
  jest.clearAllMocks();
  mockUseSWRFetch.mockReset();
  mockUseSWRFetch.mockImplementation(() => ({
    data: null,
    error: null,
    isLoading: false,
    isValidating: false,
    mutate: mockMutate,
  }));
});

describe('useCostSummary', () => {
  it('returns null summary when no data', () => {
    const { result } = renderHook(() => useCostSummary());
    expect(result.current.summary).toBeNull();
  });

  it('fetches with default 30d time range', () => {
    renderHook(() => useCostSummary());
    expect(mockUseSWRFetch).toHaveBeenCalledWith(
      '/api/v1/costs?range=30d',
      expect.objectContaining({ refreshInterval: 60000 }),
    );
  });

  it('fetches with custom time range', () => {
    renderHook(() => useCostSummary('7d'));
    expect(mockUseSWRFetch).toHaveBeenCalledWith('/api/v1/costs?range=7d', expect.anything());
  });

  it('unwraps data envelope', () => {
    const mockSummary = {
      total_cost_usd: 150.0,
      budget_usd: 500.0,
      tokens_in: 10000,
      tokens_out: 5000,
      api_calls: 200,
      period_start: '2026-02-01',
      period_end: '2026-02-24',
    };
    mockUseSWRFetch.mockReturnValue({
      data: { data: mockSummary },
      error: null,
      isLoading: false,
      mutate: mockMutate,
    });

    const { result } = renderHook(() => useCostSummary());
    expect(result.current.summary).toEqual(mockSummary);
  });
});

describe('useCostsBreakdown', () => {
  it('returns null breakdown when no data', () => {
    const { result } = renderHook(() => useCostsBreakdown());
    expect(result.current.breakdown).toBeNull();
  });

  it('fetches from breakdown endpoint', () => {
    renderHook(() => useCostsBreakdown('24h'));
    expect(mockUseSWRFetch).toHaveBeenCalledWith(
      '/api/v1/costs/breakdown?range=24h',
      expect.anything(),
    );
  });

  it('unwraps data envelope', () => {
    const mockBreakdown = {
      by_provider: [{ name: 'openai', cost: 42, percentage: 70 }],
      by_feature: [{ name: 'debate', cost: 18, percentage: 30 }],
    };
    mockUseSWRFetch.mockReturnValue({
      data: { data: mockBreakdown },
      error: null,
      isLoading: false,
      mutate: mockMutate,
    });

    const { result } = renderHook(() => useCostsBreakdown());
    expect(result.current.breakdown).toEqual(mockBreakdown);
  });
});

describe('useCostTimeline', () => {
  it('returns null timeline when no data', () => {
    const { result } = renderHook(() => useCostTimeline());
    expect(result.current.timeline).toBeNull();
  });

  it('fetches from timeline endpoint', () => {
    renderHook(() => useCostTimeline('90d'));
    expect(mockUseSWRFetch).toHaveBeenCalledWith(
      '/api/v1/costs/timeline?range=90d',
      expect.anything(),
    );
  });
});

describe('useCostAlerts', () => {
  it('returns empty alerts array when no data', () => {
    const { result } = renderHook(() => useCostAlerts());
    expect(result.current.alerts).toEqual([]);
  });

  it('refreshes alerts more frequently (30s)', () => {
    renderHook(() => useCostAlerts());
    expect(mockUseSWRFetch).toHaveBeenCalledWith(
      '/api/v1/costs/alerts',
      expect.objectContaining({ refreshInterval: 30000 }),
    );
  });

  it('unwraps nested alerts array', () => {
    const alerts = [
      {
        id: 'alert-1',
        type: 'budget_warning',
        message: '80% of budget used',
        severity: 'warning',
        timestamp: '2026-02-24T12:00:00Z',
      },
    ];
    mockUseSWRFetch.mockReturnValue({
      data: { data: { alerts } },
      error: null,
      isLoading: false,
      mutate: mockMutate,
    });

    const { result } = renderHook(() => useCostAlerts());
    expect(result.current.alerts).toHaveLength(1);
    expect(result.current.alerts[0].type).toBe('budget_warning');
  });
});

describe('useCostRecommendations', () => {
  it('returns empty recommendations when no data', () => {
    const { result } = renderHook(() => useCostRecommendations());
    expect(result.current.recommendations).toEqual([]);
  });

  it('refreshes every 5 minutes', () => {
    renderHook(() => useCostRecommendations());
    expect(mockUseSWRFetch).toHaveBeenCalledWith(
      '/api/v1/costs/recommendations',
      expect.objectContaining({ refreshInterval: 300000 }),
    );
  });
});

describe('useCostEfficiency', () => {
  it('returns null efficiency when no data', () => {
    const { result } = renderHook(() => useCostEfficiency());
    expect(result.current.efficiency).toBeNull();
  });

  it('fetches with time range', () => {
    renderHook(() => useCostEfficiency('7d'));
    expect(mockUseSWRFetch).toHaveBeenCalledWith(
      '/api/v1/costs/efficiency?range=7d',
      expect.anything(),
    );
  });
});

describe('useCostForecast', () => {
  it('returns null forecast when no data', () => {
    const { result } = renderHook(() => useCostForecast());
    expect(result.current.forecast).toBeNull();
  });

  it('fetches from forecast endpoint', () => {
    renderHook(() => useCostForecast());
    expect(mockUseSWRFetch).toHaveBeenCalledWith(
      '/api/v1/costs/forecast',
      expect.objectContaining({ refreshInterval: 300000 }),
    );
  });
});

describe('useSpendTrend', () => {
  it('returns null trend when no data', () => {
    const { result } = renderHook(() => useSpendTrend());
    expect(result.current.trend).toBeNull();
  });

  it('fetches analytics trend endpoint', () => {
    renderHook(() => useSpendTrend('7d'));
    expect(mockUseSWRFetch).toHaveBeenCalledWith(
      '/api/v1/costs/analytics/trend?period=7d',
      expect.anything(),
    );
  });
});

describe('useAgentCostBreakdown', () => {
  it('returns null agent breakdown when no data', () => {
    const { result } = renderHook(() => useAgentCostBreakdown());
    expect(result.current.agentBreakdown).toBeNull();
  });

  it('fetches by-agent analytics endpoint', () => {
    renderHook(() => useAgentCostBreakdown());
    expect(mockUseSWRFetch).toHaveBeenCalledWith(
      '/api/v1/costs/analytics/by-agent',
      expect.anything(),
    );
  });
});

describe('useModelCostBreakdown', () => {
  it('returns null model breakdown when no data', () => {
    const { result } = renderHook(() => useModelCostBreakdown());
    expect(result.current.modelBreakdown).toBeNull();
  });
});

describe('useDebateCostBreakdown', () => {
  it('returns null debate breakdown when no data', () => {
    const { result } = renderHook(() => useDebateCostBreakdown());
    expect(result.current.debateBreakdown).toBeNull();
  });

  it('passes limit parameter', () => {
    renderHook(() => useDebateCostBreakdown(10));
    expect(mockUseSWRFetch).toHaveBeenCalledWith(
      '/api/v1/costs/analytics/by-debate?limit=10',
      expect.anything(),
    );
  });
});

describe('useBudgetUtilization', () => {
  it('returns null utilization when no data', () => {
    const { result } = renderHook(() => useBudgetUtilization());
    expect(result.current.utilization).toBeNull();
  });

  it('checks frequently (30s)', () => {
    renderHook(() => useBudgetUtilization());
    expect(mockUseSWRFetch).toHaveBeenCalledWith(
      '/api/v1/costs/analytics/budget-utilization',
      expect.objectContaining({ refreshInterval: 30000 }),
    );
  });
});

describe('useCosts (unified)', () => {
  it('returns null costData when no summary', () => {
    const { result } = renderHook(() => useCosts());
    expect(result.current.costData).toBeNull();
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it('combines loading state from all sub-hooks', () => {
    // First call (summary) returns loading
    let callCount = 0;
    mockUseSWRFetch.mockImplementation(() => {
      callCount++;
      return {
        data: null,
        error: null,
        isLoading: callCount === 1, // Only first sub-hook loading
        mutate: mockMutate,
      };
    });

    const { result } = renderHook(() => useCosts());
    expect(result.current.isLoading).toBe(true);
  });

  it('provides refresh function that invalidates all cost caches', () => {
    const { result } = renderHook(() => useCosts());
    result.current.refresh();
    expect(invalidateCache).toHaveBeenCalledWith('/api/v1/costs');
    expect(invalidateCache).toHaveBeenCalledWith('/api/v1/costs/breakdown');
    expect(invalidateCache).toHaveBeenCalledWith('/api/v1/costs/timeline');
    expect(invalidateCache).toHaveBeenCalledWith('/api/v1/costs/alerts');
  });

  it('returns empty alerts array as default', () => {
    const { result } = renderHook(() => useCosts());
    expect(result.current.alerts).toEqual([]);
  });

  it('provides action functions', () => {
    const { result } = renderHook(() => useCosts());
    expect(typeof result.current.setBudget).toBe('function');
    expect(typeof result.current.dismissAlert).toBe('function');
    expect(typeof result.current.applyRecommendation).toBe('function');
    expect(typeof result.current.dismissRecommendation).toBe('function');
  });
});
