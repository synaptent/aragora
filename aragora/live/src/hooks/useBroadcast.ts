'use client';

import { useState, useCallback } from 'react';
import { API_BASE_URL } from '@/config';

const API_BASE = API_BASE_URL;

interface BroadcastStatus {
  hasAudio: boolean;
  hasVideo: boolean;
  audioUrl: string | null;
  videoUrl: string | null;
  isGenerating: boolean;
  error: string | null;
  stepsCompleted: string[];
}

interface BroadcastResult {
  broadcast_id: string;
  audio_url: string;
  status: 'generating' | 'complete' | 'error';
  duration_seconds?: number;
}

interface PipelineResult {
  debate_id: string;
  success: boolean;
  audio_path: string | null;
  audio_url: string | null;
  video_path: string | null;
  video_url: string | null;
  rss_episode_guid: string | null;
  duration_seconds: number | null;
  steps_completed: string[];
  generated_at: string;
  error: string | null;
}

interface PipelineOptions {
  video?: boolean;
  rss?: boolean;
  title?: string;
  description?: string;
  episodeNumber?: number;
}

interface PublishResult {
  success: boolean;
  url?: string;
  error?: string;
}

/**
 * Hook for managing broadcast generation and social publishing
 *
 * @example
 * const { hasAudio, generateBroadcast, publishToTwitter } = useBroadcast(debateId);
 */
export function useBroadcast(debateId: string) {
  const [status, setStatus] = useState<BroadcastStatus>({
    hasAudio: false,
    hasVideo: false,
    audioUrl: null,
    videoUrl: null,
    isGenerating: false,
    error: null,
    stepsCompleted: [],
  });

  const checkAudioExists = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/audio/${debateId}.mp3`, { method: 'HEAD' });
      if (response.ok) {
        setStatus((s) => ({ ...s, hasAudio: true, audioUrl: `${API_BASE}/audio/${debateId}.mp3` }));
        return true;
      }
      return false;
    } catch {
      // Audio doesn't exist yet
      return false;
    }
  }, [debateId]);

  const generateBroadcast = useCallback(async (): Promise<BroadcastResult> => {
    setStatus((s) => ({ ...s, isGenerating: true, error: null }));
    try {
      const response = await fetch(`${API_BASE}/api/debates/${debateId}/broadcast`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ format: 'mp3' }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || `HTTP ${response.status}`);
      }

      const result: BroadcastResult = await response.json();
      setStatus((prev) => ({
        ...prev,
        hasAudio: true,
        audioUrl: result.audio_url || `${API_BASE}/audio/${debateId}.mp3`,
        isGenerating: false,
        error: null,
      }));
      return result;
    } catch (e) {
      const errorMessage = e instanceof Error ? e.message : 'Failed to generate broadcast';
      setStatus((s) => ({ ...s, isGenerating: false, error: errorMessage }));
      throw e;
    }
  }, [debateId]);

  const publishToTwitter = useCallback(
    async (text: string): Promise<PublishResult> => {
      const response = await fetch(`${API_BASE}/api/debates/${debateId}/publish/twitter`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, debate_id: debateId }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        return { success: false, error: errorData.error || `HTTP ${response.status}` };
      }

      return response.json();
    },
    [debateId],
  );

  const publishToYouTube = useCallback(
    async (title: string, description: string): Promise<PublishResult> => {
      const response = await fetch(`${API_BASE}/api/debates/${debateId}/publish/youtube`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, description, debate_id: debateId }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        return { success: false, error: errorData.error || `HTTP ${response.status}` };
      }

      return response.json();
    },
    [debateId],
  );

  const runFullPipeline = useCallback(
    async (options: PipelineOptions = {}): Promise<PipelineResult> => {
      setStatus((s) => ({ ...s, isGenerating: true, error: null, stepsCompleted: [] }));

      try {
        const params = new URLSearchParams();
        if (options.video) params.set('video', 'true');
        if (options.rss !== false) params.set('rss', 'true');
        if (options.title) params.set('title', options.title);
        if (options.description) params.set('description', options.description);
        if (options.episodeNumber) params.set('episode_number', String(options.episodeNumber));

        const url = `${API_BASE}/api/debates/${debateId}/broadcast/full${params.toString() ? `?${params}` : ''}`;
        const response = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.error || `HTTP ${response.status}`);
        }

        const result: PipelineResult = await response.json();

        setStatus({
          hasAudio: !!result.audio_url,
          hasVideo: !!result.video_url,
          audioUrl: result.audio_url || `${API_BASE}/audio/${debateId}.mp3`,
          videoUrl: result.video_url,
          isGenerating: false,
          error: result.error,
          stepsCompleted: result.steps_completed || [],
        });

        return result;
      } catch (e) {
        const errorMessage = e instanceof Error ? e.message : 'Pipeline failed';
        setStatus((s) => ({ ...s, isGenerating: false, error: errorMessage }));
        throw e;
      }
    },
    [debateId],
  );

  return {
    ...status,
    checkAudioExists,
    generateBroadcast,
    runFullPipeline,
    publishToTwitter,
    publishToYouTube,
  };
}
