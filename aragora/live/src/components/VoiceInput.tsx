'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import { logger } from '@/utils/logger';

interface VoiceInputProps {
  debateId: string;
  onTranscript?: (text: string, isFinal: boolean) => void;
  onError?: (error: string) => void;
  apiBase?: string;
  disabled?: boolean;
  /** Optional callback to send transcript as debate suggestion */
  sendSuggestion?: (suggestion: string) => void;
  /** Auto-submit final transcripts as suggestions (requires sendSuggestion) */
  autoSubmitSuggestion?: boolean;
  /** Enable TTS playback for agent responses */
  enableTTS?: boolean;
  /** Callback when TTS audio starts playing */
  onTTSStart?: (agent: string) => void;
  /** Callback when TTS audio finishes playing */
  onTTSEnd?: (agent: string) => void;
}

type VoiceStatus = 'idle' | 'connecting' | 'recording' | 'processing' | 'error';
type TTSStatus = 'idle' | 'receiving' | 'playing';

interface TranscriptSegment {
  text: string;
  timestamp: number;
  isFinal: boolean;
}

export function VoiceInput({
  debateId,
  onTranscript,
  onError,
  apiBase = '',
  disabled = false,
  sendSuggestion,
  autoSubmitSuggestion = false,
  enableTTS = true,
  onTTSStart,
  onTTSEnd,
}: VoiceInputProps) {
  const [status, setStatus] = useState<VoiceStatus>('idle');
  const [transcript, setTranscript] = useState<TranscriptSegment[]>([]);
  const [currentText, setCurrentText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [duration, setDuration] = useState(0);

  // TTS playback state
  const [ttsStatus, setTtsStatus] = useState<TTSStatus>('idle');
  const [ttsAvailable, setTtsAvailable] = useState(false);
  const [currentAgent, setCurrentAgent] = useState<string>('');

  const wsRef = useRef<WebSocket | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const startTimeRef = useRef<number>(0);
  const durationIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const statusRef = useRef<VoiceStatus>(status);
  const stopRecordingRef = useRef<() => void>(() => {});
  const handleErrorRef = useRef<(message: string) => void>(() => {});
  const handleServerMessageRef = useRef<(data: Record<string, unknown>) => void>(() => {});
  const handleBinaryMessageRef = useRef<(data: ArrayBuffer) => void>(() => {});
  const startAudioCaptureRef = useRef<() => void>(() => {});
  const startDurationTimerRef = useRef<() => void>(() => {});

  // TTS audio playback refs
  const audioElementRef = useRef<HTMLAudioElement | null>(null);
  const audioChunksRef = useRef<Uint8Array[]>([]);
  const audioFormatRef = useRef<string>('mp3');

  // Keep statusRef in sync
  useEffect(() => {
    statusRef.current = status;
  }, [status]);

  // Build WebSocket URL
  const getWsUrl = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = apiBase ? new URL(apiBase).host : window.location.host;
    return `${protocol}//${host}/ws/voice/${debateId}`;
  }, [apiBase, debateId]);

  // Start recording
  const startRecording = useCallback(async () => {
    if (disabled || status === 'recording') return;

    setError(null);
    setStatus('connecting');

    try {
      // Request microphone access
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
      mediaStreamRef.current = stream;

      // Connect to WebSocket
      const ws = new WebSocket(getWsUrl());
      wsRef.current = ws;

      ws.onopen = () => {
        // Send config
        ws.send(
          JSON.stringify({
            type: 'config',
            format: 'pcm',
            sample_rate: 16000,
            channels: 1,
            bits_per_sample: 16,
          }),
        );
      };

      ws.onmessage = (event) => {
        // Handle binary data (TTS audio chunks)
        if (event.data instanceof ArrayBuffer) {
          handleBinaryMessageRef.current(event.data);
          return;
        }
        if (event.data instanceof Blob) {
          event.data.arrayBuffer().then((buffer) => {
            handleBinaryMessageRef.current(buffer);
          });
          return;
        }

        // Handle JSON messages
        try {
          const data = JSON.parse(event.data);
          handleServerMessageRef.current(data);
        } catch {
          logger.error('Failed to parse WebSocket message:', event.data);
        }
      };

      ws.onerror = (event) => {
        logger.error('WebSocket error:', event);
        handleErrorRef.current('Connection error');
      };

      ws.onclose = () => {
        if (statusRef.current === 'recording') {
          stopRecordingRef.current();
        }
      };
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to access microphone';
      handleErrorRef.current(message);
    }
  }, [disabled, status, getWsUrl]);

  // Handle server messages
  const handleServerMessage = useCallback(
    (data: Record<string, unknown>) => {
      switch (data.type) {
        case 'ready':
          setSessionId(data.session_id as string);
          setStatus('recording');
          startTimeRef.current = Date.now();
          startAudioCaptureRef.current();
          startDurationTimerRef.current();
          // Check TTS availability from config
          const config = data.config as Record<string, unknown> | undefined;
          if (config) {
            setTtsAvailable(Boolean(config.tts_available));
          }
          break;

        case 'transcript':
          const text = data.text as string;
          const isFinal = data.is_final as boolean;

          if (isFinal) {
            setTranscript((prev) => [...prev, { text, timestamp: Date.now(), isFinal: true }]);
            setCurrentText('');

            // Auto-submit as debate suggestion if enabled
            if (autoSubmitSuggestion && sendSuggestion && text.trim()) {
              sendSuggestion(text.trim());
            }
          } else {
            setCurrentText(text);
          }

          onTranscript?.(text, isFinal);
          break;

        // TTS messages
        case 'tts_start':
          setTtsStatus('receiving');
          setCurrentAgent((data.agent as string) || '');
          onTTSStart?.((data.agent as string) || '');
          break;

        case 'tts_audio_start':
          audioChunksRef.current = [];
          audioFormatRef.current = (data.format as string) || 'mp3';
          break;

        case 'tts_audio_end':
          // All chunks received, play the audio
          playAudio();
          break;

        case 'error':
          handleErrorRef.current((data.message as string) || 'Unknown error');
          break;

        case 'warning':
          logger.warn('Voice warning:', data.message);
          break;
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [onTranscript, autoSubmitSuggestion, sendSuggestion, onTTSStart],
  );

  // Handle binary TTS audio chunks
  const handleBinaryMessage = useCallback(
    (data: ArrayBuffer) => {
      if (ttsStatus === 'receiving' || audioChunksRef.current.length > 0) {
        audioChunksRef.current.push(new Uint8Array(data));
      }
    },
    [ttsStatus],
  );

  // Play accumulated TTS audio
  const playAudio = useCallback(() => {
    if (audioChunksRef.current.length === 0) return;

    // Combine all chunks into a single Uint8Array
    const totalLength = audioChunksRef.current.reduce((acc, chunk) => acc + chunk.length, 0);
    const combined = new Uint8Array(totalLength);
    let offset = 0;
    for (const chunk of audioChunksRef.current) {
      combined.set(chunk, offset);
      offset += chunk.length;
    }

    // Create blob and URL
    const mimeType = audioFormatRef.current === 'wav' ? 'audio/wav' : 'audio/mpeg';
    const blob = new Blob([combined], { type: mimeType });
    const url = URL.createObjectURL(blob);

    // Create audio element if needed
    if (!audioElementRef.current) {
      audioElementRef.current = new Audio();
    }

    const audio = audioElementRef.current;
    audio.src = url;
    setTtsStatus('playing');

    audio.onended = () => {
      setTtsStatus('idle');
      onTTSEnd?.(currentAgent);
      URL.revokeObjectURL(url);
      audioChunksRef.current = [];
    };

    audio.onerror = () => {
      logger.error('Error playing TTS audio');
      setTtsStatus('idle');
      URL.revokeObjectURL(url);
      audioChunksRef.current = [];
    };

    audio.play().catch((err) => {
      logger.error('Failed to play TTS audio:', err);
      setTtsStatus('idle');
    });
  }, [currentAgent, onTTSEnd]);

  // Handle errors
  const handleError = useCallback(
    (message: string) => {
      setError(message);
      setStatus('error');
      onError?.(message);
      stopRecordingRef.current();
    },
    [onError],
  );

  // Start audio capture using Web Audio API
  const startAudioCapture = useCallback(() => {
    if (!mediaStreamRef.current) return;

    try {
      const audioContext = new AudioContext({ sampleRate: 16000 });
      audioContextRef.current = audioContext;

      const source = audioContext.createMediaStreamSource(mediaStreamRef.current);

      // Use ScriptProcessorNode for audio processing
      // Note: This is deprecated but widely supported. AudioWorklet is the modern alternative.
      const processor = audioContext.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;

      processor.onaudioprocess = (event) => {
        if (wsRef.current?.readyState !== WebSocket.OPEN) return;

        const inputData = event.inputBuffer.getChannelData(0);

        // Convert Float32 samples to Int16
        const int16Data = new Int16Array(inputData.length);
        for (let i = 0; i < inputData.length; i++) {
          const s = Math.max(-1, Math.min(1, inputData[i]));
          int16Data[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }

        // Send as binary
        wsRef.current.send(int16Data.buffer);
      };

      source.connect(processor);
      processor.connect(audioContext.destination);
    } catch (err) {
      logger.error('Audio capture error:', err);
      handleErrorRef.current('Failed to capture audio');
    }
  }, []);

  // Start duration timer
  const startDurationTimer = useCallback(() => {
    durationIntervalRef.current = setInterval(() => {
      setDuration(Math.floor((Date.now() - startTimeRef.current) / 1000));
    }, 1000);
  }, []);

  // Stop recording
  const stopRecording = useCallback(() => {
    // Stop duration timer
    if (durationIntervalRef.current) {
      clearInterval(durationIntervalRef.current);
      durationIntervalRef.current = null;
    }

    // Stop audio processing
    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current = null;
    }

    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }

    // Stop media stream
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }

    // Close WebSocket
    if (wsRef.current) {
      if (wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'end' }));
      }
      wsRef.current.close();
      wsRef.current = null;
    }

    setStatus('idle');
    setSessionId(null);
  }, []);

  // Keep refs in sync for use in callbacks
  stopRecordingRef.current = stopRecording;
  handleErrorRef.current = handleError;
  handleServerMessageRef.current = handleServerMessage;
  handleBinaryMessageRef.current = handleBinaryMessage;
  startAudioCaptureRef.current = startAudioCapture;
  startDurationTimerRef.current = startDurationTimer;

  // Clean up on unmount
  useEffect(() => {
    return () => {
      stopRecordingRef.current();
    };
  }, []);

  // Format duration
  const formatDuration = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  // Get full transcript text
  const getFullTranscript = () => {
    return transcript.map((s) => s.text).join(' ');
  };

  return (
    <div className="panel" style={{ padding: 0 }}>
      <div className="p-4 border-b border-border">
        <h3 className="panel-title-sm flex items-center gap-2">
          <span>Voice Input</span>
          {status === 'recording' && (
            <span className="flex items-center gap-1 text-[var(--crimson)] text-xs">
              <span className="w-2 h-2 bg-[var(--crimson)] rounded-full animate-pulse" />
              {formatDuration(duration)}
            </span>
          )}
          {ttsStatus === 'playing' && (
            <span className="flex items-center gap-1 text-[var(--accent)] text-xs">
              <svg className="w-3 h-3 animate-pulse" viewBox="0 0 24 24" fill="currentColor">
                <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z" />
              </svg>
              Playing{currentAgent ? `: ${currentAgent}` : ''}
            </span>
          )}
          {ttsStatus === 'receiving' && (
            <span className="flex items-center gap-1 text-amber text-xs">
              <span className="w-2 h-2 bg-amber rounded-full animate-pulse" />
              Receiving audio...
            </span>
          )}
        </h3>
      </div>

      <div className="p-4 space-y-4">
        {/* Control buttons */}
        <div className="flex items-center gap-3">
          {status === 'idle' || status === 'error' ? (
            <button
              onClick={startRecording}
              disabled={disabled}
              className={`
                flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-all
                ${
                  disabled
                    ? 'bg-surface text-text-muted cursor-not-allowed'
                    : 'bg-accent hover:bg-accent/80 text-white'
                }
              `}
              aria-label="Start recording"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
                strokeWidth={1.5}
                stroke="currentColor"
                className="w-5 h-5"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M12 18.75a6 6 0 006-6v-1.5m-6 7.5a6 6 0 01-6-6v-1.5m6 7.5v3.75m-3.75 0h7.5M12 15.75a3 3 0 01-3-3V4.5a3 3 0 116 0v8.25a3 3 0 01-3 3z"
                />
              </svg>
              Start Recording
            </button>
          ) : status === 'connecting' ? (
            <button
              disabled
              className="flex items-center gap-2 px-4 py-2 rounded-lg font-medium bg-surface text-text-muted"
            >
              <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
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
              Connecting...
            </button>
          ) : (
            <button
              onClick={stopRecording}
              className="flex items-center gap-2 px-4 py-2 rounded-lg font-medium bg-[var(--crimson)] hover:bg-[var(--crimson)]/80 text-white transition-all"
              aria-label="Stop recording"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
                strokeWidth={1.5}
                stroke="currentColor"
                className="w-5 h-5"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M5.25 7.5A2.25 2.25 0 017.5 5.25h9a2.25 2.25 0 012.25 2.25v9a2.25 2.25 0 01-2.25 2.25h-9a2.25 2.25 0 01-2.25-2.25v-9z"
                />
              </svg>
              Stop Recording
            </button>
          )}

          {transcript.length > 0 && (
            <button
              onClick={() => {
                setTranscript([]);
                setCurrentText('');
              }}
              className="text-sm text-text-muted hover:text-text transition-colors"
            >
              Clear
            </button>
          )}
        </div>

        {/* Error message */}
        {error && (
          <div className="bg-[var(--crimson)]/10 border border-[var(--crimson)]/30 rounded p-3 text-sm text-[var(--crimson)]">
            {error}
          </div>
        )}

        {/* Real-time transcript display */}
        {(transcript.length > 0 || currentText) && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <div className="text-xs text-text-muted uppercase tracking-wider">Transcript</div>
              {autoSubmitSuggestion && sendSuggestion && (
                <div className="text-xs text-[var(--accent)]">Auto-submitting to debate</div>
              )}
            </div>
            <div className="bg-surface border border-border rounded p-3 max-h-48 overflow-y-auto">
              <p className="text-sm leading-relaxed">
                {getFullTranscript()}
                {currentText && (
                  <span className="text-text-muted animate-pulse"> {currentText}</span>
                )}
              </p>
            </div>
            <div className="flex items-center justify-between">
              <div className="text-xs text-text-muted">
                {transcript.length} segment{transcript.length !== 1 ? 's' : ''} transcribed
              </div>
              {/* Manual submit button (when auto-submit is disabled) */}
              {!autoSubmitSuggestion && sendSuggestion && getFullTranscript().trim() && (
                <button
                  onClick={() => {
                    const fullText = getFullTranscript().trim();
                    if (fullText) {
                      sendSuggestion(fullText);
                      setTranscript([]);
                      setCurrentText('');
                    }
                  }}
                  className="text-xs px-3 py-1 bg-accent hover:bg-accent/80 text-white rounded transition-colors"
                >
                  Submit to Debate
                </button>
              )}
            </div>
          </div>
        )}

        {/* Instructions */}
        {status === 'idle' && transcript.length === 0 && (
          <div className="text-sm text-text-muted">
            <p>Click &quot;Start Recording&quot; to speak your argument.</p>
            <p className="mt-1 text-xs">
              Your speech will be transcribed in real-time and can be added to the debate.
            </p>
          </div>
        )}

        {/* TTS Status */}
        {enableTTS && sessionId && (
          <div className="flex items-center justify-between pt-2 border-t border-border">
            <div className="flex items-center gap-2 text-xs text-text-muted">
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
                <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z" />
              </svg>
              {ttsAvailable ? (
                <span className="text-[var(--accent)]">Voice responses enabled</span>
              ) : (
                <span>Voice responses unavailable</span>
              )}
            </div>
            {ttsStatus === 'playing' && audioElementRef.current && (
              <button
                onClick={() => {
                  audioElementRef.current?.pause();
                  setTtsStatus('idle');
                  onTTSEnd?.(currentAgent);
                }}
                className="text-xs px-2 py-1 bg-surface hover:bg-border rounded transition-colors"
              >
                Stop Playback
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
