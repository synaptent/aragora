'use client';

/**
 * TTSControls -- Text-to-Speech controls for debate audio playback.
 *
 * Features:
 *   - Play/Pause button
 *   - Voice selector (multiple TTS voices)
 *   - Speed control (0.5x - 2x)
 *   - Volume slider + mute toggle
 *   - Visual indicator of which text is being spoken (state display)
 */

import { useCallback } from 'react';
import type { TTSControls as TTSControlsType } from '@/hooks/useDebateStream';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TTSControlsProps {
  /** TTS controls from useDebateStream. */
  tts: TTSControlsType;
  /** Whether the debate is currently streaming (controls are dimmed otherwise). */
  isActive?: boolean;
  /** Compact mode for inline use. */
  compact?: boolean;
}

// ---------------------------------------------------------------------------
// Speed presets
// ---------------------------------------------------------------------------

const SPEED_OPTIONS = [
  { value: 0.5, label: '0.5x' },
  { value: 0.75, label: '0.75x' },
  { value: 1.0, label: '1x' },
  { value: 1.5, label: '1.5x' },
  { value: 2.0, label: '2x' },
];

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function PlayPauseButton({
  state,
  onPlay,
  onPause,
  disabled,
}: {
  state: TTSControlsType['state'];
  onPlay: () => void;
  onPause: () => void;
  disabled: boolean;
}) {
  const isPlaying = state === 'playing';
  const isLoading = state === 'loading';

  return (
    <button
      onClick={isPlaying ? onPause : onPlay}
      disabled={disabled || isLoading}
      className={`
        px-3 py-1.5 text-xs font-theme-data border transition-colors
        ${
          isPlaying
            ? 'bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/40 hover:bg-[var(--accent)]/30'
            : 'bg-surface text-text-muted border-border hover:border-[var(--accent)]/40 hover:text-[var(--accent)]'
        }
        ${disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}
        ${isLoading ? 'animate-pulse' : ''}
      `}
      title={isPlaying ? 'Pause TTS' : 'Play TTS'}
    >
      {isLoading ? '[LOADING...]' : isPlaying ? '[PAUSE]' : '[PLAY]'}
    </button>
  );
}

function StopButton({ onStop, disabled }: { onStop: () => void; disabled: boolean }) {
  return (
    <button
      onClick={onStop}
      disabled={disabled}
      className={`
        px-2 py-1.5 text-xs font-theme-data border transition-colors
        bg-surface text-text-muted border-border hover:border-red-400/40 hover:text-red-400
        ${disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}
      `}
      title="Stop TTS"
    >
      [STOP]
    </button>
  );
}

function MuteButton({ isMuted, onToggle }: { isMuted: boolean; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      className={`
        px-2 py-1.5 text-xs font-theme-data border transition-colors cursor-pointer
        ${
          isMuted
            ? 'bg-red-400/20 text-red-400 border-red-400/40'
            : 'bg-surface text-text-muted border-border hover:border-[var(--acid-cyan)]/40'
        }
      `}
      title={isMuted ? 'Unmute' : 'Mute'}
    >
      {isMuted ? '[MUTED]' : '[MUTE]'}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TTSControls({ tts, isActive = true, compact = false }: TTSControlsProps) {
  const handleSpeedChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      tts.setSpeed(parseFloat(e.target.value));
    },
    [tts],
  );

  const handleVolumeChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      tts.setVolume(parseFloat(e.target.value));
    },
    [tts],
  );

  const handleVoiceChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      tts.setVoice(e.target.value);
    },
    [tts],
  );

  if (compact) {
    return (
      <div className="flex items-center gap-2">
        <PlayPauseButton
          state={tts.state}
          onPlay={tts.play}
          onPause={tts.pause}
          disabled={!isActive}
        />
        <MuteButton isMuted={tts.isMuted} onToggle={tts.toggleMute} />
        {tts.state === 'playing' && (
          <span className="text-[10px] font-theme-data text-[var(--accent)] animate-pulse">
            SPEAKING
          </span>
        )}
        {tts.state === 'error' && (
          <span className="text-[10px] font-theme-data text-red-400">TTS ERROR</span>
        )}
      </div>
    );
  }

  return (
    <div className="bg-surface border border-border p-3">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <span className="text-[10px] font-theme-data text-text-muted uppercase tracking-wider">
          {'>'} TEXT-TO-SPEECH
        </span>
        {tts.state === 'playing' && (
          <span className="text-[10px] font-theme-data text-[var(--accent)] animate-pulse flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent)]" />
            SPEAKING
          </span>
        )}
        {tts.state === 'loading' && (
          <span className="text-[10px] font-theme-data text-[var(--acid-yellow)] animate-pulse">
            SYNTHESIZING...
          </span>
        )}
        {tts.state === 'error' && (
          <span className="text-[10px] font-theme-data text-red-400">TTS UNAVAILABLE</span>
        )}
      </div>

      {/* Playback controls row */}
      <div className="flex items-center gap-2 mb-3">
        <PlayPauseButton
          state={tts.state}
          onPlay={tts.play}
          onPause={tts.pause}
          disabled={!isActive}
        />
        <StopButton onStop={tts.stop} disabled={tts.state === 'idle'} />
        <MuteButton isMuted={tts.isMuted} onToggle={tts.toggleMute} />
      </div>

      {/* Voice selector */}
      <div className="grid grid-cols-2 gap-3 mb-3">
        <div>
          <label className="text-[10px] font-theme-data text-text-muted uppercase block mb-1">
            Voice
          </label>
          <select
            value={tts.selectedVoice}
            onChange={handleVoiceChange}
            className="w-full text-xs font-theme-data bg-bg text-text border border-border px-2 py-1 focus:border-[var(--accent)]/40 outline-none"
          >
            {tts.availableVoices.map((voice) => (
              <option key={voice} value={voice}>
                {voice.charAt(0).toUpperCase() + voice.slice(1)}
              </option>
            ))}
          </select>
        </div>

        {/* Speed selector */}
        <div>
          <label className="text-[10px] font-theme-data text-text-muted uppercase block mb-1">
            Speed
          </label>
          <select
            value={tts.speed}
            onChange={handleSpeedChange}
            className="w-full text-xs font-theme-data bg-bg text-text border border-border px-2 py-1 focus:border-[var(--accent)]/40 outline-none"
          >
            {SPEED_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Volume control */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <label className="text-[10px] font-theme-data text-text-muted uppercase">Volume</label>
          <span className="text-[10px] font-theme-data text-text-muted">
            {Math.round(tts.volume * 100)}%
          </span>
        </div>
        <input
          type="range"
          min="0"
          max="1"
          step="0.05"
          value={tts.isMuted ? 0 : tts.volume}
          onChange={handleVolumeChange}
          disabled={tts.isMuted}
          className="w-full h-1 bg-border rounded-full appearance-none cursor-pointer accent-acid-green"
        />
      </div>
    </div>
  );
}

export default TTSControls;
