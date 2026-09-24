import { renderHook, act, waitFor } from '@testing-library/react';
import { useBroadcast } from '@/hooks/useBroadcast';

// Mock fetch globally
const mockFetch = jest.fn();
global.fetch = mockFetch;

describe('useBroadcast', () => {
  const debateId = 'debate-123';

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('initial state', () => {
    it('starts with correct initial values', () => {
      const { result } = renderHook(() => useBroadcast(debateId));

      expect(result.current.hasAudio).toBe(false);
      expect(result.current.hasVideo).toBe(false);
      expect(result.current.audioUrl).toBeNull();
      expect(result.current.videoUrl).toBeNull();
      expect(result.current.isGenerating).toBe(false);
      expect(result.current.error).toBeNull();
      expect(result.current.stepsCompleted).toEqual([]);
    });

    it('provides all expected functions', () => {
      const { result } = renderHook(() => useBroadcast(debateId));

      expect(typeof result.current.checkAudioExists).toBe('function');
      expect(typeof result.current.generateBroadcast).toBe('function');
      expect(typeof result.current.runFullPipeline).toBe('function');
      expect(typeof result.current.publishToTwitter).toBe('function');
      expect(typeof result.current.publishToYouTube).toBe('function');
    });
  });

  describe('checkAudioExists', () => {
    it('sets hasAudio true when audio exists', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true });

      const { result } = renderHook(() => useBroadcast(debateId));

      let exists: boolean;
      await act(async () => {
        exists = await result.current.checkAudioExists();
      });

      expect(exists!).toBe(true);
      expect(result.current.hasAudio).toBe(true);
      expect(result.current.audioUrl).toContain(debateId);
      expect(mockFetch).toHaveBeenCalledWith(expect.stringContaining(`/audio/${debateId}.mp3`), {
        method: 'HEAD',
      });
    });

    it('returns false when audio does not exist', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false });

      const { result } = renderHook(() => useBroadcast(debateId));

      let exists: boolean;
      await act(async () => {
        exists = await result.current.checkAudioExists();
      });

      expect(exists!).toBe(false);
      expect(result.current.hasAudio).toBe(false);
    });

    it('handles fetch errors gracefully', async () => {
      mockFetch.mockRejectedValueOnce(new Error('Network error'));

      const { result } = renderHook(() => useBroadcast(debateId));

      let exists: boolean;
      await act(async () => {
        exists = await result.current.checkAudioExists();
      });

      expect(exists!).toBe(false);
    });
  });

  describe('generateBroadcast', () => {
    it('generates broadcast successfully', async () => {
      const mockResult = {
        broadcast_id: 'bc-123',
        audio_url: 'https://api.example.com/audio/debate-123.mp3',
        status: 'complete',
        duration_seconds: 120,
      };

      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockResult) });

      const { result } = renderHook(() => useBroadcast(debateId));

      let broadcastResult: typeof mockResult;
      await act(async () => {
        broadcastResult = await result.current.generateBroadcast();
      });

      expect(broadcastResult!).toEqual(mockResult);
      expect(result.current.hasAudio).toBe(true);
      expect(result.current.isGenerating).toBe(false);
      expect(result.current.error).toBeNull();
    });

    it('sets isGenerating during generation', async () => {
      let resolvePromise: (value: Response) => void;
      mockFetch.mockReturnValueOnce(
        new Promise<Response>((resolve) => {
          resolvePromise = resolve;
        }),
      );

      const { result } = renderHook(() => useBroadcast(debateId));

      act(() => {
        result.current.generateBroadcast();
      });

      expect(result.current.isGenerating).toBe(true);

      await act(async () => {
        resolvePromise!({
          ok: true,
          json: () => Promise.resolve({ broadcast_id: 'bc-123', status: 'complete' }),
        } as Response);
      });

      await waitFor(() => {
        expect(result.current.isGenerating).toBe(false);
      });
    });

    it('handles generation errors', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: () => Promise.resolve({ error: 'Server error' }),
      });

      const { result } = renderHook(() => useBroadcast(debateId));

      await act(async () => {
        try {
          await result.current.generateBroadcast();
        } catch {
          // Expected to throw
        }
      });

      expect(result.current.error).toBe('Server error');
      expect(result.current.isGenerating).toBe(false);
    });
  });

  describe('publishToTwitter', () => {
    it('publishes to Twitter successfully', async () => {
      const mockResult = { success: true, url: 'https://twitter.com/status/123' };
      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockResult) });

      const { result } = renderHook(() => useBroadcast(debateId));

      let publishResult: typeof mockResult;
      await act(async () => {
        publishResult = await result.current.publishToTwitter('Check out this debate!');
      });

      expect(publishResult!).toEqual(mockResult);
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining(`/api/debates/${debateId}/publish/twitter`),
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('Check out this debate!'),
        }),
      );
    });

    it('returns error on failure', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: () => Promise.resolve({ error: 'Not authenticated' }),
      });

      const { result } = renderHook(() => useBroadcast(debateId));

      let publishResult: { success: boolean; error?: string };
      await act(async () => {
        publishResult = await result.current.publishToTwitter('Test');
      });

      expect(publishResult!.success).toBe(false);
      expect(publishResult!.error).toBe('Not authenticated');
    });
  });

  describe('publishToYouTube', () => {
    it('publishes to YouTube successfully', async () => {
      const mockResult = { success: true, url: 'https://youtube.com/watch?v=abc' };
      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockResult) });

      const { result } = renderHook(() => useBroadcast(debateId));

      let publishResult: typeof mockResult;
      await act(async () => {
        publishResult = await result.current.publishToYouTube('My Debate', 'Description');
      });

      expect(publishResult!).toEqual(mockResult);
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining(`/api/debates/${debateId}/publish/youtube`),
        expect.objectContaining({ method: 'POST', body: expect.stringContaining('My Debate') }),
      );
    });
  });

  describe('runFullPipeline', () => {
    it('runs full pipeline successfully', async () => {
      const mockResult = {
        debate_id: debateId,
        success: true,
        audio_path: '/audio/debate-123.mp3',
        audio_url: 'https://api.example.com/audio/debate-123.mp3',
        video_path: '/video/debate-123.mp4',
        video_url: 'https://api.example.com/video/debate-123.mp4',
        rss_episode_guid: 'guid-123',
        duration_seconds: 180,
        steps_completed: ['audio', 'video', 'rss'],
        generated_at: '2025-01-16T10:00:00Z',
        error: null,
      };

      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockResult) });

      const { result } = renderHook(() => useBroadcast(debateId));

      let pipelineResult: typeof mockResult;
      await act(async () => {
        pipelineResult = await result.current.runFullPipeline({ video: true });
      });

      expect(pipelineResult!).toEqual(mockResult);
      expect(result.current.hasAudio).toBe(true);
      expect(result.current.hasVideo).toBe(true);
      expect(result.current.stepsCompleted).toEqual(['audio', 'video', 'rss']);
    });

    it('includes options in URL params', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ debate_id: debateId, success: true, steps_completed: [] }),
      });

      const { result } = renderHook(() => useBroadcast(debateId));

      await act(async () => {
        await result.current.runFullPipeline({
          video: true,
          title: 'Test Title',
          episodeNumber: 42,
        });
      });

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringMatching(/video=true.*title=Test\+Title.*episode_number=42/),
        expect.any(Object),
      );
    });

    it('handles pipeline errors', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: () => Promise.resolve({ error: 'Pipeline failed' }),
      });

      const { result } = renderHook(() => useBroadcast(debateId));

      await act(async () => {
        try {
          await result.current.runFullPipeline();
        } catch {
          // Expected to throw
        }
      });

      expect(result.current.error).toBe('Pipeline failed');
      expect(result.current.isGenerating).toBe(false);
    });
  });

  describe('debateId changes', () => {
    it('uses correct debateId in requests', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ broadcast_id: 'bc-1', status: 'complete' }),
      });

      const { result, rerender } = renderHook(({ id }) => useBroadcast(id), {
        initialProps: { id: 'debate-1' },
      });

      await act(async () => {
        await result.current.generateBroadcast();
      });

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/debates/debate-1/broadcast'),
        expect.any(Object),
      );

      // Change debateId
      rerender({ id: 'debate-2' });

      await act(async () => {
        await result.current.generateBroadcast();
      });

      expect(mockFetch).toHaveBeenLastCalledWith(
        expect.stringContaining('/api/debates/debate-2/broadcast'),
        expect.any(Object),
      );
    });
  });
});
