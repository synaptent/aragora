/**
 * useDebateStream -- React hook for real-time debate streaming with TTS support.
 *
 * Connects to the debate WebSocket and augments it with:
 *   - Per-agent token buffering for smooth rendering
 *   - Debate phase tracking (proposal -> critique -> revision -> vote)
 *   - TTS audio queue management (fetch audio chunks, queue for playback)
 *   - Stream quality metrics (TTFT, latency, stall detection)
 *   - Reconnection state forwarding from the underlying WebSocket
 *
 * Usage:
 *   const stream = useDebateStream({ debateId: 'adhoc_abc123' });
 *   // stream.messages, stream.currentPhase, stream.isStreaming, etc.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useDebateWebSocket } from '@/hooks/debate-websocket/useDebateWebSocket';
import { useStreamingAudio } from '@/hooks/useStreamingAudio';
import { WS_URL, API_BASE_URL } from '@/config';
import type {
  TranscriptMessage,
  StreamingMessage,
  DebateConnectionStatus,
} from '@/hooks/debate-websocket/types';
import type { StreamEvent } from '@/types/events';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type DebatePhase =
  | 'idle'
  | 'initializing'
  | 'proposal'
  | 'critique'
  | 'revision'
  | 'cross_examination'
  | 'synthesis'
  | 'vote'
  | 'complete';

export type TTSState = 'idle' | 'loading' | 'playing' | 'paused' | 'error';

export interface StreamMetrics {
  /** Time-to-first-token in milliseconds (null if no tokens received yet). */
  ttftMs: number | null;
  /** Number of tokens received in the current stream. */
  tokenCount: number;
  /** Number of stream stalls detected. */
  stallCount: number;
  /** Average inter-token latency in milliseconds. */
  avgTokenLatencyMs: number | null;
  /** Total stream duration in milliseconds (null if still streaming). */
  streamDurationMs: number | null;
  /** Current connection latency from heartbeat. */
  connectionLatencyMs: number | null;
}

export interface TTSControls {
  /** Current TTS playback state. */
  state: TTSState;
  /** Play or resume TTS audio. */
  play: () => void;
  /** Pause TTS audio. */
  pause: () => void;
  /** Stop TTS and clear the queue. */
  stop: () => void;
  /** Set playback speed (0.5 - 2.0). */
  setSpeed: (speed: number) => void;
  /** Set volume (0.0 - 1.0). */
  setVolume: (volume: number) => void;
  /** Toggle mute. */
  toggleMute: () => void;
  /** Current playback speed. */
  speed: number;
  /** Current volume (0.0 - 1.0). */
  volume: number;
  /** Whether audio is muted. */
  isMuted: boolean;
  /** Index of the message currently being spoken (for highlight sync). */
  speakingMessageIndex: number | null;
  /** Available voices (populated after first TTS request). */
  availableVoices: string[];
  /** Currently selected voice. */
  selectedVoice: string;
  /** Set voice for TTS. */
  setVoice: (voice: string) => void;
}

export interface UseDebateStreamOptions {
  debateId: string;
  wsUrl?: string;
  enabled?: boolean;
  /** Enable TTS audio for agent messages. */
  enableTTS?: boolean;
  /** Access token for authenticated connections. */
  accessToken?: string | null;
}

export interface UseDebateStreamReturn {
  // Data
  messages: TranscriptMessage[];
  streamingMessages: Map<string, StreamingMessage>;
  streamEvents: StreamEvent[];
  agents: string[];
  task: string;

  // State
  currentPhase: DebatePhase;
  isStreaming: boolean;
  connectionStatus: DebateConnectionStatus;
  error: string | null;

  // Metrics
  streamMetrics: StreamMetrics;

  // TTS
  tts: TTSControls;

  // Actions
  reconnect: () => void;
}

// ---------------------------------------------------------------------------
// Phase mapping from stream events to DebatePhase
// ---------------------------------------------------------------------------

const ROUND_TO_PHASE: Record<number, DebatePhase> = {
  0: 'initializing',
  1: 'proposal',
  2: 'critique',
  3: 'proposal', // lateral exploration = alternate proposal
  4: 'critique', // devil's advocacy = adversarial critique
  5: 'synthesis',
  6: 'cross_examination',
  7: 'revision', // final synthesis = revision
  8: 'vote', // final adjudication = vote
};

function roundToPhase(round: number): DebatePhase {
  return ROUND_TO_PHASE[round] ?? 'proposal';
}

// ---------------------------------------------------------------------------
// Available TTS voices (default set, can be extended via server config)
// ---------------------------------------------------------------------------

const DEFAULT_VOICES = ['narrator', 'alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer'];

// ---------------------------------------------------------------------------
// Hook implementation
// ---------------------------------------------------------------------------

export function useDebateStream({
  debateId,
  wsUrl = WS_URL,
  enabled = true,
  enableTTS = false,
  accessToken = null,
}: UseDebateStreamOptions): UseDebateStreamReturn {
  // -- Underlying debate WebSocket --
  const {
    status: connectionStatus,
    error,
    task,
    agents,
    messages,
    streamingMessages,
    streamEvents,
    reconnect,
    connectionQuality,
  } = useDebateWebSocket({ debateId, wsUrl, enabled, accessToken });

  // -- Phase tracking --
  const [currentPhase, setCurrentPhase] = useState<DebatePhase>('idle');

  // -- Stream metrics --
  const [metrics, setMetrics] = useState<StreamMetrics>({
    ttftMs: null,
    tokenCount: 0,
    stallCount: 0,
    avgTokenLatencyMs: null,
    streamDurationMs: null,
    connectionLatencyMs: null,
  });

  const streamStartRef = useRef<number | null>(null);
  const firstTokenTimeRef = useRef<number | null>(null);
  const tokenTimestampsRef = useRef<number[]>([]);
  const stallTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prevTokenCountRef = useRef(0);

  // -- TTS state --
  const [ttsState, setTTSState] = useState<TTSState>('idle');
  const [ttsSpeed, setTTSSpeed] = useState(1.0);
  const [ttsVolume, setTTSVolume] = useState(1.0);
  const [ttsMuted, setTTSMuted] = useState(false);
  const [speakingMessageIndex, setSpeakingMessageIndex] = useState<number | null>(null);
  const [selectedVoice, setSelectedVoice] = useState('narrator');
  const ttsQueueRef = useRef<Array<{ text: string; messageIndex: number }>>([]);
  const ttsProcessingRef = useRef(false);
  const audio = useStreamingAudio();

  // -- Derived state --
  const isStreaming = connectionStatus === 'streaming';

  // ==========================================================================
  // Phase tracking from stream events
  // ==========================================================================

  useEffect(() => {
    if (connectionStatus === 'idle') {
      setCurrentPhase('idle');
      return;
    }
    if (connectionStatus === 'complete') {
      setCurrentPhase('complete');
      return;
    }

    // Derive phase from stream events
    const phaseEvents = streamEvents.filter(
      (e) => e.type === 'phase_progress' || e.type === 'round_start',
    );
    if (phaseEvents.length > 0) {
      const lastEvent = phaseEvents[phaseEvents.length - 1];
      const data = lastEvent.data as Record<string, unknown>;
      const round = (data?.phase as number) ?? (data?.round as number) ?? 0;
      setCurrentPhase(roundToPhase(round));
      return;
    }

    // Fallback: estimate from messages
    if (messages.length > 0) {
      const maxRound = Math.max(...messages.map((m) => m.round ?? 0));
      setCurrentPhase(roundToPhase(maxRound));
    } else if (connectionStatus === 'streaming') {
      setCurrentPhase('initializing');
    }
  }, [connectionStatus, streamEvents, messages]);

  // ==========================================================================
  // Stream metrics tracking
  // ==========================================================================

  // Track stream start
  useEffect(() => {
    if (connectionStatus === 'streaming' && streamStartRef.current === null) {
      streamStartRef.current = performance.now();
      firstTokenTimeRef.current = null;
      tokenTimestampsRef.current = [];
      prevTokenCountRef.current = 0;
      setMetrics({
        ttftMs: null,
        tokenCount: 0,
        stallCount: 0,
        avgTokenLatencyMs: null,
        streamDurationMs: null,
        connectionLatencyMs: connectionQuality?.avgLatencyMs ?? null,
      });
    }
    if (connectionStatus === 'complete' || connectionStatus === 'error') {
      if (streamStartRef.current !== null) {
        const duration = performance.now() - streamStartRef.current;
        setMetrics((prev) => ({ ...prev, streamDurationMs: Math.round(duration) }));
      }
      streamStartRef.current = null;
    }
  }, [connectionStatus, connectionQuality?.avgLatencyMs]);

  // Track tokens from streaming messages
  useEffect(() => {
    let totalTokens = 0;
    for (const [, sm] of streamingMessages) {
      // Approximate token count by word splits (tokens ~ words for display)
      totalTokens += sm.content.split(/\s+/).filter(Boolean).length;
    }

    if (totalTokens > prevTokenCountRef.current) {
      const now = performance.now();

      // Track TTFT
      if (firstTokenTimeRef.current === null && streamStartRef.current !== null) {
        firstTokenTimeRef.current = now;
        setMetrics((prev) => ({ ...prev, ttftMs: Math.round(now - streamStartRef.current!) }));
      }

      tokenTimestampsRef.current.push(now);
      prevTokenCountRef.current = totalTokens;

      // Calculate average inter-token latency
      const timestamps = tokenTimestampsRef.current;
      if (timestamps.length >= 2) {
        let totalGap = 0;
        for (let i = 1; i < timestamps.length; i++) {
          totalGap += timestamps[i] - timestamps[i - 1];
        }
        const avgLatency = totalGap / (timestamps.length - 1);
        setMetrics((prev) => ({
          ...prev,
          tokenCount: totalTokens,
          avgTokenLatencyMs: Math.round(avgLatency),
          connectionLatencyMs: connectionQuality?.avgLatencyMs ?? prev.connectionLatencyMs,
        }));
      } else {
        setMetrics((prev) => ({
          ...prev,
          tokenCount: totalTokens,
          connectionLatencyMs: connectionQuality?.avgLatencyMs ?? prev.connectionLatencyMs,
        }));
      }
    }

    // Reset stall timer on activity
    if (stallTimerRef.current) {
      clearTimeout(stallTimerRef.current);
    }
    if (isStreaming) {
      stallTimerRef.current = setTimeout(() => {
        setMetrics((prev) => ({ ...prev, stallCount: prev.stallCount + 1 }));
      }, 15000); // 15s without new tokens = stall
    }
  }, [streamingMessages, isStreaming, connectionQuality?.avgLatencyMs]);

  // Cleanup stall timer
  useEffect(() => {
    return () => {
      if (stallTimerRef.current) clearTimeout(stallTimerRef.current);
    };
  }, []);

  // ==========================================================================
  // TTS management
  // ==========================================================================

  // Queue new completed messages for TTS
  const lastTTSMessageCount = useRef(0);
  useEffect(() => {
    if (!enableTTS || !isStreaming) return;

    // Queue any new completed messages
    if (messages.length > lastTTSMessageCount.current) {
      const newMessages = messages.slice(lastTTSMessageCount.current);
      for (const msg of newMessages) {
        if (msg.content && msg.agent !== 'system') {
          ttsQueueRef.current.push({
            text: msg.content,
            messageIndex: lastTTSMessageCount.current + newMessages.indexOf(msg),
          });
        }
      }
      lastTTSMessageCount.current = messages.length;
      processNextTTS();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages.length, enableTTS, isStreaming]);

  const processNextTTS = useCallback(async () => {
    if (ttsProcessingRef.current || ttsQueueRef.current.length === 0) return;
    if (ttsMuted) return;

    ttsProcessingRef.current = true;
    const item = ttsQueueRef.current.shift();
    if (!item) {
      ttsProcessingRef.current = false;
      return;
    }

    setTTSState('loading');
    setSpeakingMessageIndex(item.messageIndex);

    try {
      // Request TTS audio from the server
      const response = await fetch(`${API_BASE_URL}/api/tts/synthesize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: item.text.slice(0, 2000), // Truncate for TTS
          voice: selectedVoice,
          speed: ttsSpeed,
        }),
      });

      if (!response.ok) {
        throw new Error(`TTS request failed: ${response.status}`);
      }

      const audioData = await response.arrayBuffer();
      if (audioData.byteLength > 0) {
        // Create a prefixed buffer (1-byte phase tag + audio data)
        // Phase tag 0 = main audio
        const prefixed = new Uint8Array(audioData.byteLength + 1);
        prefixed[0] = 0;
        prefixed.set(new Uint8Array(audioData), 1);

        audio.appendChunk(prefixed.buffer);
        audio.endSegment();
        setTTSState('playing');
      }
    } catch {
      setTTSState('error');
    } finally {
      ttsProcessingRef.current = false;
      setSpeakingMessageIndex(null);

      // Process next in queue after a short delay
      if (ttsQueueRef.current.length > 0) {
        setTimeout(processNextTTS, 300);
      } else {
        setTTSState('idle');
      }
    }
  }, [audio, selectedVoice, ttsSpeed, ttsMuted]);

  // -- TTS controls --
  const ttsPlay = useCallback(() => {
    if (audio.isPaused()) {
      audio.resume();
      setTTSState('playing');
    } else {
      processNextTTS();
    }
  }, [audio, processNextTTS]);

  const ttsPause = useCallback(() => {
    audio.pause();
    setTTSState('paused');
  }, [audio]);

  const ttsStop = useCallback(() => {
    audio.stop();
    ttsQueueRef.current = [];
    ttsProcessingRef.current = false;
    setSpeakingMessageIndex(null);
    setTTSState('idle');
  }, [audio]);

  const ttsSetSpeed = useCallback((speed: number) => {
    setTTSSpeed(Math.max(0.5, Math.min(2.0, speed)));
  }, []);

  const ttsSetVolume = useCallback((volume: number) => {
    setTTSVolume(Math.max(0.0, Math.min(1.0, volume)));
  }, []);

  const ttsToggleMute = useCallback(() => {
    setTTSMuted((prev) => {
      if (!prev) {
        // Muting: pause current audio
        audio.pause();
        setTTSState('paused');
      }
      return !prev;
    });
  }, [audio]);

  const ttsSetVoice = useCallback((voice: string) => {
    setSelectedVoice(voice);
  }, []);

  // Cleanup TTS on unmount
  useEffect(() => {
    return () => {
      audio.stop();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ==========================================================================
  // Build return value
  // ==========================================================================

  const tts: TTSControls = useMemo(
    () => ({
      state: ttsState,
      play: ttsPlay,
      pause: ttsPause,
      stop: ttsStop,
      setSpeed: ttsSetSpeed,
      setVolume: ttsSetVolume,
      toggleMute: ttsToggleMute,
      speed: ttsSpeed,
      volume: ttsVolume,
      isMuted: ttsMuted,
      speakingMessageIndex,
      availableVoices: DEFAULT_VOICES,
      selectedVoice,
      setVoice: ttsSetVoice,
    }),
    [
      ttsState,
      ttsPlay,
      ttsPause,
      ttsStop,
      ttsSetSpeed,
      ttsSetVolume,
      ttsToggleMute,
      ttsSpeed,
      ttsVolume,
      ttsMuted,
      speakingMessageIndex,
      selectedVoice,
      ttsSetVoice,
    ],
  );

  return {
    messages,
    streamingMessages,
    streamEvents,
    agents,
    task,
    currentPhase,
    isStreaming,
    connectionStatus,
    error,
    streamMetrics: metrics,
    tts,
    reconnect,
  };
}

export default useDebateStream;
