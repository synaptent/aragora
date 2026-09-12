'use client';

import { useState, useCallback, useMemo } from 'react';
import { VoiceRecorder } from './VoiceRecorder';
import { YouTubeInput } from './YouTubeInput';

interface UploadedDocument {
  id: string;
  filename: string;
  word_count: number;
  page_count?: number;
  preview: string;
  source: 'upload';
}

interface UploadedMedia {
  id: string;
  job_id: string;
  filename: string;
  file_type: 'audio' | 'video';
  source: 'upload' | 'recording' | 'youtube';
  status: 'pending' | 'processing' | 'completed' | 'failed';
  text?: string;
  word_count?: number;
  duration_seconds?: number;
  language?: string;
  error?: string;
  youtube_title?: string;
  youtube_channel?: string;
}

interface MediaUploadProps {
  onDocumentsChange?: (documents: UploadedDocument[]) => void;
  onTranscriptionsChange?: (transcriptions: UploadedMedia[]) => void;
  apiBase?: string;
  enableDocuments?: boolean;
  enableAudioVideo?: boolean;
  enableVoice?: boolean;
  enableYouTube?: boolean;
  maxVoiceDurationSeconds?: number;
  maxYouTubeDurationSeconds?: number;
}

type ActiveTab = 'upload' | 'record' | 'youtube';

// File type mappings
const DOC_EXTENSIONS = ['.pdf', '.docx', '.txt', '.md', '.markdown'];
const AUDIO_EXTENSIONS = ['.mp3', '.m4a', '.wav', '.webm', '.ogg', '.flac'];
const VIDEO_EXTENSIONS = ['.mp4', '.webm', '.mov', '.mkv'];

const MAX_DOC_SIZE_MB = 10;
const MAX_MEDIA_SIZE_MB = 100;

export function MediaUpload({
  onDocumentsChange,
  onTranscriptionsChange,
  apiBase = '',
  enableDocuments = true,
  enableAudioVideo = true,
  enableVoice = true,
  enableYouTube = true,
  maxVoiceDurationSeconds = 300,
  maxYouTubeDurationSeconds = 7200,
}: MediaUploadProps) {
  const [activeTab, setActiveTab] = useState<ActiveTab>('upload');
  const [documents, setDocuments] = useState<UploadedDocument[]>([]);
  const [mediaFiles, setMediaFiles] = useState<UploadedMedia[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  // Determine which tabs to show
  const showTabs = [enableAudioVideo, enableVoice, enableYouTube].filter(Boolean).length > 0;
  const tabs: { id: ActiveTab; label: string; icon: string }[] = [
    ...(enableDocuments || enableAudioVideo
      ? [{ id: 'upload' as const, label: 'Upload', icon: 'upload' }]
      : []),
    ...(enableVoice ? [{ id: 'record' as const, label: 'Record', icon: 'mic' }] : []),
    ...(enableYouTube ? [{ id: 'youtube' as const, label: 'YouTube', icon: 'play' }] : []),
  ];

  // Build accepted extensions
  const allExtensions = useMemo(
    () => [
      ...(enableDocuments ? DOC_EXTENSIONS : []),
      ...(enableAudioVideo ? [...AUDIO_EXTENSIONS, ...VIDEO_EXTENSIONS] : []),
    ],
    [enableDocuments, enableAudioVideo],
  );

  const getFileType = (filename: string): 'document' | 'audio' | 'video' => {
    const ext = '.' + filename.split('.').pop()?.toLowerCase();
    if (AUDIO_EXTENSIONS.includes(ext)) return 'audio';
    if (VIDEO_EXTENSIONS.includes(ext)) return 'video';
    return 'document';
  };

  // Upload document file
  const uploadDocument = useCallback(
    async (file: File) => {
      const formData = new FormData();
      formData.append('file', file);

      const response = await fetch(`${apiBase}/api/documents/upload`, {
        method: 'POST',
        body: formData,
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || 'Upload failed');
      }

      const newDoc: UploadedDocument = {
        id: data.document.id,
        filename: data.document.filename,
        word_count: data.document.word_count,
        page_count: data.document.page_count,
        preview: data.document.preview,
        source: 'upload',
      };

      setDocuments((prev) => {
        const updated = [...prev, newDoc];
        onDocumentsChange?.(updated);
        return updated;
      });
    },
    [apiBase, onDocumentsChange],
  );

  // Upload media file for transcription
  const uploadMedia = useCallback(
    async (
      file: File | Blob,
      fileType: 'audio' | 'video',
      source: 'upload' | 'recording' = 'upload',
      filename?: string,
    ) => {
      const formData = new FormData();
      const actualFilename =
        filename || (file instanceof File ? file.name : `recording_${Date.now()}.webm`);
      formData.append('file', file, actualFilename);

      const endpoint =
        fileType === 'video'
          ? `${apiBase}/api/transcription/video`
          : `${apiBase}/api/transcription/audio`;

      const response = await fetch(endpoint, { method: 'POST', body: formData });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || 'Transcription failed');
      }

      const newMedia: UploadedMedia = {
        id: data.job_id,
        job_id: data.job_id,
        filename: actualFilename,
        file_type: fileType,
        source,
        status: data.status || 'completed',
        text: data.text,
        word_count: data.text ? data.text.split(/\s+/).length : undefined,
        duration_seconds: data.duration,
        language: data.language,
      };

      setMediaFiles((prev) => {
        const updated = [...prev, newMedia];
        onTranscriptionsChange?.(updated);
        return updated;
      });

      return newMedia;
    },
    [apiBase, onTranscriptionsChange],
  );

  // Handle file upload
  const handleFileUpload = useCallback(
    async (file: File) => {
      setUploading(true);
      setError(null);

      try {
        const ext = '.' + file.name.split('.').pop()?.toLowerCase();

        if (!allExtensions.includes(ext)) {
          throw new Error(`Unsupported file type: ${ext}`);
        }

        const fileType = getFileType(file.name);
        const maxSizeMB = fileType === 'document' ? MAX_DOC_SIZE_MB : MAX_MEDIA_SIZE_MB;

        if (file.size > maxSizeMB * 1024 * 1024) {
          throw new Error(`File too large. Max: ${maxSizeMB}MB for ${fileType} files.`);
        }

        if (fileType === 'document') {
          await uploadDocument(file);
        } else {
          await uploadMedia(file, fileType, 'upload');
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Upload failed');
      } finally {
        setUploading(false);
      }
    },
    [allExtensions, uploadDocument, uploadMedia],
  );

  // Handle voice recording completion
  const handleRecordingComplete = useCallback(
    async (audioBlob: Blob, _duration: number) => {
      setUploading(true);
      setError(null);

      try {
        await uploadMedia(audioBlob, 'audio', 'recording', `voice_recording_${Date.now()}.webm`);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to transcribe recording');
      } finally {
        setUploading(false);
      }
    },
    [uploadMedia],
  );

  // Handle YouTube submission
  const handleYouTubeSubmit = useCallback(
    async (
      url: string,
      videoInfo: { video_id: string; title: string; duration: number; channel: string },
    ) => {
      setUploading(true);
      setError(null);

      try {
        const response = await fetch(`${apiBase}/api/transcription/youtube`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url }),
        });

        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.error || 'YouTube transcription failed');
        }

        const newMedia: UploadedMedia = {
          id: data.job_id,
          job_id: data.job_id,
          filename: `${videoInfo.video_id}.mp3`,
          file_type: 'audio',
          source: 'youtube',
          status: data.status || 'completed',
          text: data.text,
          word_count: data.text ? data.text.split(/\s+/).length : undefined,
          duration_seconds: data.duration || videoInfo.duration,
          language: data.language,
          youtube_title: videoInfo.title,
          youtube_channel: videoInfo.channel,
        };

        setMediaFiles((prev) => {
          const updated = [...prev, newMedia];
          onTranscriptionsChange?.(updated);
          return updated;
        });
      } catch (err) {
        setError(err instanceof Error ? err.message : 'YouTube transcription failed');
      } finally {
        setUploading(false);
      }
    },
    [apiBase, onTranscriptionsChange],
  );

  // Drag and drop handlers
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
      const file = e.dataTransfer.files[0];
      if (file) {
        handleFileUpload(file);
      }
    },
    [handleFileUpload],
  );

  // Remove handlers
  const removeDocument = (id: string) => {
    setDocuments((prev) => {
      const updated = prev.filter((d) => d.id !== id);
      onDocumentsChange?.(updated);
      return updated;
    });
  };

  const removeMedia = (id: string) => {
    setMediaFiles((prev) => {
      const updated = prev.filter((m) => m.id !== id);
      onTranscriptionsChange?.(updated);
      return updated;
    });
  };

  const _getSourceIcon = (source: UploadedMedia['source']) => {
    switch (source) {
      case 'upload':
        return null;
      case 'recording':
        return 'mic';
      case 'youtube':
        return 'play';
    }
  };

  const _getFileIcon = (filename: string, source?: string) => {
    if (source === 'youtube') return 'play';
    if (source === 'recording') return 'mic';

    const ext = filename.split('.').pop()?.toLowerCase();
    switch (ext) {
      case 'pdf':
        return 'doc-pdf';
      case 'docx':
        return 'doc-word';
      case 'txt':
      case 'md':
      case 'markdown':
        return 'doc-text';
      case 'mp3':
      case 'm4a':
      case 'wav':
      case 'webm':
      case 'ogg':
      case 'flac':
        return 'audio';
      case 'mp4':
      case 'mov':
      case 'mkv':
        return 'video';
      default:
        return 'file';
    }
  };

  return (
    <div className="panel" style={{ padding: 0 }}>
      {/* Header with tabs */}
      <div className="border-b border-border">
        <div className="px-4 pt-4">
          <h3 className="panel-title-sm mb-3">Media Input</h3>
        </div>
        {showTabs && tabs.length > 1 && (
          <div className="flex gap-1 px-4">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`
                  px-4 py-2 text-sm font-medium rounded-t-lg transition-colors
                  ${
                    activeTab === tab.id
                      ? 'bg-surface-elevated text-text border-t border-x border-border -mb-px'
                      : 'text-text-muted hover:text-text hover:bg-surface'
                  }
                `}
              >
                {tab.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Tab content */}
      <div className="p-4">
        {/* Upload tab */}
        {activeTab === 'upload' && (
          <div className="space-y-4">
            {/* Drop zone */}
            <div
              role="button"
              tabIndex={uploading ? -1 : 0}
              aria-label="Upload a file. Click or drag and drop."
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onClick={() => {
                const input = document.createElement('input');
                input.type = 'file';
                input.accept = allExtensions.join(',');
                input.onchange = (e) => {
                  const file = (e.target as HTMLInputElement).files?.[0];
                  if (file) handleFileUpload(file);
                };
                input.click();
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  const input = document.createElement('input');
                  input.type = 'file';
                  input.accept = allExtensions.join(',');
                  input.onchange = (ev) => {
                    const file = (ev.target as HTMLInputElement).files?.[0];
                    if (file) handleFileUpload(file);
                  };
                  input.click();
                }
              }}
              className={`
                border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-all
                focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface
                ${isDragging ? 'border-accent bg-accent/10' : 'border-border hover:border-accent/50 hover:bg-surface'}
                ${uploading ? 'opacity-50 pointer-events-none' : ''}
              `}
            >
              {uploading ? (
                <div className="flex items-center justify-center gap-2 text-text-muted">
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
                  <span>Processing...</span>
                </div>
              ) : (
                <>
                  <div className="text-3xl mb-2">
                    {enableDocuments && enableAudioVideo
                      ? '📎 🎵 🎬'
                      : enableDocuments
                        ? '📎'
                        : '🎵 🎬'}
                  </div>
                  <div className="text-sm text-text-muted">Drop files here or click to upload</div>
                  <div className="text-xs text-text-muted mt-2">
                    {enableDocuments && 'Documents: PDF, DOCX, TXT, MD (10MB)'}
                    {enableDocuments && enableAudioVideo && ' | '}
                    {enableAudioVideo && 'Media: MP3, WAV, MP4, MOV, etc. (100MB)'}
                  </div>
                </>
              )}
            </div>
          </div>
        )}

        {/* Record tab */}
        {activeTab === 'record' && enableVoice && (
          <VoiceRecorder
            onRecordingComplete={handleRecordingComplete}
            maxDurationSeconds={maxVoiceDurationSeconds}
            disabled={uploading}
          />
        )}

        {/* YouTube tab */}
        {activeTab === 'youtube' && enableYouTube && (
          <YouTubeInput
            onSubmit={handleYouTubeSubmit}
            apiBase={apiBase}
            maxDurationSeconds={maxYouTubeDurationSeconds}
            disabled={uploading}
          />
        )}

        {/* Error message */}
        {error && (
          <div className="mt-4 bg-[var(--crimson)]/10 border border-[var(--crimson)]/30 rounded p-2 text-sm text-[var(--crimson)]">
            {error}
          </div>
        )}

        {/* Uploaded files list */}
        {(documents.length > 0 || mediaFiles.length > 0) && (
          <div className="mt-4 space-y-2">
            <div className="text-xs text-text-muted uppercase tracking-wider">
              Files ({documents.length + mediaFiles.length})
            </div>

            {/* Documents */}
            {documents.map((doc) => (
              <div
                key={doc.id}
                className="bg-surface border border-border rounded p-2 flex items-start gap-2"
              >
                <span className="text-lg flex-shrink-0">📄</span>
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-sm truncate">{doc.filename}</div>
                  <div className="text-xs text-text-muted">
                    {doc.word_count.toLocaleString()} words
                    {doc.page_count && doc.page_count > 1 && ` | ${doc.page_count} pages`}
                  </div>
                </div>
                <button
                  onClick={() => removeDocument(doc.id)}
                  className="text-text-muted hover:text-[var(--crimson)] transition-colors p-1"
                  aria-label={`Remove ${doc.filename}`}
                >
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    fill="none"
                    viewBox="0 0 24 24"
                    strokeWidth={1.5}
                    stroke="currentColor"
                    className="w-4 h-4"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            ))}

            {/* Media / Transcriptions */}
            {mediaFiles.map((media) => (
              <div
                key={media.id}
                className="bg-surface border border-border rounded p-2 flex items-start gap-2"
              >
                <span className="text-lg flex-shrink-0">
                  {media.source === 'youtube'
                    ? '📺'
                    : media.source === 'recording'
                      ? '🎤'
                      : media.file_type === 'video'
                        ? '🎬'
                        : '🎵'}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-sm truncate flex items-center gap-2">
                    {media.youtube_title || media.filename}
                    <span
                      className={`text-xs px-2 py-0.5 rounded ${
                        media.status === 'completed'
                          ? 'bg-success/20 text-success'
                          : media.status === 'failed'
                            ? 'bg-[var(--crimson)]/20 text-[var(--crimson)]'
                            : 'bg-amber-500/20 text-amber-400'
                      }`}
                    >
                      {media.status === 'completed'
                        ? 'Done'
                        : media.status === 'failed'
                          ? 'Failed'
                          : 'Processing'}
                    </span>
                  </div>
                  <div className="text-xs text-text-muted">
                    {media.source === 'youtube' &&
                      media.youtube_channel &&
                      `${media.youtube_channel} | `}
                    {media.duration_seconds && `${Math.round(media.duration_seconds)}s`}
                    {media.word_count && ` | ${media.word_count.toLocaleString()} words`}
                    {media.language && ` | ${media.language.toUpperCase()}`}
                  </div>
                  {media.status === 'completed' && media.text && (
                    <div className="text-xs text-text-muted mt-1 line-clamp-2">
                      {media.text.slice(0, 150)}...
                    </div>
                  )}
                  {media.status === 'failed' && media.error && (
                    <div className="text-xs text-[var(--crimson)] mt-1">Error: {media.error}</div>
                  )}
                </div>
                <button
                  onClick={() => removeMedia(media.id)}
                  className="text-text-muted hover:text-[var(--crimson)] transition-colors p-1"
                  aria-label={`Remove ${media.youtube_title || media.filename}`}
                >
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    fill="none"
                    viewBox="0 0 24 24"
                    strokeWidth={1.5}
                    stroke="currentColor"
                    className="w-4 h-4"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
