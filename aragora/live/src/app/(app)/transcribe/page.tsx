'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
import Link from 'next/link';
import { API_BASE_URL } from '@/config';
import { usePWA } from '@/hooks/usePWA';
import { YouTubeInput } from '@/components/YouTubeInput';
import { logger } from '@/utils/logger';

type TranscribeState = 'idle' | 'uploading' | 'processing' | 'complete' | 'error';
type InputMode = 'file' | 'youtube' | 'url';

interface TranscriptionResult {
  text: string;
  duration?: number;
  language?: string;
  backend?: string;
  processing_time?: number;
  segments?: Array<{ start: number; end: number; text: string }>;
}

interface TranscriptionConfig {
  available: boolean;
  error?: string;
  backends?: string[];
  audio_formats?: string[];
  video_formats?: string[];
  max_audio_size_mb?: number;
  max_video_size_mb?: number;
  models?: string[];
  youtube_enabled?: boolean;
}

interface YouTubeVideoInfo {
  video_id: string;
  title: string;
  duration: number;
  channel: string;
  thumbnail_url?: string;
}

const ACCEPTED_FORMATS = [
  'audio/mpeg',
  'audio/mp3',
  'audio/wav',
  'audio/webm',
  'audio/ogg',
  'audio/m4a',
  'audio/flac',
  'audio/aac',
  'video/mp4',
  'video/webm',
  'video/quicktime',
  'video/x-msvideo',
];

const FORMAT_LABELS: Record<string, string> = {
  'audio/mpeg': 'MP3',
  'audio/mp3': 'MP3',
  'audio/wav': 'WAV',
  'audio/webm': 'WebM',
  'audio/ogg': 'OGG',
  'audio/m4a': 'M4A',
  'audio/flac': 'FLAC',
  'audio/aac': 'AAC',
  'video/mp4': 'MP4',
  'video/webm': 'WebM',
  'video/quicktime': 'MOV',
  'video/x-msvideo': 'AVI',
};

export default function TranscribePage() {
  const { isOffline } = usePWA();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [config, setConfig] = useState<TranscriptionConfig | null>(null);
  const [inputMode, setInputMode] = useState<InputMode>('file');
  const [state, setState] = useState<TranscribeState>('idle');
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [result, setResult] = useState<TranscriptionResult | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [selectedBackend, setSelectedBackend] = useState<string>('');
  const [selectedLanguage, setSelectedLanguage] = useState<string>('');

  // Fetch config on mount
  useEffect(() => {
    const fetchConfig = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/transcription/config`);
        if (res.ok) {
          const data = await res.json();
          setConfig(data);
          // Set default backend if available
          if (data.backends?.length > 0) {
            setSelectedBackend(data.backends[0]);
          }
        }
      } catch (err) {
        logger.error('Failed to fetch transcription config:', err);
      }
    };
    fetchConfig();
  }, []);

  const handleFileSelect = useCallback(
    (file: File) => {
      if (!ACCEPTED_FORMATS.includes(file.type)) {
        setError(`Unsupported format. Accepted: MP3, WAV, M4A, FLAC, MP4, WebM, MOV`);
        return;
      }

      const maxSize = config?.max_video_size_mb || 100;
      if (file.size > maxSize * 1024 * 1024) {
        setError(`File too large. Maximum size is ${maxSize}MB.`);
        return;
      }

      setSelectedFile(file);
      setError(null);
      setResult(null);
    },
    [config],
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);

      const files = e.dataTransfer.files;
      if (files.length > 0) {
        handleFileSelect(files[0]);
      }
    },
    [handleFileSelect],
  );

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files;
      if (files && files.length > 0) {
        handleFileSelect(files[0]);
      }
    },
    [handleFileSelect],
  );

  const transcribeFile = useCallback(async () => {
    if (!selectedFile) return;

    setState('uploading');
    setProgress(0);
    setError(null);

    try {
      const formData = new FormData();
      formData.append('file', selectedFile);
      if (selectedLanguage) formData.append('language', selectedLanguage);
      if (selectedBackend) formData.append('backend', selectedBackend);

      const isVideo = selectedFile.type.startsWith('video/');
      const endpoint = isVideo ? '/api/transcription/video' : '/api/transcription/audio';

      // Use XMLHttpRequest for progress tracking
      const xhr = new XMLHttpRequest();

      const result = await new Promise<TranscriptionResult>((resolve, reject) => {
        xhr.upload.addEventListener('progress', (e) => {
          if (e.lengthComputable) {
            const uploadProgress = Math.round((e.loaded / e.total) * 50);
            setProgress(uploadProgress);
          }
        });

        xhr.addEventListener('load', () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            try {
              const data = JSON.parse(xhr.responseText);
              resolve(data);
            } catch {
              reject(new Error('Invalid response'));
            }
          } else {
            try {
              const error = JSON.parse(xhr.responseText);
              reject(new Error(error.error || 'Transcription failed'));
            } catch {
              reject(new Error('Transcription failed'));
            }
          }
        });

        xhr.addEventListener('error', () => reject(new Error('Network error')));
        xhr.addEventListener('abort', () => reject(new Error('Cancelled')));

        xhr.open('POST', `${API_BASE_URL}${endpoint}`);
        xhr.send(formData);

        setState('processing');
        // Simulate processing progress
        const interval = setInterval(() => {
          setProgress((p) => Math.min(p + 5, 95));
        }, 500);

        xhr.addEventListener('load', () => clearInterval(interval));
        xhr.addEventListener('error', () => clearInterval(interval));
      });

      setProgress(100);
      setResult(result);
      setState('complete');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Transcription failed');
      setState('error');
    }
  }, [selectedFile, selectedBackend, selectedLanguage]);

  const handleYouTubeSubmit = useCallback(
    async (url: string, _videoInfo: YouTubeVideoInfo) => {
      setState('processing');
      setProgress(0);
      setError(null);

      try {
        // Start progress simulation
        const interval = setInterval(() => {
          setProgress((p) => Math.min(p + 2, 95));
        }, 500);

        const res = await fetch(`${API_BASE_URL}/api/transcription/youtube`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            url,
            language: selectedLanguage || undefined,
            backend: selectedBackend || undefined,
            use_cache: true,
          }),
        });

        clearInterval(interval);

        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.error || 'YouTube transcription failed');
        }

        const data = await res.json();
        setProgress(100);
        setResult({
          text: data.text,
          duration: data.duration,
          language: data.language,
          backend: data.backend,
          processing_time: data.processing_time,
          segments: data.segments,
        });
        setState('complete');
      } catch (err) {
        setError(err instanceof Error ? err.message : 'YouTube transcription failed');
        setState('error');
      }
    },
    [selectedBackend, selectedLanguage],
  );

  const copyToClipboard = useCallback(() => {
    if (result?.text) {
      navigator.clipboard.writeText(result.text);
    }
  }, [result]);

  const downloadTranscript = useCallback(
    (format: 'txt' | 'srt' | 'vtt') => {
      if (!result) return;

      let content = '';
      const filename = `transcript.${format}`;
      let mimeType = 'text/plain';

      if (format === 'txt') {
        content = result.text;
      } else if (format === 'srt' && result.segments) {
        content = result.segments
          .map((seg, i) => {
            const start = formatTimestamp(seg.start, true);
            const end = formatTimestamp(seg.end, true);
            return `${i + 1}\n${start} --> ${end}\n${seg.text}\n`;
          })
          .join('\n');
        mimeType = 'text/srt';
      } else if (format === 'vtt' && result.segments) {
        content =
          'WEBVTT\n\n' +
          result.segments
            .map((seg) => {
              const start = formatTimestamp(seg.start, false);
              const end = formatTimestamp(seg.end, false);
              return `${start} --> ${end}\n${seg.text}\n`;
            })
            .join('\n');
        mimeType = 'text/vtt';
      }

      const blob = new Blob([content], { type: mimeType });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    },
    [result],
  );

  const formatTimestamp = (seconds: number, srtFormat: boolean): string => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    const ms = Math.round((seconds % 1) * 1000);

    if (srtFormat) {
      return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')},${ms.toString().padStart(3, '0')}`;
    }
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}.${ms.toString().padStart(3, '0')}`;
  };

  const formatDuration = (seconds: number): string => {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const reset = useCallback(() => {
    setSelectedFile(null);
    setResult(null);
    setError(null);
    setState('idle');
    setProgress(0);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  }, []);

  return (
    <main className="min-h-screen bg-bg flex flex-col">
      {/* Header */}
      <header className="border-b border-border p-4">
        <div className="flex items-center justify-between">
          <Link href="/" className="text-[var(--accent)] font-theme-data font-bold">
            ARAGORA
          </Link>
          <div className="flex items-center gap-4">
            <Link href="/voice" className="text-xs font-theme-data text-text-muted hover:text-text">
              [VOICE INPUT]
            </Link>
            <Link
              href="/speech"
              className="text-xs font-theme-data text-text-muted hover:text-text"
            >
              [TEXT-TO-SPEECH]
            </Link>
          </div>
        </div>
      </header>

      {/* Offline Warning */}
      {isOffline && (
        <div className="bg-warning/20 border-b border-warning/30 px-4 py-2 text-center">
          <span className="text-warning text-sm font-theme-data">
            Transcription requires internet connection
          </span>
        </div>
      )}

      {/* Config Error */}
      {config && !config.available && (
        <div className="bg-warning/20 border-b border-warning/30 px-4 py-2 text-center">
          <span className="text-warning text-sm font-theme-data">
            {config.error || 'Transcription service not available'}
          </span>
        </div>
      )}

      {/* Main Content */}
      <div className="flex-1 flex flex-col items-center justify-center p-6">
        <div className="w-full max-w-xl space-y-6">
          <div className="text-center">
            <h1 className="text-2xl font-theme-data font-bold text-text mb-2">
              Transcribe Audio & Video
            </h1>
            <p className="text-text-muted text-sm">Upload a file or paste a YouTube URL</p>
          </div>

          {/* Input Mode Selector */}
          {state === 'idle' && !result && (
            <div className="flex gap-2 justify-center">
              <button
                onClick={() => setInputMode('file')}
                className={`px-4 py-2 font-theme-data text-sm border transition-colors ${
                  inputMode === 'file'
                    ? 'border-[var(--accent)] text-[var(--accent)] bg-[var(--accent)]/10'
                    : 'border-border text-text-muted hover:border-text-muted'
                }`}
              >
                File Upload
              </button>
              <button
                onClick={() => setInputMode('youtube')}
                disabled={!config?.youtube_enabled}
                className={`px-4 py-2 font-theme-data text-sm border transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                  inputMode === 'youtube'
                    ? 'border-[var(--accent)] text-[var(--accent)] bg-[var(--accent)]/10'
                    : 'border-border text-text-muted hover:border-text-muted'
                }`}
              >
                YouTube URL
              </button>
            </div>
          )}

          {/* Backend & Language Selection */}
          {state === 'idle' && !result && config?.backends && config.backends.length > 1 && (
            <div className="flex gap-4 justify-center">
              <div className="flex items-center gap-2">
                <label className="text-xs text-text-muted font-theme-data">Backend:</label>
                <select
                  value={selectedBackend}
                  onChange={(e) => setSelectedBackend(e.target.value)}
                  className="bg-surface border border-border text-text text-sm font-theme-data px-2 py-1 rounded"
                >
                  {config.backends.map((backend) => (
                    <option key={backend} value={backend}>
                      {backend}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex items-center gap-2">
                <label className="text-xs text-text-muted font-theme-data">Language:</label>
                <select
                  value={selectedLanguage}
                  onChange={(e) => setSelectedLanguage(e.target.value)}
                  className="bg-surface border border-border text-text text-sm font-theme-data px-2 py-1 rounded"
                >
                  <option value="">Auto-detect</option>
                  <option value="en">English</option>
                  <option value="es">Spanish</option>
                  <option value="fr">French</option>
                  <option value="de">German</option>
                  <option value="ja">Japanese</option>
                  <option value="zh">Chinese</option>
                </select>
              </div>
            </div>
          )}

          {/* Error Display */}
          {error && (
            <div className="p-3 bg-warning/10 border border-warning/30 rounded-lg text-warning text-sm text-center">
              {error}
            </div>
          )}

          {/* File Upload Mode */}
          {inputMode === 'file' && state === 'idle' && !selectedFile && (
            <div
              onClick={() => fileInputRef.current?.click()}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              className={`
                p-8 border-2 border-dashed rounded-lg text-center cursor-pointer
                transition-colors
                ${
                  isDragging
                    ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                    : 'border-border hover:border-[var(--accent)]/50'
                }
              `}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept={ACCEPTED_FORMATS.join(',')}
                onChange={handleInputChange}
                className="hidden"
              />

              <div className="space-y-4">
                <div className="w-16 h-16 mx-auto rounded-full bg-surface border border-border flex items-center justify-center">
                  <span className="text-3xl">📁</span>
                </div>
                <div>
                  <p className="text-text font-medium">Drop your file here</p>
                  <p className="text-text-muted text-sm mt-1">or tap to browse</p>
                </div>
                <p className="text-xs text-text-muted">
                  MP3, WAV, M4A, FLAC, MP4, WebM, MOV (max {config?.max_video_size_mb || 100}MB)
                </p>
              </div>
            </div>
          )}

          {/* YouTube URL Mode */}
          {inputMode === 'youtube' && state === 'idle' && !result && (
            <YouTubeInput
              onSubmit={handleYouTubeSubmit}
              disabled={isOffline || !config?.youtube_enabled}
              apiBase={API_BASE_URL}
              maxDurationSeconds={7200}
            />
          )}

          {/* File Selected - Preview */}
          {inputMode === 'file' && state === 'idle' && selectedFile && (
            <div className="space-y-4">
              <div className="p-4 bg-surface border border-[var(--accent)]/30 rounded-lg">
                <div className="flex items-start gap-3">
                  <div className="w-10 h-10 rounded bg-[var(--accent)]/20 flex items-center justify-center text-lg">
                    {selectedFile.type.startsWith('video/') ? '🎬' : '🎵'}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-text font-medium truncate">{selectedFile.name}</p>
                    <p className="text-text-muted text-xs mt-1">
                      {FORMAT_LABELS[selectedFile.type] || 'Unknown'} ·{' '}
                      {formatFileSize(selectedFile.size)}
                    </p>
                  </div>
                  <button onClick={reset} className="text-text-muted hover:text-warning text-sm">
                    ✕
                  </button>
                </div>
              </div>

              <div className="flex gap-3">
                <button
                  onClick={reset}
                  className="flex-1 px-4 py-3 bg-surface border border-border text-text font-theme-data hover:border-text-muted transition-colors rounded"
                >
                  Change File
                </button>
                <button
                  onClick={transcribeFile}
                  disabled={isOffline || !config?.available}
                  className="flex-1 px-4 py-3 bg-[var(--accent)] text-bg font-theme-data font-bold hover:bg-[var(--accent)]/80 transition-colors rounded disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Transcribe
                </button>
              </div>
            </div>
          )}

          {/* Processing State */}
          {(state === 'uploading' || state === 'processing') && (
            <div className="space-y-6 text-center">
              <div className="w-16 h-16 mx-auto border-4 border-[var(--accent)]/30 border-t-acid-green rounded-full animate-spin" />
              <div>
                <h2 className="text-xl font-theme-data font-bold text-[var(--accent)]">
                  {state === 'uploading' ? 'Uploading...' : 'Transcribing...'}
                </h2>
                <p className="text-text-muted text-sm mt-2">
                  {state === 'uploading' ? 'Sending file to server' : 'AI is processing your audio'}
                </p>
              </div>
              <div className="w-full bg-surface rounded-full h-2">
                <div
                  className="bg-[var(--accent)] h-2 rounded-full transition-all duration-300"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <p className="text-xs text-text-muted">{progress}%</p>
            </div>
          )}

          {/* Complete State - Results */}
          {state === 'complete' && result && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-theme-data text-[var(--accent)]">
                  Transcription Complete
                </h2>
                <div className="flex items-center gap-3 text-xs text-text-muted">
                  {result.duration && <span>{formatDuration(result.duration)}</span>}
                  {result.backend && (
                    <span className="px-2 py-0.5 bg-surface border border-border rounded">
                      {result.backend}
                    </span>
                  )}
                  {result.language && <span className="uppercase">{result.language}</span>}
                </div>
              </div>

              <div className="p-4 bg-surface border border-border rounded-lg max-h-64 overflow-y-auto">
                <p className="text-text text-sm whitespace-pre-wrap">{result.text}</p>
              </div>

              {result.processing_time && (
                <p className="text-xs text-text-muted text-center">
                  Processed in {result.processing_time.toFixed(1)}s
                </p>
              )}

              <div className="flex flex-wrap gap-2">
                <button
                  onClick={copyToClipboard}
                  className="flex-1 min-w-[100px] px-3 py-2 bg-surface border border-border text-text text-sm font-theme-data hover:border-[var(--accent)]/50 rounded"
                >
                  Copy Text
                </button>
                <button
                  onClick={() => downloadTranscript('txt')}
                  className="px-3 py-2 bg-surface border border-border text-text text-sm font-theme-data hover:border-[var(--accent)]/50 rounded"
                >
                  .txt
                </button>
                {result.segments && result.segments.length > 0 && (
                  <>
                    <button
                      onClick={() => downloadTranscript('srt')}
                      className="px-3 py-2 bg-surface border border-border text-text text-sm font-theme-data hover:border-[var(--accent)]/50 rounded"
                    >
                      .srt
                    </button>
                    <button
                      onClick={() => downloadTranscript('vtt')}
                      className="px-3 py-2 bg-surface border border-border text-text text-sm font-theme-data hover:border-[var(--accent)]/50 rounded"
                    >
                      .vtt
                    </button>
                  </>
                )}
              </div>

              <button
                onClick={reset}
                className="w-full px-4 py-3 bg-[var(--accent)] text-bg font-theme-data font-bold hover:bg-[var(--accent)]/80 transition-colors rounded"
              >
                Transcribe Another
              </button>
            </div>
          )}

          {/* Error State */}
          {state === 'error' && (
            <div className="space-y-4 text-center">
              <div className="w-16 h-16 mx-auto rounded-full bg-warning/20 flex items-center justify-center">
                <span className="text-3xl">⚠️</span>
              </div>
              <p className="text-warning">{error}</p>
              <button
                onClick={reset}
                className="px-6 py-3 bg-surface border border-border text-text font-theme-data hover:border-text-muted rounded"
              >
                Try Again
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Footer */}
      <footer className="border-t border-border p-4">
        <div className="flex items-center justify-between text-xs font-theme-data text-text-muted">
          <span>Powered by {config?.backends?.join(', ') || 'Whisper AI'}</span>
          <div className="flex gap-4">
            <Link href="/voice" className="hover:text-[var(--accent)]">
              [VOICE INPUT]
            </Link>
            <Link href="/speech" className="hover:text-[var(--accent)]">
              [TTS]
            </Link>
          </div>
        </div>
      </footer>
    </main>
  );
}
