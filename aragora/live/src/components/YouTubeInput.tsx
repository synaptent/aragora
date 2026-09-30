'use client';

import { useState, useCallback, useEffect } from 'react';

interface YouTubeVideoInfo {
  video_id: string;
  title: string;
  duration: number;
  channel: string;
  thumbnail_url?: string;
}

interface YouTubeInputProps {
  onSubmit: (url: string, videoInfo: YouTubeVideoInfo) => void;
  disabled?: boolean;
  apiBase?: string;
  maxDurationSeconds?: number;
}

type InputState = 'idle' | 'validating' | 'valid' | 'error';

// YouTube URL patterns for validation
const YOUTUBE_PATTERNS = [
  /(?:https?:\/\/)?(?:www\.)?youtube\.com\/watch\?v=([a-zA-Z0-9_-]{11})/,
  /(?:https?:\/\/)?(?:www\.)?youtu\.be\/([a-zA-Z0-9_-]{11})/,
  /(?:https?:\/\/)?(?:www\.)?youtube\.com\/embed\/([a-zA-Z0-9_-]{11})/,
  /(?:https?:\/\/)?(?:www\.)?youtube\.com\/v\/([a-zA-Z0-9_-]{11})/,
  /(?:https?:\/\/)?(?:www\.)?youtube\.com\/shorts\/([a-zA-Z0-9_-]{11})/,
];

function extractVideoId(url: string): string | null {
  for (const pattern of YOUTUBE_PATTERNS) {
    const match = url.match(pattern);
    if (match) {
      return match[1];
    }
  }
  return null;
}

function formatDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;

  if (hours > 0) {
    return `${hours}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  }
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

export function YouTubeInput({
  onSubmit,
  disabled = false,
  apiBase = '',
  maxDurationSeconds = 7200, // 2 hours default
}: YouTubeInputProps) {
  const [url, setUrl] = useState('');
  const [state, setState] = useState<InputState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [videoInfo, setVideoInfo] = useState<YouTubeVideoInfo | null>(null);

  // Validate URL and fetch video info
  const validateUrl = useCallback(
    async (inputUrl: string) => {
      const videoId = extractVideoId(inputUrl);

      if (!videoId) {
        setState('idle');
        setVideoInfo(null);
        return;
      }

      setState('validating');
      setError(null);

      try {
        const response = await fetch(`${apiBase}/api/transcription/youtube/info`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: inputUrl }),
        });

        const data = await response.json();

        if (!response.ok) {
          throw new Error(data.error || 'Failed to fetch video info');
        }

        const info: YouTubeVideoInfo = {
          video_id: data.video_id,
          title: data.title,
          duration: data.duration,
          channel: data.channel,
          thumbnail_url: data.thumbnail_url,
        };

        if (info.duration > maxDurationSeconds) {
          setError(
            `Video too long (${formatDuration(info.duration)}). Max: ${formatDuration(maxDurationSeconds)}`,
          );
          setState('error');
          setVideoInfo(info);
          return;
        }

        setVideoInfo(info);
        setState('valid');
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to validate URL');
        setState('error');
        setVideoInfo(null);
      }
    },
    [apiBase, maxDurationSeconds],
  );

  // Debounced URL validation
  useEffect(() => {
    if (!url.trim()) {
      setState('idle');
      setVideoInfo(null);
      setError(null);
      return;
    }

    const videoId = extractVideoId(url);
    if (!videoId) {
      setState('idle');
      setVideoInfo(null);
      return;
    }

    const timer = setTimeout(() => {
      validateUrl(url);
    }, 500);

    return () => clearTimeout(timer);
  }, [url, validateUrl]);

  const handleSubmit = useCallback(() => {
    if (state === 'valid' && videoInfo) {
      onSubmit(url, videoInfo);
      setUrl('');
      setState('idle');
      setVideoInfo(null);
    }
  }, [state, videoInfo, url, onSubmit]);

  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    const pastedText = e.clipboardData.getData('text');
    if (extractVideoId(pastedText)) {
      setUrl(pastedText);
    }
  }, []);

  const isPlaylist = url.includes('list=');

  return (
    <div className="space-y-3">
      {/* URL Input */}
      <div className="flex gap-2">
        <div className="flex-1 relative">
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onPaste={handlePaste}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && state === 'valid') {
                handleSubmit();
              }
            }}
            placeholder="Paste YouTube URL..."
            disabled={disabled}
            className={`
              w-full px-3 py-2 rounded-lg border bg-surface text-text
              placeholder:text-text-muted
              focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-surface
              ${state === 'error' ? 'border-[var(--crimson)] focus:ring-crimson' : 'border-border focus:ring-accent'}
              ${disabled ? 'opacity-50 cursor-not-allowed' : ''}
            `}
            aria-label="YouTube video URL"
          />
          {state === 'validating' && (
            <div className="absolute right-3 top-1/2 -translate-y-1/2">
              <svg className="animate-spin h-4 w-4 text-text-muted" viewBox="0 0 24 24">
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                  fill="none"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                />
              </svg>
            </div>
          )}
        </div>
        <button
          onClick={handleSubmit}
          disabled={disabled || state !== 'valid'}
          className={`
            px-4 py-2 rounded-lg font-medium transition-colors
            focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-surface focus:ring-accent
            ${
              state === 'valid'
                ? 'bg-accent text-white hover:bg-accent/80'
                : 'bg-surface-elevated text-text-muted cursor-not-allowed'
            }
          `}
        >
          Transcribe
        </button>
      </div>

      {/* Playlist warning */}
      {isPlaylist && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded p-2 text-sm text-amber-400 flex items-start gap-2">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
            className="w-5 h-5 flex-shrink-0"
          >
            <path
              fillRule="evenodd"
              d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z"
              clipRule="evenodd"
            />
          </svg>
          <span>This looks like a playlist URL. Only the first video will be transcribed.</span>
        </div>
      )}

      {/* Error message */}
      {error && (
        <div className="bg-[var(--crimson)]/10 border border-[var(--crimson)]/30 rounded p-2 text-sm text-[var(--crimson)]">
          {error}
        </div>
      )}

      {/* Video preview */}
      {videoInfo && (
        <div className="bg-surface border border-border rounded-lg overflow-hidden flex">
          {/* Thumbnail */}
          {videoInfo.thumbnail_url ? (
            <div className="w-32 h-20 flex-shrink-0 bg-surface-elevated relative">
              <img
                src={videoInfo.thumbnail_url}
                alt={videoInfo.title}
                className="w-full h-full object-cover"
              />
              <div className="absolute bottom-1 right-1 bg-black/80 text-white text-xs px-1 rounded">
                {formatDuration(videoInfo.duration)}
              </div>
            </div>
          ) : (
            <div className="w-32 h-20 flex-shrink-0 bg-surface-elevated flex items-center justify-center">
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 24 24"
                fill="currentColor"
                className="w-8 h-8 text-text-muted"
              >
                <path
                  fillRule="evenodd"
                  d="M4.5 5.653c0-1.426 1.529-2.33 2.779-1.643l11.54 6.348c1.295.712 1.295 2.573 0 3.285L7.28 19.991c-1.25.687-2.779-.217-2.779-1.643V5.653z"
                  clipRule="evenodd"
                />
              </svg>
            </div>
          )}

          {/* Info */}
          <div className="flex-1 p-3 min-w-0">
            <div className="font-medium text-sm truncate" title={videoInfo.title}>
              {videoInfo.title}
            </div>
            <div className="text-xs text-text-muted truncate">{videoInfo.channel}</div>
            <div className="text-xs text-text-muted mt-1">
              Duration: {formatDuration(videoInfo.duration)}
              {videoInfo.duration > maxDurationSeconds && (
                <span className="text-[var(--crimson)] ml-2">
                  (exceeds {formatDuration(maxDurationSeconds)} limit)
                </span>
              )}
            </div>
          </div>

          {/* Clear button */}
          <button
            onClick={() => {
              setUrl('');
              setState('idle');
              setVideoInfo(null);
              setError(null);
            }}
            className="p-3 text-text-muted hover:text-[var(--crimson)] transition-colors flex-shrink-0"
            aria-label="Clear URL"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 20 20"
              fill="currentColor"
              className="w-5 h-5"
            >
              <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
            </svg>
          </button>
        </div>
      )}

      {/* Help text */}
      {state === 'idle' && !videoInfo && (
        <div className="text-xs text-text-muted">
          Supports youtube.com and youtu.be URLs. Max video length:{' '}
          {formatDuration(maxDurationSeconds)}.
        </div>
      )}
    </div>
  );
}
