import { renderHook, act, waitFor } from '@testing-library/react';
import { useEvidence, EvidenceData } from '@/hooks/useEvidence';

// Mock fetch globally
const mockFetch = jest.fn();
global.fetch = mockFetch;

const mockEvidenceData: EvidenceData = {
  debate_id: 'debate-123',
  task: 'Is AI beneficial?',
  has_evidence: true,
  grounded_verdict: { grounding_score: 0.85, verdict: 'Supported', confidence: 0.9 },
  claims: [
    {
      claim_text: 'AI increases productivity',
      confidence: 0.9,
      grounding_score: 0.88,
      citations: [
        {
          id: 'cit-1',
          citation_type: 'academic',
          title: 'AI Productivity Study',
          url: 'https://example.com/study',
          excerpt: 'Studies show AI increases productivity by 40%',
          relevance_score: 0.95,
          quality: 'authoritative',
        },
      ],
    },
  ],
  citations: [
    {
      id: 'cit-1',
      citation_type: 'academic',
      title: 'AI Productivity Study',
      url: 'https://example.com/study',
      excerpt: 'Studies show AI increases productivity by 40%',
      relevance_score: 0.95,
      quality: 'authoritative',
    },
  ],
  related_evidence: [
    {
      id: 'rel-1',
      content: 'Related evidence content',
      source: 'knowledge-base',
      importance: 0.8,
      tier: 'high',
    },
  ],
  evidence_count: 5,
};

describe('useEvidence', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('initial state', () => {
    it('starts with loading true and no evidence', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockEvidenceData) });

      const { result } = renderHook(() => useEvidence('debate-123'));

      // Initially loading
      expect(result.current.loading).toBe(true);
      expect(result.current.evidence).toBeNull();
      expect(result.current.error).toBeNull();

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });
    });

    it('has correct initial derived values', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockEvidenceData) });

      const { result } = renderHook(() => useEvidence('debate-123'));

      // Before data loads
      expect(result.current.hasEvidence).toBe(false);
      expect(result.current.groundingScore).toBe(0);
      expect(result.current.claimsCount).toBe(0);
      expect(result.current.citationsCount).toBe(0);

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });
    });
  });

  describe('successful fetch', () => {
    it('fetches evidence data on mount', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockEvidenceData) });

      const { result } = renderHook(() => useEvidence('debate-123'));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/debates/debate-123/evidence'),
      );
      expect(result.current.evidence).toEqual(mockEvidenceData);
      expect(result.current.error).toBeNull();
    });

    it('sets derived values correctly', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockEvidenceData) });

      const { result } = renderHook(() => useEvidence('debate-123'));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.hasEvidence).toBe(true);
      expect(result.current.groundingScore).toBe(0.85);
      expect(result.current.claimsCount).toBe(1);
      expect(result.current.citationsCount).toBe(1);
    });
  });

  describe('error handling', () => {
    it('handles 404 response', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false, status: 404 });

      const { result } = renderHook(() => useEvidence('nonexistent-id'));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.error).toBe('Debate not found');
      expect(result.current.evidence).toBeNull();
    });

    it('handles other HTTP errors', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false, status: 500 });

      const { result } = renderHook(() => useEvidence('debate-123'));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.error).toBe('HTTP 500');
      expect(result.current.evidence).toBeNull();
    });

    it('handles network errors', async () => {
      mockFetch.mockRejectedValueOnce(new Error('Network error'));

      const { result } = renderHook(() => useEvidence('debate-123'));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.error).toBe('Network error');
      expect(result.current.evidence).toBeNull();
    });
  });

  describe('empty debateId', () => {
    it('does not fetch when debateId is empty', async () => {
      const { result } = renderHook(() => useEvidence(''));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(mockFetch).not.toHaveBeenCalled();
      expect(result.current.evidence).toBeNull();
      expect(result.current.error).toBeNull();
    });
  });

  describe('refetch', () => {
    it('provides refetch function', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockEvidenceData) });

      const { result } = renderHook(() => useEvidence('debate-123'));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(typeof result.current.refetch).toBe('function');
    });

    it('refetch updates data', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockEvidenceData) });

      const { result } = renderHook(() => useEvidence('debate-123'));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      // Update mock for refetch
      const updatedData = { ...mockEvidenceData, evidence_count: 10 };
      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(updatedData) });

      await act(async () => {
        await result.current.refetch();
      });

      expect(result.current.evidence?.evidence_count).toBe(10);
    });
  });

  describe('debateId changes', () => {
    it('refetches when debateId changes', async () => {
      mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(mockEvidenceData) });

      const { result, rerender } = renderHook(({ id }) => useEvidence(id), {
        initialProps: { id: 'debate-1' },
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(mockFetch).toHaveBeenCalledTimes(1);
      expect(mockFetch).toHaveBeenLastCalledWith(
        expect.stringContaining('/api/debates/debate-1/evidence'),
      );

      // Change debateId
      rerender({ id: 'debate-2' });

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledTimes(2);
      });

      expect(mockFetch).toHaveBeenLastCalledWith(
        expect.stringContaining('/api/debates/debate-2/evidence'),
      );
    });
  });

  describe('evidence without grounded_verdict', () => {
    it('handles null grounded_verdict', async () => {
      const dataWithoutVerdict: EvidenceData = { ...mockEvidenceData, grounded_verdict: null };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(dataWithoutVerdict),
      });

      const { result } = renderHook(() => useEvidence('debate-123'));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.groundingScore).toBe(0);
    });
  });
});
