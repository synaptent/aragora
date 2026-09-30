'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import { logger } from '@/utils/logger';

interface VoiceInputProps {
  onTranscript: (text: string) => void;
  onInterimResult?: (text: string) => void;
  onRecordingStart?: () => void;
  onRecordingStop?: () => void;
  onError?: (error: string) => void;
  language?: string;
  apiEndpoint?: string;
  disabled?: boolean;
  className?: string;
  showWaveform?: boolean;
}

type RecordingState = 'idle' | 'requesting' | 'recording' | 'processing';

/**
 * Voice input component with speech-to-text transcription
 *
 * Features:
 * - Browser microphone recording
 * - Audio visualization (optional)
 * - Sends audio to backend STT endpoint
 * - Interim results support (if backend supports streaming)
 */
export function VoiceInput({
  onTranscript,
  onRecordingStart,
  onRecordingStop,
  onError,
  language,
  apiEndpoint = '/api/transcribe/audio',
  disabled = false,
  className = '',
  showWaveform = true,
}: VoiceInputProps) {
  const [state, setState] = useState<RecordingState>('idle');
  const [audioLevel, setAudioLevel] = useState(0);
  const [duration, setDuration] = useState(0);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyzerRef = useRef<AnalyserNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const animationRef = useRef<number | null>(null);
  const startTimeRef = useRef<number>(0);
  const durationIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const stopRecordingRef = useRef<() => void>(() => {});
  const processRecordingRef = useRef<() => Promise<void>>(() => Promise.resolve());

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopRecordingRef.current();
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
      if (durationIntervalRef.current) {
        clearInterval(durationIntervalRef.current);
      }
    };
  }, []);

  const updateAudioLevel = useCallback(() => {
    if (!analyzerRef.current) return;

    const dataArray = new Uint8Array(analyzerRef.current.frequencyBinCount);
    analyzerRef.current.getByteFrequencyData(dataArray);

    // Calculate RMS level
    let sum = 0;
    for (let i = 0; i < dataArray.length; i++) {
      sum += dataArray[i] * dataArray[i];
    }
    const rms = Math.sqrt(sum / dataArray.length);
    const normalized = Math.min(100, rms / 2.55); // Normalize to 0-100

    setAudioLevel(normalized);

    if (state === 'recording') {
      animationRef.current = requestAnimationFrame(updateAudioLevel);
    }
  }, [state]);

  const startRecording = useCallback(async () => {
    if (disabled || state !== 'idle') return;

    setState('requesting');
    chunksRef.current = [];

    try {
      // Request microphone access
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });

      streamRef.current = stream;

      // Set up audio analysis for visualization
      if (showWaveform) {
        const audioContext = new AudioContext();
        const source = audioContext.createMediaStreamSource(stream);
        const analyzer = audioContext.createAnalyser();
        analyzer.fftSize = 256;
        source.connect(analyzer);

        audioContextRef.current = audioContext;
        analyzerRef.current = analyzer;
      }

      // Set up MediaRecorder
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm';

      const mediaRecorder = new MediaRecorder(stream, { mimeType });
      mediaRecorderRef.current = mediaRecorder;

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          chunksRef.current.push(e.data);
        }
      };

      mediaRecorder.onstop = async () => {
        setState('processing');
        await processRecordingRef.current();
      };

      mediaRecorder.onerror = (e) => {
        logger.error('MediaRecorder error:', e);
        onError?.('Recording error occurred');
        stopRecordingRef.current();
      };

      // Start recording
      mediaRecorder.start(100); // Collect data every 100ms
      setState('recording');
      startTimeRef.current = Date.now();

      // Start duration timer
      durationIntervalRef.current = setInterval(() => {
        setDuration(Math.floor((Date.now() - startTimeRef.current) / 1000));
      }, 100);

      // Start audio level animation
      if (showWaveform) {
        animationRef.current = requestAnimationFrame(updateAudioLevel);
      }

      onRecordingStart?.();
    } catch (err) {
      logger.error('Failed to start recording:', err);
      setState('idle');

      if (err instanceof DOMException && err.name === 'NotAllowedError') {
        onError?.('Microphone access denied. Please allow microphone access.');
      } else {
        onError?.('Failed to start recording');
      }
    }
  }, [disabled, state, showWaveform, updateAudioLevel, onRecordingStart, onError]);

  const stopRecording = useCallback(() => {
    // Stop duration timer
    if (durationIntervalRef.current) {
      clearInterval(durationIntervalRef.current);
      durationIntervalRef.current = null;
    }

    // Stop animation
    if (animationRef.current) {
      cancelAnimationFrame(animationRef.current);
      animationRef.current = null;
    }

    // Stop MediaRecorder
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }

    // Stop audio tracks
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }

    // Close audio context
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }

    analyzerRef.current = null;
    setAudioLevel(0);
    onRecordingStop?.();
  }, [onRecordingStop]);

  // Keep refs in sync for use in callbacks
  stopRecordingRef.current = stopRecording;

  const processRecording = useCallback(async () => {
    try {
      const audioBlob = new Blob(chunksRef.current, { type: 'audio/webm' });
      chunksRef.current = [];

      // Create form data
      const formData = new FormData();
      formData.append('audio', audioBlob, 'recording.webm');
      if (language) {
        formData.append('language', language);
      }

      // Send to backend
      const response = await fetch(apiEndpoint, { method: 'POST', body: formData });

      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.error || 'Transcription failed');
      }

      const result = await response.json();
      onTranscript(result.text || result.transcript || '');
    } catch (err) {
      logger.error('Transcription error:', err);
      onError?.(err instanceof Error ? err.message : 'Transcription failed');
    } finally {
      setState('idle');
      setDuration(0);
    }
  }, [apiEndpoint, language, onTranscript, onError]);

  processRecordingRef.current = processRecording;

  const toggleRecording = useCallback(() => {
    if (state === 'recording') {
      stopRecording();
    } else if (state === 'idle') {
      startRecording();
    }
  }, [state, startRecording, stopRecording]);

  const formatDuration = (seconds: number): string => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className={`inline-flex items-center gap-2 ${className}`}>
      {/* Main button */}
      <button
        onClick={toggleRecording}
        disabled={disabled || state === 'processing' || state === 'requesting'}
        aria-label={
          state === 'recording'
            ? 'Stop voice recording'
            : state === 'processing'
              ? 'Processing audio transcription'
              : 'Start voice recording'
        }
        aria-pressed={state === 'recording'}
        className={`
          relative w-10 h-10 rounded-full border-2 transition-all
          flex items-center justify-center font-theme-data
          ${
            state === 'recording'
              ? 'border-[var(--crimson)] bg-[var(--crimson)]/20 text-[var(--crimson)] animate-pulse'
              : state === 'processing' || state === 'requesting'
                ? 'border-[var(--acid-cyan)] bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)] cursor-wait'
                : 'border-[var(--accent)]/50 text-[var(--accent)] hover:border-[var(--accent)] hover:bg-[var(--accent)]/10'
          }
          disabled:opacity-50 disabled:cursor-not-allowed
        `}
        title={
          state === 'recording'
            ? 'Stop recording'
            : state === 'processing'
              ? 'Processing...'
              : 'Start recording'
        }
      >
        {state === 'recording' ? (
          <span className="w-3 h-3 bg-[var(--crimson)] rounded-sm" />
        ) : state === 'processing' || state === 'requesting' ? (
          <span className="animate-spin">*</span>
        ) : (
          <MicrophoneIcon />
        )}
      </button>

      {/* Audio level / duration display */}
      {state === 'recording' && (
        <div className="flex items-center gap-2 text-xs font-theme-data">
          {showWaveform && (
            <div className="flex items-end gap-0.5 h-4" aria-hidden="true" role="presentation">
              {Array.from({ length: 5 }).map((_, i) => {
                const threshold = (i + 1) * 20;
                const active = audioLevel >= threshold;
                return (
                  <div
                    key={i}
                    className={`w-1 transition-all duration-75 ${
                      active ? 'bg-[var(--accent)]' : 'bg-[var(--accent)]/30'
                    }`}
                    style={{ height: `${(i + 1) * 20}%` }}
                  />
                );
              })}
            </div>
          )}
          <span className="text-[var(--crimson)]">{formatDuration(duration)}</span>
        </div>
      )}

      {state === 'processing' && (
        <span className="text-xs font-theme-data text-[var(--acid-cyan)]">Processing...</span>
      )}
    </div>
  );
}

/**
 * Simple microphone icon
 */
function MicrophoneIcon() {
  return (
    <svg
      className="w-5 h-5"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
      aria-hidden="true"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"
      />
    </svg>
  );
}

/**
 * Expanded voice input with more controls
 */
export function VoiceInputExpanded({
  onTranscript,
  onError,
  language,
  apiEndpoint = '/api/transcribe/audio',
  disabled = false,
  className = '',
}: Omit<VoiceInputProps, 'showWaveform' | 'onInterimResult'>) {
  const [transcript, setTranscript] = useState('');

  const handleTranscript = useCallback(
    (text: string) => {
      setTranscript(text);
      onTranscript(text);
    },
    [onTranscript],
  );

  return (
    <div className={`space-y-3 ${className}`}>
      <div className="flex items-center gap-3">
        <VoiceInput
          onTranscript={handleTranscript}
          onError={onError}
          language={language}
          apiEndpoint={apiEndpoint}
          disabled={disabled}
          showWaveform
        />
        <span className="text-xs text-text-muted font-theme-data">
          Click to record, click again to stop
        </span>
      </div>

      {transcript && (
        <div className="p-3 bg-surface border border-[var(--accent)]/20 rounded text-sm font-theme-data">
          <div className="text-xs text-[var(--accent)]/70 mb-1">TRANSCRIPT:</div>
          <div className="text-text">{transcript}</div>
        </div>
      )}
    </div>
  );
}
