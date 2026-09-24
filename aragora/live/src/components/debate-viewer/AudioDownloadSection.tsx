'use client';

import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL } from '@/config';

interface AudioDownloadSectionProps {
  debateId: string;
}

type AudioStatus = 'idle' | 'checking' | 'generating' | 'ready' | 'error';

export function AudioDownloadSection({ debateId }: AudioDownloadSectionProps) {
  const [status, setStatus] = useState<AudioStatus>('idle');
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Check if audio already exists on mount
  useEffect(() => {
    const checkAudio = async () => {
      setStatus('checking');
      try {
        const res = await fetch(`${API_BASE_URL}/audio/${debateId}.mp3`, { method: 'HEAD' });
        if (res.ok) {
          setAudioUrl(`${API_BASE_URL}/audio/${debateId}.mp3`);
          setStatus('ready');
        } else {
          setStatus('idle');
        }
      } catch {
        setStatus('idle');
      }
    };
    checkAudio();
  }, [debateId]);

  const generateAudio = useCallback(async () => {
    setStatus('generating');
    setError(null);
    try {
      const res = await fetch(`${API_BASE_URL}/api/debates/${debateId}/broadcast`, {
        method: 'POST',
      });
      const data = await res.json();

      if (data.audio_url) {
        // audio_url is relative like /audio/debate_id.mp3
        setAudioUrl(`${API_BASE_URL}${data.audio_url}`);
        setStatus('ready');
      } else if (data.status === 'exists' && data.audio_url) {
        setAudioUrl(`${API_BASE_URL}${data.audio_url}`);
        setStatus('ready');
      } else if (data.error) {
        setError(data.error);
        setStatus('error');
      } else {
        setError('Failed to generate audio');
        setStatus('error');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Generation failed');
      setStatus('error');
    }
  }, [debateId]);

  if (status === 'checking') {
    return (
      <span className="px-3 py-2 text-xs font-theme-data text-text-muted">Checking audio...</span>
    );
  }

  if (status === 'ready' && audioUrl) {
    return (
      <a
        href={audioUrl}
        download={`debate-${debateId}.mp3`}
        className="inline-block px-3 py-2 text-xs font-theme-data bg-bg border border-accent/40 text-accent hover:bg-accent/10 transition-colors"
      >
        [DOWNLOAD MP3]
      </a>
    );
  }

  if (status === 'generating') {
    return (
      <span className="px-3 py-2 text-xs font-theme-data bg-bg border border-border text-text-muted animate-pulse">
        [GENERATING AUDIO...]
      </span>
    );
  }

  if (status === 'error') {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <span
          className="text-xs font-theme-data text-red-400 truncate max-w-[200px]"
          title={error || ''}
        >
          {error}
        </span>
        <button
          onClick={generateAudio}
          className="px-3 py-2 text-xs font-theme-data bg-bg border border-border text-text-muted hover:border-accent/40 transition-colors"
        >
          [RETRY]
        </button>
      </div>
    );
  }

  // idle state - show generate button
  return (
    <button
      onClick={generateAudio}
      className="px-3 py-2 text-xs font-theme-data bg-bg border border-accent/40 text-accent hover:bg-accent/10 transition-colors"
    >
      [GENERATE MP3]
    </button>
  );
}

export default AudioDownloadSection;
