/**
 * useStreamingAudio — Progressive audio playback via MediaSource API.
 *
 * Receives raw mp3 chunks from the Oracle WebSocket (binary frames with
 * 1-byte phase tag prefix) and plays them through a gapless MediaSource
 * pipeline. Falls back to blob-based Audio() if MediaSource is unsupported.
 */

import { useCallback, useRef } from 'react';

export type AudioPhase = 'reflex' | 'deep' | 'tentacle' | 'synthesis';

interface UseStreamingAudio {
  /** Append a binary chunk (phase-tag-prefixed mp3 data) from WebSocket. */
  appendChunk: (data: ArrayBuffer) => void;
  /** Signal end of current audio stream segment. */
  endSegment: () => void;
  /** Stop all playback and reset. */
  stop: () => void;
  /** Pause audio playback (resumable). */
  pause: () => void;
  /** Resume paused audio playback. */
  resume: () => void;
  /** Whether audio is currently playing. */
  isPlaying: () => boolean;
  /** Whether audio is currently paused. */
  isPaused: () => boolean;
}

/**
 * Check if MediaSource API supports audio/mpeg.
 * Falls back to blob-based playback if not.
 */
function supportsMediaSource(): boolean {
  if (typeof window === 'undefined') return false;
  if (!('MediaSource' in window)) return false;
  try {
    return MediaSource.isTypeSupported('audio/mpeg');
  } catch {
    return false;
  }
}

export function useStreamingAudio(): UseStreamingAudio {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const mediaSourceRef = useRef<MediaSource | null>(null);
  const sourceBufferRef = useRef<SourceBuffer | null>(null);
  const queueRef = useRef<ArrayBuffer[]>([]);
  const endedRef = useRef(false);
  const useMediaSource = useRef(supportsMediaSource());

  // Fallback: accumulate chunks and play as blob
  const fallbackChunksRef = useRef<ArrayBuffer[]>([]);
  const fallbackAudioRef = useRef<HTMLAudioElement | null>(null);

  const flushQueue = useCallback(() => {
    const sb = sourceBufferRef.current;
    if (!sb || sb.updating || queueRef.current.length === 0) return;

    const chunk = queueRef.current.shift();
    if (chunk) {
      try {
        sb.appendBuffer(chunk);
      } catch {
        // Buffer full or error — re-queue and try later
        queueRef.current.unshift(chunk);
      }
    }
  }, []);

  const ensureMediaSource = useCallback(() => {
    if (mediaSourceRef.current && audioRef.current) return;

    const mediaSource = new MediaSource();
    mediaSourceRef.current = mediaSource;

    const audio = new Audio();
    audio.src = URL.createObjectURL(mediaSource);
    audioRef.current = audio;

    mediaSource.addEventListener('sourceopen', () => {
      try {
        const sb = mediaSource.addSourceBuffer('audio/mpeg');
        sourceBufferRef.current = sb;

        sb.addEventListener('updateend', () => {
          if (queueRef.current.length > 0) {
            flushQueue();
          } else if (endedRef.current && mediaSource.readyState === 'open') {
            try {
              mediaSource.endOfStream();
            } catch {
              // Already ended
            }
          }
        });

        // Flush any chunks that arrived before sourceopen
        flushQueue();
      } catch {
        // Codec not supported — fall back
        useMediaSource.current = false;
      }
    });

    audio.play().catch((err) => {
      console.warn('[useStreamingAudio] Autoplay blocked or playback failed:', err);
    });
  }, [flushQueue]);

  const appendChunk = useCallback(
    (data: ArrayBuffer) => {
      if (data.byteLength < 2) return; // Need at least tag + 1 byte

      // Strip the 1-byte phase tag prefix
      const raw = new Uint8Array(data);
      const audioData = raw.slice(1);
      // Convert to ArrayBuffer for SourceBuffer.appendBuffer() compatibility
      const audioBuffer = audioData.buffer.slice(
        audioData.byteOffset,
        audioData.byteOffset + audioData.byteLength,
      );

      if (useMediaSource.current) {
        ensureMediaSource();
        endedRef.current = false;
        queueRef.current.push(audioBuffer);
        flushQueue();
      } else {
        // Fallback: accumulate chunks for blob playback
        fallbackChunksRef.current.push(audioBuffer);
      }
    },
    [ensureMediaSource, flushQueue],
  );

  const endSegment = useCallback(() => {
    if (useMediaSource.current) {
      endedRef.current = true;
      // If nothing is updating, end now
      const sb = sourceBufferRef.current;
      const ms = mediaSourceRef.current;
      if (sb && !sb.updating && queueRef.current.length === 0 && ms?.readyState === 'open') {
        try {
          ms.endOfStream();
        } catch {
          // Already ended
        }
      }
    } else {
      // Fallback: play accumulated chunks as blob
      if (fallbackChunksRef.current.length > 0) {
        const blob = new Blob(fallbackChunksRef.current, { type: 'audio/mpeg' });
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        fallbackAudioRef.current = audio;
        audio.onended = () => {
          URL.revokeObjectURL(url);
          fallbackAudioRef.current = null;
        };
        audio.play().catch((err) => {
          console.warn('[useStreamingAudio] Fallback audio playback failed:', err);
        });
        fallbackChunksRef.current = [];
      }
    }
  }, []);

  const stop = useCallback(() => {
    // Stop MediaSource playback
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = '';
      audioRef.current = null;
    }
    if (mediaSourceRef.current?.readyState === 'open') {
      try {
        mediaSourceRef.current.endOfStream();
      } catch {
        // Already ended
      }
    }
    mediaSourceRef.current = null;
    sourceBufferRef.current = null;
    queueRef.current = [];
    endedRef.current = false;

    // Stop fallback playback
    if (fallbackAudioRef.current) {
      fallbackAudioRef.current.pause();
      fallbackAudioRef.current = null;
    }
    fallbackChunksRef.current = [];
  }, []);

  const pause = useCallback(() => {
    if (audioRef.current && !audioRef.current.paused) {
      audioRef.current.pause();
    }
    if (fallbackAudioRef.current && !fallbackAudioRef.current.paused) {
      fallbackAudioRef.current.pause();
    }
  }, []);

  const resume = useCallback(() => {
    if (audioRef.current?.paused) {
      audioRef.current.play().catch((err) => {
        console.warn('[useStreamingAudio] Resume playback failed:', err);
      });
    }
    if (fallbackAudioRef.current?.paused) {
      fallbackAudioRef.current.play().catch((err) => {
        console.warn('[useStreamingAudio] Resume fallback playback failed:', err);
      });
    }
  }, []);

  const isPlaying = useCallback(() => {
    if (audioRef.current && !audioRef.current.paused) return true;
    if (fallbackAudioRef.current && !fallbackAudioRef.current.paused) return true;
    return false;
  }, []);

  const isPaused = useCallback(() => {
    if (audioRef.current?.paused && audioRef.current.currentTime > 0) return true;
    if (fallbackAudioRef.current?.paused && fallbackAudioRef.current.currentTime > 0) return true;
    return false;
  }, []);

  return { appendChunk, endSegment, stop, pause, resume, isPlaying, isPaused };
}

export default useStreamingAudio;
