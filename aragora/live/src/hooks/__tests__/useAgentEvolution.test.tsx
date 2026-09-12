import { renderHook } from '@testing-library/react';

import {
  useAgentEvolutionDashboard,
  usePendingChanges,
  type PendingChangesData,
} from '@/hooks/useAgentEvolution';

const mockMutate = jest.fn();
const mockPost = jest.fn();

jest.mock('@/hooks/useSWRFetch', () => ({
  useSWRFetch: jest.fn(() => ({
    data: null,
    error: null,
    isLoading: false,
    isValidating: false,
    mutate: mockMutate,
  })),
  invalidateCache: jest.fn(),
}));

jest.mock('@/hooks/useApi', () => ({ useApi: () => ({ post: mockPost, get: jest.fn() }) }));

import { useSWRFetch } from '@/hooks/useSWRFetch';

const mockUseSWRFetch = useSWRFetch as jest.Mock;

describe('usePendingChanges', () => {
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

  it('fails closed to an empty pending fallback when no backend data is available', () => {
    const { result } = renderHook(() => usePendingChanges());

    expect(result.current.pending).toBeNull();
    expect(result.current.pendingFallback).toEqual({ changes: [], total_pending: 0 });
  });

  it('unwraps live pending data when the backend responds', () => {
    const livePending: PendingChangesData = {
      changes: [
        {
          id: 'pc-live-1',
          agent_name: 'claude-3-opus',
          change_type: 'prompt_rewrite',
          nomic_cycle_id: 'nomic-101',
          proposed_at: '2026-04-07T10:00:00Z',
          proposed_by: 'nomic-loop',
          description: 'Tighten synthesis prompt',
          diff_summary: 'Prompt v5 -> v6',
          old_content: 'before',
          new_content: 'after',
          impact_estimate: 'Expected +2% clarity',
          status: 'pending',
        },
      ],
      total_pending: 1,
    };

    mockUseSWRFetch.mockReturnValue({
      data: { data: livePending },
      error: null,
      isLoading: false,
      isValidating: false,
      mutate: mockMutate,
    });

    const { result } = renderHook(() => usePendingChanges());

    expect(result.current.pending).toEqual(livePending);
  });
});

describe('useAgentEvolutionDashboard', () => {
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

  it('does not invent pending proposals when the pending endpoint is empty or unavailable', () => {
    const { result } = renderHook(() => useAgentEvolutionDashboard());

    expect(result.current.pending.total_pending).toBe(0);
    expect(result.current.pending.changes).toEqual([]);
  });
});
