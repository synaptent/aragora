'use client';

import { useState, useCallback } from 'react';
import { FileUploader } from './FileUploader';

interface TranscriptionSegment {
  id: number;
  start: number;
  end: number;
  text: string;
}

interface TranscriptionResult {
  text: string;
  segments: TranscriptionSegment[];
  language: string;
  duration: number;
  backend: string;
  model?: string;
  processing_time?: number;
}

interface AudioTranscriberProps {
  onTranscript?: (result: TranscriptionResult) => void;
  onError?: (error: string) => void;
  apiEndpoint?: string;
  className?: string;
}

type TranscriberState = 'idle' | 'uploading' | 'transcribing' | 'completed' | 'error';

const AUDIO_ACCEPT = ['.mp3', '.wav', '.m4a', '.webm', '.ogg', '.flac', '.aac', '.wma'];

const VIDEO_ACCEPT = ['.mp4', '.mov', '.webm', '.mkv', '.avi', '.wmv', '.flv'];

const formatTime = (seconds: number): string => {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 1000);

  if (h > 0) {
    return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  }
  return `${m}:${s.toString().padStart(2, '0')}.${ms.toString().padStart(3, '0').slice(0, 2)}`;
};

/**
 * Audio/Video transcription component
 *
 * Features:
 * - Upload audio or video files
 * - Transcription with timestamps
 * - Export to SRT, VTT, TXT
 * - Progress indicator
 */
export function AudioTranscriber({
  onTranscript,
  onError,
  apiEndpoint = '/api/transcribe',
  className = '',
}: AudioTranscriberProps) {
  const [state, setState] = useState<TranscriberState>('idle');
  const [result, setResult] = useState<TranscriptionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string>('');
  const [showSegments, setShowSegments] = useState(true);

  const handleUpload = useCallback(
    async (files: File[]) => {
      const file = files[0];
      if (!file) return;

      setFileName(file.name);
      setState('uploading');
      setError(null);
      setResult(null);

      try {
        const formData = new FormData();
        formData.append('file', file);

        // Determine endpoint based on file type
        const ext = '.' + file.name.split('.').pop()?.toLowerCase();
        const isVideo = VIDEO_ACCEPT.includes(ext);
        const endpoint = isVideo ? `${apiEndpoint}/video` : `${apiEndpoint}/audio`;

        setState('transcribing');

        const response = await fetch(endpoint, { method: 'POST', body: formData });

        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          throw new Error(data.error || 'Transcription failed');
        }

        const transcription = await response.json();
        setResult(transcription);
        setState('completed');
        onTranscript?.(transcription);
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Transcription failed';
        setError(message);
        setState('error');
        onError?.(message);
      }
    },
    [apiEndpoint, onTranscript, onError],
  );

  const reset = useCallback(() => {
    setState('idle');
    setResult(null);
    setError(null);
    setFileName('');
  }, []);

  const exportTranscript = useCallback(
    (format: 'txt' | 'srt' | 'vtt') => {
      if (!result) return;

      let content = '';
      let mimeType = 'text/plain';
      const extension = format;

      switch (format) {
        case 'txt':
          content = result.text;
          break;

        case 'srt':
          content = result.segments
            .map((seg, i) => {
              const start = formatSrtTime(seg.start);
              const end = formatSrtTime(seg.end);
              return `${i + 1}\n${start} --> ${end}\n${seg.text.trim()}\n`;
            })
            .join('\n');
          mimeType = 'text/plain';
          break;

        case 'vtt':
          content =
            'WEBVTT\n\n' +
            result.segments
              .map((seg) => {
                const start = formatVttTime(seg.start);
                const end = formatVttTime(seg.end);
                return `${start} --> ${end}\n${seg.text.trim()}\n`;
              })
              .join('\n');
          mimeType = 'text/vtt';
          break;
      }

      // Download file
      const blob = new Blob([content], { type: mimeType });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${fileName.replace(/\.[^/.]+$/, '')}.${extension}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    },
    [result, fileName],
  );

  return (
    <div className={`space-y-4 ${className}`}>
      {/* Upload section */}
      {state === 'idle' && (
        <FileUploader
          onUpload={handleUpload}
          accept={[...AUDIO_ACCEPT, ...VIDEO_ACCEPT]}
          maxSize={500 * 1024 * 1024} // 500MB
          maxFiles={1}
          multiple={false}
        >
          <div className="text-3xl mb-2 text-[var(--accent)]/70">~</div>
          <div className="font-theme-data text-sm text-text">UPLOAD AUDIO OR VIDEO FILE</div>
          <div className="text-xs text-text-muted mt-1">Supports MP3, WAV, MP4, MOV, and more</div>
        </FileUploader>
      )}

      {/* Processing indicator */}
      {(state === 'uploading' || state === 'transcribing') && (
        <div className="p-6 border-2 border-dashed border-[var(--acid-cyan)]/50 rounded-lg text-center">
          <div className="animate-spin text-3xl mb-3 text-[var(--acid-cyan)]">*</div>
          <div className="font-theme-data text-sm text-[var(--acid-cyan)]">
            {state === 'uploading' ? 'UPLOADING...' : 'TRANSCRIBING...'}
          </div>
          {fileName && <div className="text-xs text-text-muted mt-1 truncate">{fileName}</div>}
        </div>
      )}

      {/* Error display */}
      {state === 'error' && error && (
        <div className="p-4 bg-[var(--crimson)]/10 border border-[var(--crimson)]/30 rounded-lg">
          <div className="font-theme-data text-sm text-[var(--crimson)] mb-2">
            TRANSCRIPTION FAILED
          </div>
          <div className="text-xs text-[var(--crimson)]/80">{error}</div>
          <button
            onClick={reset}
            aria-label="Try transcription again"
            className="mt-3 px-3 py-1 text-xs font-theme-data border border-[var(--crimson)]/50 text-[var(--crimson)] hover:bg-[var(--crimson)]/10 transition-colors"
          >
            Try Again
          </button>
        </div>
      )}

      {/* Results display */}
      {state === 'completed' && result && (
        <div className="space-y-4">
          {/* Header with stats */}
          <div className="flex items-center justify-between">
            <div>
              <div className="font-theme-data text-sm text-[var(--accent)]">
                TRANSCRIPTION COMPLETE
              </div>
              <div className="text-xs text-text-muted mt-1">
                {formatTime(result.duration)} duration
                {result.processing_time && ` • ${result.processing_time.toFixed(1)}s processing`}
                {result.language && ` • ${result.language.toUpperCase()}`}
              </div>
            </div>
            <button
              onClick={reset}
              aria-label="Start new transcription"
              className="text-xs font-theme-data text-[var(--accent)]/70 hover:text-[var(--accent)]"
            >
              New File
            </button>
          </div>

          {/* Export buttons */}
          <div className="flex gap-2" role="group" aria-label="Export options">
            <button
              onClick={() => exportTranscript('txt')}
              aria-label="Export as plain text"
              className="px-3 py-1.5 text-xs font-theme-data border border-[var(--accent)]/30 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors"
            >
              Export TXT
            </button>
            <button
              onClick={() => exportTranscript('srt')}
              aria-label="Export as SRT subtitles"
              className="px-3 py-1.5 text-xs font-theme-data border border-[var(--accent)]/30 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors"
            >
              Export SRT
            </button>
            <button
              onClick={() => exportTranscript('vtt')}
              aria-label="Export as WebVTT subtitles"
              className="px-3 py-1.5 text-xs font-theme-data border border-[var(--accent)]/30 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors"
            >
              Export VTT
            </button>
          </div>

          {/* Transcript content */}
          <div className="bg-surface border border-[var(--accent)]/20 rounded-lg overflow-hidden">
            {/* Toggle between full text and segments */}
            <div
              className="flex border-b border-[var(--accent)]/20"
              role="tablist"
              aria-label="Transcript view"
            >
              <button
                onClick={() => setShowSegments(false)}
                role="tab"
                aria-selected={!showSegments}
                aria-controls="transcript-content"
                className={`flex-1 px-3 py-2 text-xs font-theme-data ${
                  !showSegments
                    ? 'bg-[var(--accent)]/10 text-[var(--accent)]'
                    : 'text-text-muted hover:text-text'
                }`}
              >
                Full Text
              </button>
              <button
                onClick={() => setShowSegments(true)}
                role="tab"
                aria-selected={showSegments}
                aria-controls="transcript-content"
                className={`flex-1 px-3 py-2 text-xs font-theme-data ${
                  showSegments
                    ? 'bg-[var(--accent)]/10 text-[var(--accent)]'
                    : 'text-text-muted hover:text-text'
                }`}
              >
                With Timestamps
              </button>
            </div>

            <div className="p-4 max-h-96 overflow-y-auto">
              {showSegments ? (
                <div className="space-y-2">
                  {result.segments.map((seg) => (
                    <div key={seg.id} className="flex gap-3 text-sm">
                      <span className="text-[var(--acid-cyan)]/70 font-theme-data text-xs shrink-0 w-20">
                        {formatTime(seg.start)}
                      </span>
                      <span className="text-text">{seg.text}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-text whitespace-pre-wrap">{result.text}</p>
              )}
            </div>
          </div>

          {/* Backend info */}
          <div className="text-xs text-text-muted">
            Transcribed with {result.backend}
            {result.model && ` (${result.model})`}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Format time for SRT format (00:00:00,000)
 */
function formatSrtTime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 1000);

  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')},${ms.toString().padStart(3, '0')}`;
}

/**
 * Format time for VTT format (00:00:00.000)
 */
function formatVttTime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 1000);

  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}.${ms.toString().padStart(3, '0')}`;
}
