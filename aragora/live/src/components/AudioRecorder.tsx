'use client';

import { useState, useRef, useCallback, useEffect } from 'react';

interface AudioRecorderProps {
  onRecordingComplete: (blob: Blob, duration: number) => void;
  onError?: (error: string) => void;
  maxDuration?: number; // in seconds
  className?: string;
}

export function AudioRecorder({
  onRecordingComplete,
  onError,
  maxDuration = 300, // 5 minutes default
  className = '',
}: AudioRecorderProps) {
  const [isRecording, setIsRecording] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [duration, setDuration] = useState(0);
  const [audioLevel, setAudioLevel] = useState(0);
  const [hasPermission, setHasPermission] = useState<boolean | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const startTimeRef = useRef<number>(0);
  const stopRecordingRef = useRef<() => void>(() => {});

  // Check for microphone permission
  useEffect(() => {
    const checkPermission = async () => {
      try {
        const result = await navigator.permissions.query({ name: 'microphone' as PermissionName });
        setHasPermission(result.state === 'granted');

        result.addEventListener('change', () => {
          setHasPermission(result.state === 'granted');
        });
      } catch {
        // Permission API not supported, we'll check when recording starts
        setHasPermission(null);
      }
    };

    checkPermission();
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current);
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track) => track.stop());
      }
    };
  }, []);

  const updateAudioLevel = useCallback(() => {
    if (!analyserRef.current) return;

    const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount);
    analyserRef.current.getByteFrequencyData(dataArray);

    // Calculate average level
    const average = dataArray.reduce((a, b) => a + b) / dataArray.length;
    setAudioLevel(average / 255);

    if (isRecording && !isPaused) {
      animationFrameRef.current = requestAnimationFrame(updateAudioLevel);
    }
  }, [isRecording, isPaused]);

  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      setHasPermission(true);

      // Set up audio analyser for level visualization
      const audioContext = new AudioContext();
      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      analyserRef.current = analyser;

      // Create media recorder
      const mediaRecorder = new MediaRecorder(stream, {
        mimeType: MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : 'audio/mp4',
      });
      mediaRecorderRef.current = mediaRecorder;
      chunksRef.current = [];

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          chunksRef.current.push(e.data);
        }
      };

      mediaRecorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: mediaRecorder.mimeType });
        const recordingDuration = (Date.now() - startTimeRef.current) / 1000;
        onRecordingComplete(blob, recordingDuration);

        // Cleanup
        stream.getTracks().forEach((track) => track.stop());
        if (animationFrameRef.current) {
          cancelAnimationFrame(animationFrameRef.current);
        }
      };

      mediaRecorder.start(1000); // Collect data every second
      startTimeRef.current = Date.now();
      setIsRecording(true);
      setIsPaused(false);
      setDuration(0);

      // Start duration timer
      timerRef.current = setInterval(() => {
        setDuration((prev) => {
          const newDuration = prev + 1;
          if (newDuration >= maxDuration) {
            stopRecordingRef.current();
          }
          return newDuration;
        });
      }, 1000);

      // Start audio level visualization
      updateAudioLevel();
    } catch (err) {
      const error = err instanceof Error ? err.message : 'Failed to access microphone';
      setHasPermission(false);
      onError?.(error);
    }
  }, [maxDuration, onRecordingComplete, onError, updateAudioLevel]);

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
    if (timerRef.current) {
      clearInterval(timerRef.current);
    }
    setIsRecording(false);
    setIsPaused(false);
    setAudioLevel(0);
  }, []);

  // Keep ref in sync for use in callbacks
  stopRecordingRef.current = stopRecording;

  const pauseRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      mediaRecorderRef.current.pause();
      setIsPaused(true);
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
    }
  }, []);

  const resumeRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'paused') {
      mediaRecorderRef.current.resume();
      setIsPaused(false);

      timerRef.current = setInterval(() => {
        setDuration((prev) => {
          const newDuration = prev + 1;
          if (newDuration >= maxDuration) {
            stopRecordingRef.current();
          }
          return newDuration;
        });
      }, 1000);

      updateAudioLevel();
    }
  }, [maxDuration, updateAudioLevel]);

  const formatTime = (seconds: number): string => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  // Permission denied state
  if (hasPermission === false) {
    return (
      <div className={`p-4 border border-warning/30 bg-warning/5 ${className}`}>
        <p className="text-warning font-theme-data text-xs mb-2">Microphone access denied</p>
        <p className="text-text-muted font-theme-data text-[10px]">
          Please enable microphone permissions in your browser settings to record audio.
        </p>
      </div>
    );
  }

  return (
    <div className={`p-4 border border-[var(--accent)]/30 bg-surface/50 ${className}`}>
      {/* Audio level indicator */}
      {isRecording && (
        <div className="mb-4">
          <div className="h-2 bg-bg rounded overflow-hidden">
            <div
              className={`h-full transition-all duration-75 ${
                isPaused ? 'bg-acid-yellow/50' : 'bg-[var(--accent)]'
              }`}
              style={{ width: `${Math.min(audioLevel * 100, 100)}%` }}
            />
          </div>
        </div>
      )}

      {/* Duration display */}
      <div className="text-center mb-4">
        <span
          className={`font-theme-data text-2xl ${isRecording ? 'text-[var(--accent)]' : 'text-text-muted'}`}
        >
          {formatTime(duration)}
        </span>
        {isRecording && (
          <span className="text-text-muted font-theme-data text-xs ml-2">
            / {formatTime(maxDuration)}
          </span>
        )}
      </div>

      {/* Controls */}
      <div className="flex justify-center gap-3">
        {!isRecording ? (
          <button
            onClick={startRecording}
            className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/50 text-[var(--accent)] font-theme-data text-sm hover:bg-[var(--accent)]/30 transition-colors flex items-center gap-2"
          >
            <span className="w-3 h-3 rounded-full bg-warning animate-pulse" />
            START RECORDING
          </button>
        ) : (
          <>
            {isPaused ? (
              <button
                onClick={resumeRecording}
                className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/50 text-[var(--accent)] font-theme-data text-sm hover:bg-[var(--accent)]/30 transition-colors"
              >
                RESUME
              </button>
            ) : (
              <button
                onClick={pauseRecording}
                className="px-4 py-2 bg-acid-yellow/20 border border-acid-yellow/50 text-[var(--acid-yellow)] font-theme-data text-sm hover:bg-acid-yellow/30 transition-colors"
              >
                PAUSE
              </button>
            )}
            <button
              onClick={stopRecording}
              className="px-4 py-2 bg-warning/20 border border-warning/50 text-warning font-theme-data text-sm hover:bg-warning/30 transition-colors"
            >
              STOP
            </button>
          </>
        )}
      </div>

      {/* Status */}
      {isRecording && (
        <p className="text-center mt-3 text-[10px] font-theme-data text-text-muted/60">
          {isPaused ? 'Recording paused' : 'Recording in progress...'}
        </p>
      )}
    </div>
  );
}
