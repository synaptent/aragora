import { renderHook, act, waitFor } from '@testing-library/react';
import { createHookWrapper } from '@/test-utils';
import { useFeatures } from '@/hooks/useFeatures';

// Provide an authenticated wrapper so useAuth() returns valid tokens
const hookWrapper = createHookWrapper({
  isAuthenticated: true,
  tokens: {
    access_token: 'test-token',
    refresh_token: 'test-refresh',
    token_type: 'bearer',
  } as never,
});

// Mock fetch globally
const mockFetch = jest.fn();
global.fetch = mockFetch;

const mockFeaturesResponse = {
  available: ['pulse', 'evidence', 'gauntlet'],
  unavailable: ['matrix', 'broadcast'],
  features: {
    pulse: {
      name: 'pulse',
      description: 'Trending topics detection',
      available: true,
      endpoints: ['/api/pulse'],
      category: 'discovery',
    },
    evidence: {
      name: 'evidence',
      description: 'Evidence collection',
      available: true,
      endpoints: ['/api/evidence'],
      category: 'analysis',
    },
    gauntlet: {
      name: 'gauntlet',
      description: 'Security testing',
      available: true,
      category: 'security',
    },
    matrix: {
      name: 'matrix',
      description: 'Matrix debates',
      available: false,
      install_hint: 'Enable MATRIX_DEBATES feature flag',
      category: 'debates',
    },
    broadcast: {
      name: 'broadcast',
      description: 'Audio/video broadcast',
      available: false,
      install_hint: 'Install ffmpeg',
      category: 'media',
    },
  },
};

describe('useFeatures', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('initial state', () => {
    it('starts with loading true', () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(mockFeaturesResponse),
      });

      const { result } = renderHook(() => useFeatures('http://localhost:8000'), {
        wrapper: hookWrapper,
      });

      expect(result.current.loading).toBe(true);
      expect(result.current.features).toBeNull();
      expect(result.current.error).toBeNull();
    });
  });

  describe('successful fetch', () => {
    it('fetches features on mount', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(mockFeaturesResponse),
      });

      const { result } = renderHook(() => useFeatures('http://localhost:8000'), {
        wrapper: hookWrapper,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(mockFetch).toHaveBeenCalledWith(
        'http://localhost:8000/api/features',
        expect.objectContaining({
          method: 'GET',
          headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
        }),
      );
      expect(result.current.features).toEqual(mockFeaturesResponse);
      expect(result.current.error).toBeNull();
    });

    it('only fetches once on mount', async () => {
      mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(mockFeaturesResponse) });

      const { result, rerender } = renderHook(() => useFeatures('http://localhost:8000'), {
        wrapper: hookWrapper,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      // Rerender should not trigger another fetch
      rerender();

      expect(mockFetch).toHaveBeenCalledTimes(1);
    });
  });

  describe('error handling', () => {
    it('handles HTTP errors', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false, status: 500 });

      const { result } = renderHook(() => useFeatures('http://localhost:8000'), {
        wrapper: hookWrapper,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.error).toBe('Failed to fetch features: 500');
      expect(result.current.features).toBeNull();
    });

    it('handles network errors', async () => {
      mockFetch.mockRejectedValueOnce(new Error('Network error'));

      const { result } = renderHook(() => useFeatures('http://localhost:8000'), {
        wrapper: hookWrapper,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.error).toBe('Network error');
      expect(result.current.features).toBeNull();
    });
  });

  describe('isAvailable', () => {
    it('returns true for available features', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(mockFeaturesResponse),
      });

      const { result } = renderHook(() => useFeatures('http://localhost:8000'), {
        wrapper: hookWrapper,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.isAvailable('pulse')).toBe(true);
      expect(result.current.isAvailable('evidence')).toBe(true);
      expect(result.current.isAvailable('gauntlet')).toBe(true);
    });

    it('returns false for unavailable features', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(mockFeaturesResponse),
      });

      const { result } = renderHook(() => useFeatures('http://localhost:8000'), {
        wrapper: hookWrapper,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.isAvailable('matrix')).toBe(false);
      expect(result.current.isAvailable('broadcast')).toBe(false);
    });

    it('returns false during loading', () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(mockFeaturesResponse),
      });

      const { result } = renderHook(() => useFeatures('http://localhost:8000'), {
        wrapper: hookWrapper,
      });

      // While loading, features are not yet known
      expect(result.current.loading).toBe(true);
      expect(result.current.isAvailable('any-feature')).toBe(false);
    });
  });

  describe('getFeatureInfo', () => {
    it('returns feature info for existing feature', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(mockFeaturesResponse),
      });

      const { result } = renderHook(() => useFeatures('http://localhost:8000'), {
        wrapper: hookWrapper,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      const pulseInfo = result.current.getFeatureInfo('pulse');
      expect(pulseInfo).toEqual(mockFeaturesResponse.features.pulse);
    });

    it('returns undefined for non-existent feature', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(mockFeaturesResponse),
      });

      const { result } = renderHook(() => useFeatures('http://localhost:8000'), {
        wrapper: hookWrapper,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.getFeatureInfo('nonexistent')).toBeUndefined();
    });
  });

  describe('getAvailableFeatures', () => {
    it('returns list of available feature IDs', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(mockFeaturesResponse),
      });

      const { result } = renderHook(() => useFeatures('http://localhost:8000'), {
        wrapper: hookWrapper,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.getAvailableFeatures()).toEqual(['pulse', 'evidence', 'gauntlet']);
    });

    it('returns empty array when features not loaded', () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(mockFeaturesResponse),
      });

      const { result } = renderHook(() => useFeatures('http://localhost:8000'), {
        wrapper: hookWrapper,
      });

      // Before load completes
      expect(result.current.getAvailableFeatures()).toEqual([]);
    });
  });

  describe('getUnavailableFeatures', () => {
    it('returns list of unavailable feature IDs', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(mockFeaturesResponse),
      });

      const { result } = renderHook(() => useFeatures('http://localhost:8000'), {
        wrapper: hookWrapper,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.getUnavailableFeatures()).toEqual(['matrix', 'broadcast']);
    });
  });

  describe('refetch', () => {
    it('refetches features when called', async () => {
      mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(mockFeaturesResponse) });

      const { result } = renderHook(() => useFeatures('http://localhost:8000'), {
        wrapper: hookWrapper,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(mockFetch).toHaveBeenCalledTimes(1);

      // Call refetch
      await act(async () => {
        await result.current.refetch();
      });

      expect(mockFetch).toHaveBeenCalledTimes(2);
    });

    it('updates state on refetch', async () => {
      const updatedResponse = {
        ...mockFeaturesResponse,
        available: ['pulse', 'evidence', 'gauntlet', 'matrix'],
      };

      mockFetch
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockFeaturesResponse) })
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(updatedResponse) });

      const { result } = renderHook(() => useFeatures('http://localhost:8000'), {
        wrapper: hookWrapper,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.isAvailable('matrix')).toBe(false);

      await act(async () => {
        await result.current.refetch();
      });

      expect(result.current.isAvailable('matrix')).toBe(true);
    });

    it('handles refetch errors', async () => {
      mockFetch
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockFeaturesResponse) })
        .mockRejectedValueOnce(new Error('Refetch failed'));

      const { result } = renderHook(() => useFeatures('http://localhost:8000'), {
        wrapper: hookWrapper,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      await act(async () => {
        await result.current.refetch();
      });

      expect(result.current.error).toBe('Refetch failed');
    });
  });
});
