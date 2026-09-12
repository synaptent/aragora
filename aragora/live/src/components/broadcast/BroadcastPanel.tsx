'use client';

import { useEffect, useCallback, useState } from 'react';
import { useBroadcast } from '@/hooks/useBroadcast';
import { AudioPlayer } from './AudioPlayer';
import { PublishDropdown } from './PublishDropdown';
import type { BroadcastPanelProps } from './types';

/**
 * Panel for generating audio broadcasts and publishing to social media
 *
 * Displays:
 * - Generate Audio button (when no audio exists)
 * - Video option checkbox
 * - Audio/Video players (when media exists)
 * - Pipeline progress (steps completed)
 * - Publish dropdown (when audio exists)
 */
export function BroadcastPanel({ debateId, debateTitle }: BroadcastPanelProps) {
  const {
    hasAudio,
    hasVideo,
    audioUrl,
    videoUrl,
    isGenerating,
    error,
    stepsCompleted,
    checkAudioExists,
    runFullPipeline,
  } = useBroadcast(debateId);

  const [includeVideo, setIncludeVideo] = useState(false);

  // Check if audio already exists on mount
  useEffect(() => {
    checkAudioExists();
  }, [checkAudioExists]);

  const handleGenerate = useCallback(async () => {
    try {
      await runFullPipeline({ video: includeVideo, rss: true, title: debateTitle });
    } catch {
      // Error is already captured in state
    }
  }, [runFullPipeline, includeVideo, debateTitle]);

  const stepLabels: Record<string, string> = {
    audio: 'Audio generated',
    video: 'Video generated',
    rss: 'RSS episode created',
    storage: 'Saved to storage',
  };

  return (
    <div className="border border-accent/30 bg-surface/50 mt-6">
      <div className="px-4 py-3 border-b border-accent/20 bg-bg/50 flex items-center justify-between">
        <span className="text-xs font-theme-data text-accent uppercase tracking-wider">
          {'>'} BROADCAST
        </span>
        {hasAudio && <PublishDropdown debateId={debateId} title={debateTitle} />}
      </div>

      <div className="p-4 space-y-4">
        {!hasAudio && !isGenerating && (
          <div className="space-y-3">
            <p className="text-xs font-theme-data text-text-muted">
              Generate an audio version of this debate using text-to-speech.
            </p>

            <label className="flex items-center gap-2 text-xs font-theme-data text-text-muted cursor-pointer">
              <input
                type="checkbox"
                checked={includeVideo}
                onChange={(e) => setIncludeVideo(e.target.checked)}
                className="w-3 h-3 accent-accent"
              />
              Include video (requires FFmpeg)
            </label>

            <button
              onClick={handleGenerate}
              disabled={isGenerating}
              className="w-full px-3 py-2 text-xs font-theme-data border border-accent/40 hover:bg-accent/10 disabled:opacity-50 transition-colors"
            >
              {includeVideo ? '[GENERATE AUDIO + VIDEO]' : '[GENERATE AUDIO]'}
            </button>
          </div>
        )}

        {isGenerating && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <div className="w-4 h-4 border-2 border-[var(--accent)]/40 border-t-acid-green rounded-full animate-spin" />
              <span className="text-xs font-theme-data text-[var(--accent)] animate-pulse">
                RUNNING PIPELINE...
              </span>
            </div>
            {stepsCompleted.length > 0 && (
              <div className="pl-6 space-y-1">
                {stepsCompleted.map((step) => (
                  <div key={step} className="text-xs font-theme-data text-[var(--accent)]/70">
                    ✓ {stepLabels[step] || step}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {error && (
          <div className="p-3 text-xs font-theme-data text-warning bg-warning/10 border border-warning/30">
            {'>'} ERROR: {error}
          </div>
        )}

        {hasAudio && audioUrl && (
          <div className="space-y-3">
            <AudioPlayer url={audioUrl} />
            {stepsCompleted.length > 0 && (
              <div className="text-xs font-theme-data text-text-muted">
                Pipeline: {stepsCompleted.map((s) => stepLabels[s] || s).join(' → ')}
              </div>
            )}
          </div>
        )}

        {hasVideo && videoUrl && (
          <div className="space-y-2">
            <div className="text-xs font-theme-data text-accent">{'>'} VIDEO</div>
            <video src={videoUrl} controls className="w-full max-h-64 bg-black" />
          </div>
        )}
      </div>
    </div>
  );
}
