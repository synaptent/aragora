'use client';

import { useState, useRef, useCallback, useEffect } from 'react';

interface VoiceRecorderProps {
  onRecordingComplete: (audioBlob: Blob, duration: number) => void;
  maxDurationSeconds?: number;
  disabled?: boolean;
}

type RecordingState = 'idle' | 'recording' | 'processing';

export function VoiceRecorder({
  onRecordingComplete,
  maxDurationSeconds = 300, // 5 minutes default
  disabled = false,
}: VoiceRecorderProps) {
  const [state, setState] = useState<RecordingState>('idle');
  const [duration, setDuration] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [audioLevel, setAudioLevel] = useState(0);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animationRef = useRef<number | null>(null);
  const stopRecordingRef = useRef<() => void>(() => {});

  // Clean up on unmount
  useEffect(() => {
    return () => {
      stopRecordingRef.current();
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, []);

  // Auto-stop when max duration reached
  useEffect(() => {
    if (state === 'recording' && duration >= maxDurationSeconds) {
      stopRecordingRef.current();
    }
  }, [duration, maxDurationSeconds, state]);

  const startRecording = useCallback(async () => {
    setError(null);
    chunksRef.current = [];

    try {
      // Request microphone access
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      streamRef.current = stream;

      // Set up audio analysis for visualization
      const audioContext = new AudioContext();
      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      analyserRef.current = analyser;

      // Start level monitoring
      const dataArray = new Uint8Array(analyser.frequencyBinCount);
      const updateLevel = () => {
        if (analyserRef.current) {
          analyserRef.current.getByteFrequencyData(dataArray);
          const average = dataArray.reduce((a, b) => a + b) / dataArray.length;
          setAudioLevel(average / 255);
          animationRef.current = requestAnimationFrame(updateLevel);
        }
      };
      updateLevel();

      // Determine supported MIME type
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : MediaRecorder.isTypeSupported('audio/webm')
          ? 'audio/webm'
          : 'audio/mp4';

      const mediaRecorder = new MediaRecorder(stream, { mimeType });
      mediaRecorderRef.current = mediaRecorder;

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = () => {
        setState('processing');
        const audioBlob = new Blob(chunksRef.current, { type: mimeType });
        const finalDuration = duration;

        // Clean up
        if (streamRef.current) {
          streamRef.current.getTracks().forEach((track) => track.stop());
          streamRef.current = null;
        }
        if (animationRef.current) {
          cancelAnimationFrame(animationRef.current);
          animationRef.current = null;
        }
        analyserRef.current = null;
        setAudioLevel(0);

        onRecordingComplete(audioBlob, finalDuration);
        setState('idle');
        setDuration(0);
      };

      mediaRecorder.onerror = () => {
        setError('Recording failed. Please try again.');
        setState('idle');
      };

      // Start recording
      mediaRecorder.start(1000); // Collect data every second
      setState('recording');
      setDuration(0);

      // Start duration timer
      timerRef.current = setInterval(() => {
        setDuration((d) => d + 1);
      }, 1000);
    } catch (err) {
      if (err instanceof Error) {
        if (err.name === 'NotAllowedError') {
          setError('Microphone access denied. Please allow microphone access and try again.');
        } else if (err.name === 'NotFoundError') {
          setError('No microphone found. Please connect a microphone and try again.');
        } else {
          setError(`Failed to start recording: ${err.message}`);
        }
      } else {
        setError('Failed to start recording');
      }
      setState('idle');
    }
  }, [duration, onRecordingComplete]);

  const stopRecording = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }

    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
  }, []);

  // Keep ref in sync for use in effects
  stopRecordingRef.current = stopRecording;

  const formatDuration = (seconds: number): string => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const remainingTime = maxDurationSeconds - duration;
  const isNearLimit = remainingTime <= 30;

  return (
    <div className="flex flex-col items-center gap-3 p-4">
      {/* Audio level visualization */}
      {state === 'recording' && (
        <div className="flex items-center gap-1 h-8">
          {Array.from({ length: 20 }).map((_, i) => (
            <div
              key={i}
              className="w-1 bg-accent rounded-full transition-all duration-75"
              style={{
                height: `${Math.max(4, audioLevel * 32 * (1 + Math.sin(i * 0.5) * 0.3))}px`,
                opacity: i / 20 < audioLevel ? 1 : 0.3,
              }}
            />
          ))}
        </div>
      )}

      {/* Record button */}
      <button
        onClick={state === 'recording' ? stopRecording : startRecording}
        disabled={disabled || state === 'processing'}
        className={`
          w-16 h-16 rounded-full flex items-center justify-center transition-all
          focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-surface
          ${
            state === 'recording'
              ? 'bg-[var(--crimson)] hover:bg-[var(--crimson)]/80 focus:ring-crimson'
              : 'bg-accent hover:bg-accent/80 focus:ring-accent'
          }
          ${disabled || state === 'processing' ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
        `}
        aria-label={state === 'recording' ? 'Stop recording' : 'Start recording'}
      >
        {state === 'processing' ? (
          <svg className="animate-spin h-6 w-6 text-white" viewBox="0 0 24 24">
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
        ) : state === 'recording' ? (
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="currentColor"
            className="w-6 h-6 text-white"
          >
            <rect x="6" y="6" width="12" height="12" rx="2" />
          </svg>
        ) : (
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="currentColor"
            className="w-6 h-6 text-white"
          >
            <path d="M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
            <path d="M19 10v1a7 7 0 0 1-14 0v-1a1 1 0 1 0-2 0v1a9 9 0 0 0 8 8.94V22h-3a1 1 0 1 0 0 2h8a1 1 0 1 0 0-2h-3v-2.06A9 9 0 0 0 21 11v-1a1 1 0 1 0-2 0Z" />
          </svg>
        )}
      </button>

      {/* Status text */}
      <div className="text-center">
        {state === 'idle' && !error && (
          <div className="text-sm text-text-muted">Click to start recording</div>
        )}
        {state === 'recording' && (
          <div className="space-y-1">
            <div
              className={`text-sm font-theme-data ${isNearLimit ? 'text-[var(--crimson)]' : 'text-text'}`}
            >
              {formatDuration(duration)}
              {isNearLimit && (
                <span className="text-text-muted ml-2">({formatDuration(remainingTime)} left)</span>
              )}
            </div>
            <div className="text-xs text-text-muted">Recording... Click to stop</div>
          </div>
        )}
        {state === 'processing' && <div className="text-sm text-text-muted">Processing...</div>}
        {error && <div className="text-sm text-[var(--crimson)]">{error}</div>}
      </div>

      {/* Max duration hint */}
      {state === 'idle' && !error && (
        <div className="text-xs text-text-muted">
          Max {Math.floor(maxDurationSeconds / 60)} minutes
        </div>
      )}
    </div>
  );
}
