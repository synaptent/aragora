import { renderHook, act } from '@testing-library/react';
import { useDebateFork, ForkNode } from '@/hooks/useDebateFork';

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Mock config
jest.mock('@/config', () => ({ API_BASE_URL: 'http://localhost:8080' }));

describe('useDebateFork', () => {
  const debateId = 'debate-123';

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('initial state', () => {
    it('starts with empty state', () => {
      const { result } = renderHook(() => useDebateFork(debateId));

      expect(result.current.forks).toEqual([]);
      expect(result.current.forkTree).toBeNull();
      expect(result.current.loading).toBe(false);
      expect(result.current.error).toBeNull();
      expect(result.current.forkResult).toBeNull();
      expect(result.current.forking).toBe(false);
      expect(result.current.forkError).toBeNull();
      expect(result.current.selectedNodes).toEqual([null, null]);
    });

    it('has correct computed values initially', () => {
      const { result } = renderHook(() => useDebateFork(debateId));

      expect(result.current.hasForks).toBe(false);
      expect(result.current.hasSelection).toBe(false);
      expect(result.current.canCompare).toBe(false);
      expect(result.current.comparisonData).toBeNull();
    });
  });

  describe('loadForks', () => {
    it('loads forks successfully', async () => {
      const mockForks = [
        {
          branch_id: 'fork-1',
          parent_debate_id: debateId,
          branch_point: 3,
          pivot_claim: 'What if we assumed the opposite?',
          status: 'completed',
          messages_inherited: 3,
          created_at: Date.now(),
        },
        {
          branch_id: 'fork-2',
          parent_debate_id: debateId,
          branch_point: 5,
          status: 'active',
          messages_inherited: 5,
        },
      ];

      const mockTree = {
        id: debateId,
        type: 'root' as const,
        branch_point: 0,
        children: [
          { id: 'fork-1', type: 'fork' as const, branch_point: 3, children: [] },
          { id: 'fork-2', type: 'fork' as const, branch_point: 5, children: [] },
        ],
        total_nodes: 3,
        max_depth: 1,
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ forks: mockForks, tree: mockTree }),
      });

      const { result } = renderHook(() => useDebateFork(debateId));

      await act(async () => {
        await result.current.loadForks();
      });

      expect(mockFetch).toHaveBeenCalledWith(`http://localhost:8080/api/debates/${debateId}/forks`);
      expect(result.current.forks).toEqual(mockForks);
      expect(result.current.forkTree).toEqual(mockTree);
      expect(result.current.loading).toBe(false);
      expect(result.current.hasForks).toBe(true);
    });

    it('handles 404 gracefully (no forks yet)', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false, status: 404 });

      const { result } = renderHook(() => useDebateFork(debateId));

      await act(async () => {
        await result.current.loadForks();
      });

      expect(result.current.forks).toEqual([]);
      expect(result.current.forkTree).toBeNull();
      expect(result.current.error).toBeNull();
    });

    it('handles error response', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: async () => ({ error: 'Internal server error' }),
      });

      const { result } = renderHook(() => useDebateFork(debateId));

      await act(async () => {
        await result.current.loadForks();
      });

      expect(result.current.error).toBe('Internal server error');
    });

    it('handles network error', async () => {
      mockFetch.mockRejectedValueOnce(new Error('Network error'));

      const { result } = renderHook(() => useDebateFork(debateId));

      await act(async () => {
        await result.current.loadForks();
      });

      expect(result.current.error).toBe('Network error');
    });

    it('does nothing if debateId is empty', async () => {
      const { result } = renderHook(() => useDebateFork(''));

      await act(async () => {
        await result.current.loadForks();
      });

      expect(mockFetch).not.toHaveBeenCalled();
    });

    it('shows loading state during request', async () => {
      mockFetch.mockImplementationOnce(() => new Promise(() => {}));

      const { result } = renderHook(() => useDebateFork(debateId));

      act(() => {
        result.current.loadForks();
      });

      expect(result.current.loading).toBe(true);
    });
  });

  describe('createFork', () => {
    it('creates fork successfully', async () => {
      const mockForkResult = {
        success: true,
        branch_id: 'fork-new',
        parent_debate_id: debateId,
        branch_point: 3,
        messages_inherited: 3,
        modified_context: 'What if we assumed the opposite?',
        status: 'created',
        message: 'Fork created successfully',
      };

      mockFetch
        .mockResolvedValueOnce({ ok: true, json: async () => mockForkResult })
        // loadForks is called after createFork
        .mockResolvedValueOnce({ ok: true, json: async () => ({ forks: [], tree: null }) });

      const { result } = renderHook(() => useDebateFork(debateId));

      let forkResult: unknown;
      await act(async () => {
        forkResult = await result.current.createFork(3, 'What if we assumed the opposite?');
      });

      expect(mockFetch).toHaveBeenCalledWith(
        `http://localhost:8080/api/debates/${debateId}/fork`,
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            branch_point: 3,
            modified_context: 'What if we assumed the opposite?',
          }),
        }),
      );
      expect(forkResult).toEqual(mockForkResult);
      expect(result.current.forkResult).toEqual(mockForkResult);
      expect(result.current.forking).toBe(false);
    });

    it('handles error response', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 400,
        json: async () => ({ error: 'Invalid branch point' }),
      });

      const { result } = renderHook(() => useDebateFork(debateId));

      const forkResult = await act(async () => {
        return await result.current.createFork(999);
      });

      expect(result.current.forkError).toBe('Invalid branch point');
      expect(forkResult).toBeNull();
    });

    it('does nothing if debateId is empty', async () => {
      const { result } = renderHook(() => useDebateFork(''));

      const forkResult = await act(async () => {
        return await result.current.createFork(3);
      });

      expect(mockFetch).not.toHaveBeenCalled();
      expect(forkResult).toBeNull();
    });

    it('shows forking state during request', async () => {
      mockFetch.mockImplementationOnce(() => new Promise(() => {}));

      const { result } = renderHook(() => useDebateFork(debateId));

      act(() => {
        result.current.createFork(3);
      });

      expect(result.current.forking).toBe(true);
    });
  });

  describe('selectForComparison', () => {
    const mockNode1: ForkNode = {
      id: 'fork-1',
      type: 'fork',
      branch_point: 3,
      pivot_claim: 'Claim A',
      status: 'completed',
      messages_inherited: 3,
      children: [],
    };

    const mockNode2: ForkNode = {
      id: 'fork-2',
      type: 'fork',
      branch_point: 5,
      pivot_claim: 'Claim B',
      status: 'active',
      messages_inherited: 5,
      children: [],
    };

    it('selects node in slot 0', () => {
      const { result } = renderHook(() => useDebateFork(debateId));

      act(() => {
        result.current.selectForComparison(mockNode1, 0);
      });

      expect(result.current.selectedNodes[0]).toEqual(mockNode1);
      expect(result.current.selectedNodes[1]).toBeNull();
      expect(result.current.hasSelection).toBe(true);
      expect(result.current.canCompare).toBe(false);
    });

    it('selects node in slot 1', () => {
      const { result } = renderHook(() => useDebateFork(debateId));

      act(() => {
        result.current.selectForComparison(mockNode2, 1);
      });

      expect(result.current.selectedNodes[0]).toBeNull();
      expect(result.current.selectedNodes[1]).toEqual(mockNode2);
      expect(result.current.hasSelection).toBe(true);
      expect(result.current.canCompare).toBe(false);
    });

    it('selects both nodes for comparison', () => {
      const { result } = renderHook(() => useDebateFork(debateId));

      act(() => {
        result.current.selectForComparison(mockNode1, 0);
        result.current.selectForComparison(mockNode2, 1);
      });

      expect(result.current.selectedNodes[0]).toEqual(mockNode1);
      expect(result.current.selectedNodes[1]).toEqual(mockNode2);
      expect(result.current.hasSelection).toBe(true);
      expect(result.current.canCompare).toBe(true);
    });

    it('replaces existing selection in slot', () => {
      const { result } = renderHook(() => useDebateFork(debateId));

      act(() => {
        result.current.selectForComparison(mockNode1, 0);
      });

      act(() => {
        result.current.selectForComparison(mockNode2, 0);
      });

      expect(result.current.selectedNodes[0]).toEqual(mockNode2);
    });
  });

  describe('clearSelection', () => {
    it('clears both selected nodes', () => {
      const mockNode: ForkNode = { id: 'fork-1', type: 'fork', branch_point: 3, children: [] };

      const { result } = renderHook(() => useDebateFork(debateId));

      act(() => {
        result.current.selectForComparison(mockNode, 0);
        result.current.selectForComparison(mockNode, 1);
      });

      expect(result.current.hasSelection).toBe(true);

      act(() => {
        result.current.clearSelection();
      });

      expect(result.current.selectedNodes).toEqual([null, null]);
      expect(result.current.hasSelection).toBe(false);
      expect(result.current.canCompare).toBe(false);
    });
  });

  describe('comparisonData', () => {
    const mockNode1: ForkNode = {
      id: 'fork-1',
      type: 'fork',
      branch_point: 3,
      pivot_claim: 'Claim A',
      status: 'completed',
      messages_inherited: 3,
      children: [],
    };

    const mockNode2: ForkNode = {
      id: 'fork-2',
      type: 'fork',
      branch_point: 5,
      pivot_claim: 'Claim B',
      status: 'active',
      messages_inherited: 5,
      children: [],
    };

    it('returns null when no nodes selected', () => {
      const { result } = renderHook(() => useDebateFork(debateId));

      expect(result.current.comparisonData).toBeNull();
    });

    it('returns null when only one node selected', () => {
      const { result } = renderHook(() => useDebateFork(debateId));

      act(() => {
        result.current.selectForComparison(mockNode1, 0);
      });

      expect(result.current.comparisonData).toBeNull();
    });

    it('calculates comparison data when both nodes selected', () => {
      const { result } = renderHook(() => useDebateFork(debateId));

      act(() => {
        result.current.selectForComparison(mockNode1, 0);
        result.current.selectForComparison(mockNode2, 1);
      });

      const comparison = result.current.comparisonData;
      expect(comparison).not.toBeNull();
      expect(comparison!.leftFork).toEqual(mockNode1);
      expect(comparison!.rightFork).toEqual(mockNode2);
      expect(comparison!.divergencePoint).toBe(3); // min of 3 and 5
      expect(comparison!.sharedMessages).toBe(3);
    });

    it('includes outcome differences', () => {
      const { result } = renderHook(() => useDebateFork(debateId));

      act(() => {
        result.current.selectForComparison(mockNode1, 0);
        result.current.selectForComparison(mockNode2, 1);
      });

      const comparison = result.current.comparisonData;
      expect(comparison!.outcomeDiff).toContainEqual({
        field: 'status',
        left: 'completed',
        right: 'active',
      });
      expect(comparison!.outcomeDiff).toContainEqual({
        field: 'pivot_claim',
        left: 'Claim A',
        right: 'Claim B',
      });
      expect(comparison!.outcomeDiff).toContainEqual({
        field: 'messages_inherited',
        left: 3,
        right: 5,
      });
    });

    it('empty outcomeDiff when nodes are identical', () => {
      const identicalNode: ForkNode = {
        id: 'fork-same',
        type: 'fork',
        branch_point: 3,
        pivot_claim: 'Same claim',
        status: 'completed',
        messages_inherited: 3,
        children: [],
      };

      const { result } = renderHook(() => useDebateFork(debateId));

      act(() => {
        result.current.selectForComparison(identicalNode, 0);
        result.current.selectForComparison(identicalNode, 1);
      });

      const comparison = result.current.comparisonData;
      expect(comparison!.outcomeDiff).toEqual([]);
    });
  });

  describe('clearError', () => {
    it('clears both error types', async () => {
      mockFetch.mockRejectedValue(new Error('Test error'));

      const { result } = renderHook(() => useDebateFork(debateId));

      await act(async () => {
        await result.current.loadForks();
        await result.current.createFork(3);
      });

      expect(result.current.error).not.toBeNull();
      expect(result.current.forkError).not.toBeNull();

      act(() => {
        result.current.clearError();
      });

      expect(result.current.error).toBeNull();
      expect(result.current.forkError).toBeNull();
    });
  });

  describe('clearForkResult', () => {
    it('clears fork result', async () => {
      mockFetch
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({
            success: true,
            branch_id: 'fork-new',
            parent_debate_id: debateId,
            branch_point: 3,
            messages_inherited: 3,
            status: 'created',
            message: 'Fork created',
          }),
        })
        .mockResolvedValueOnce({ ok: true, json: async () => ({ forks: [], tree: null }) });

      const { result } = renderHook(() => useDebateFork(debateId));

      await act(async () => {
        await result.current.createFork(3);
      });

      expect(result.current.forkResult).not.toBeNull();

      act(() => {
        result.current.clearForkResult();
      });

      expect(result.current.forkResult).toBeNull();
    });
  });
});
