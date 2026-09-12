import { renderHook, act } from '@testing-library/react';
import { createHookWrapper } from '@/test-utils';
import { useBatchDebate } from '@/hooks/useBatchDebate';

// Provide an authenticated wrapper so useAuth() returns valid tokens
const hookWrapper = createHookWrapper({
  isAuthenticated: true,
  tokens: {
    access_token: 'test-token',
    refresh_token: 'test-refresh',
    token_type: 'bearer',
  } as never,
});

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Mock config
jest.mock('@/config', () => ({ API_BASE_URL: 'http://localhost:8080' }));

describe('useBatchDebate', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  describe('initial state', () => {
    it('starts with empty state', () => {
      const { result } = renderHook(() => useBatchDebate(), { wrapper: hookWrapper });

      expect(result.current.submitting).toBe(false);
      expect(result.current.submitError).toBeNull();
      expect(result.current.lastSubmittedBatchId).toBeNull();
      expect(result.current.currentBatch).toBeNull();
      expect(result.current.batches).toEqual([]);
      expect(result.current.queueStatus).toBeNull();
      expect(result.current.progress).toBe(0);
      expect(result.current.isComplete).toBe(false);
      expect(result.current.isFailed).toBe(false);
      expect(result.current.isProcessing).toBe(false);
    });
  });

  describe('submitBatch', () => {
    it('submits batch successfully', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          success: true,
          batch_id: 'batch-123',
          items_queued: 5,
          status_url: '/api/debates/batch/batch-123/status',
        }),
      });

      const { result } = renderHook(() => useBatchDebate(), { wrapper: hookWrapper });

      let response: unknown;
      await act(async () => {
        response = await result.current.submitBatch({
          items: [{ question: 'Is AI safe?' }, { question: 'What is consciousness?' }],
        });
      });

      expect(mockFetch).toHaveBeenCalledWith(
        'http://localhost:8080/api/debates/batch',
        expect.objectContaining({
          method: 'POST',
          headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
        }),
      );
      expect(response).toEqual({
        success: true,
        batch_id: 'batch-123',
        items_queued: 5,
        status_url: '/api/debates/batch/batch-123/status',
      });
      expect(result.current.lastSubmittedBatchId).toBe('batch-123');
      expect(result.current.submitting).toBe(false);
      expect(result.current.submitError).toBeNull();
    });

    it('handles submit error', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 400,
        json: async () => ({ error: 'Invalid batch format' }),
      });

      const { result } = renderHook(() => useBatchDebate(), { wrapper: hookWrapper });

      await act(async () => {
        await result.current.submitBatch({ items: [] });
      });

      expect(result.current.submitError).toBe('Invalid batch format');
      expect(result.current.submitting).toBe(false);
    });

    it('handles network error', async () => {
      mockFetch.mockRejectedValueOnce(new Error('Network error'));

      const { result } = renderHook(() => useBatchDebate(), { wrapper: hookWrapper });

      await act(async () => {
        await result.current.submitBatch({ items: [{ question: 'Test' }] });
      });

      expect(result.current.submitError).toBe('Network error');
    });

    it('shows submitting state during request', async () => {
      mockFetch.mockImplementationOnce(() => new Promise(() => {}));

      const { result } = renderHook(() => useBatchDebate(), { wrapper: hookWrapper });

      act(() => {
        result.current.submitBatch({ items: [{ question: 'Test' }] });
      });

      expect(result.current.submitting).toBe(true);
    });
  });

  describe('getBatchStatus', () => {
    it('fetches batch status successfully', async () => {
      const mockStatus = {
        batch_id: 'batch-123',
        status: 'processing',
        total_items: 5,
        completed_items: 2,
        failed_items: 0,
        items: [],
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:01:00Z',
      };

      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => mockStatus });

      const { result } = renderHook(() => useBatchDebate(), { wrapper: hookWrapper });

      await act(async () => {
        await result.current.getBatchStatus('batch-123');
      });

      expect(result.current.currentBatch).toEqual(mockStatus);
      expect(result.current.batchLoading).toBe(false);
      expect(result.current.progress).toBe(40); // 2/5 * 100
      expect(result.current.isProcessing).toBe(true);
    });

    it('handles 404 batch not found', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false, status: 404 });

      const { result } = renderHook(() => useBatchDebate(), { wrapper: hookWrapper });

      await act(async () => {
        await result.current.getBatchStatus('nonexistent');
      });

      expect(result.current.batchError).toBe('Batch not found');
      expect(result.current.currentBatch).toBeNull();
    });
  });

  describe('pollBatchStatus', () => {
    it('polls batch status at interval', async () => {
      const mockStatus = {
        batch_id: 'batch-123',
        status: 'processing',
        total_items: 5,
        completed_items: 2,
        failed_items: 0,
        items: [],
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:01:00Z',
      };

      mockFetch.mockResolvedValue({ ok: true, json: async () => mockStatus });

      const { result } = renderHook(() => useBatchDebate(), { wrapper: hookWrapper });

      await act(async () => {
        result.current.pollBatchStatus('batch-123', 1000);
      });

      // Initial fetch
      expect(mockFetch).toHaveBeenCalledTimes(1);

      // Advance timer for next poll
      await act(async () => {
        jest.advanceTimersByTime(1000);
      });

      expect(mockFetch).toHaveBeenCalledTimes(2);
    });

    it('stops polling when batch is completed', async () => {
      const completedStatus = {
        batch_id: 'batch-123',
        status: 'completed',
        total_items: 5,
        completed_items: 5,
        failed_items: 0,
        items: [],
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:02:00Z',
      };

      mockFetch.mockResolvedValue({ ok: true, json: async () => completedStatus });

      const { result } = renderHook(() => useBatchDebate(), { wrapper: hookWrapper });

      await act(async () => {
        result.current.pollBatchStatus('batch-123', 1000);
      });

      // Initial fetch happens immediately
      expect(mockFetch).toHaveBeenCalledTimes(1);

      // First interval tick - detects completion and should stop
      await act(async () => {
        jest.advanceTimersByTime(1000);
        await Promise.resolve();
      });

      const fetchCountAfterFirstTick = mockFetch.mock.calls.length;

      // Advance more time - no additional fetches should happen
      await act(async () => {
        jest.advanceTimersByTime(5000);
      });

      // Verify polling actually stopped (no more fetches after detecting completion)
      expect(mockFetch).toHaveBeenCalledTimes(fetchCountAfterFirstTick);
      expect(result.current.isComplete).toBe(true);
    });

    it('stopPolling clears interval', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: async () => ({
          batch_id: 'batch-123',
          status: 'processing',
          total_items: 5,
          completed_items: 2,
          failed_items: 0,
          items: [],
        }),
      });

      const { result } = renderHook(() => useBatchDebate(), { wrapper: hookWrapper });

      await act(async () => {
        result.current.pollBatchStatus('batch-123', 1000);
      });

      act(() => {
        result.current.stopPolling();
      });

      const fetchCountBefore = mockFetch.mock.calls.length;

      await act(async () => {
        jest.advanceTimersByTime(5000);
      });

      // Should not have made more requests
      expect(mockFetch).toHaveBeenCalledTimes(fetchCountBefore);
    });
  });

  describe('listBatches', () => {
    it('lists batches successfully', async () => {
      const mockBatches = [
        {
          batch_id: 'b1',
          status: 'completed',
          total_items: 5,
          completed_items: 5,
          failed_items: 0,
          created_at: '2024-01-01',
        },
        {
          batch_id: 'b2',
          status: 'processing',
          total_items: 3,
          completed_items: 1,
          failed_items: 0,
          created_at: '2024-01-02',
        },
      ];

      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ batches: mockBatches }) });

      const { result } = renderHook(() => useBatchDebate(), { wrapper: hookWrapper });

      await act(async () => {
        await result.current.listBatches();
      });

      expect(result.current.batches).toEqual(mockBatches);
      expect(result.current.batchesLoading).toBe(false);
    });

    it('supports status filter', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ batches: [] }) });

      const { result } = renderHook(() => useBatchDebate(), { wrapper: hookWrapper });

      await act(async () => {
        await result.current.listBatches(50, 'completed');
      });

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('status=completed'),
        expect.anything(),
      );
    });
  });

  describe('getQueueStatus', () => {
    it('fetches queue status', async () => {
      const mockQueueStatus = {
        active: true,
        max_concurrent: 3,
        active_count: 2,
        total_batches: 10,
        status_counts: { processing: 2, pending: 3, completed: 5 },
      };

      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => mockQueueStatus });

      const { result } = renderHook(() => useBatchDebate(), { wrapper: hookWrapper });

      await act(async () => {
        await result.current.getQueueStatus();
      });

      expect(result.current.queueStatus).toEqual(mockQueueStatus);
      expect(result.current.queueLoading).toBe(false);
    });
  });

  describe('clearBatch', () => {
    it('clears current batch and stops polling', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: async () => ({
          batch_id: 'batch-123',
          status: 'processing',
          total_items: 5,
          completed_items: 2,
          failed_items: 0,
          items: [],
        }),
      });

      const { result } = renderHook(() => useBatchDebate(), { wrapper: hookWrapper });

      await act(async () => {
        await result.current.getBatchStatus('batch-123');
      });

      expect(result.current.currentBatch).not.toBeNull();

      act(() => {
        result.current.clearBatch();
      });

      expect(result.current.currentBatch).toBeNull();
      expect(result.current.batchError).toBeNull();
    });
  });

  describe('clearSubmitError', () => {
    it('clears submit error', async () => {
      mockFetch.mockRejectedValueOnce(new Error('Test error'));

      const { result } = renderHook(() => useBatchDebate(), { wrapper: hookWrapper });

      await act(async () => {
        await result.current.submitBatch({ items: [] });
      });

      expect(result.current.submitError).not.toBeNull();

      act(() => {
        result.current.clearSubmitError();
      });

      expect(result.current.submitError).toBeNull();
    });
  });

  describe('cleanup', () => {
    it('clears polling on unmount', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: async () => ({
          batch_id: 'batch-123',
          status: 'processing',
          total_items: 5,
          completed_items: 2,
          failed_items: 0,
          items: [],
        }),
      });

      const { result, unmount } = renderHook(() => useBatchDebate(), { wrapper: hookWrapper });

      await act(async () => {
        result.current.pollBatchStatus('batch-123', 1000);
      });

      const fetchCountBefore = mockFetch.mock.calls.length;

      unmount();

      await act(async () => {
        jest.advanceTimersByTime(5000);
      });

      // Should not have made more requests after unmount
      expect(mockFetch).toHaveBeenCalledTimes(fetchCountBefore);
    });
  });
});
