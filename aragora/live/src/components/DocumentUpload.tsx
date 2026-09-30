'use client';

import { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import { useAuth } from '@/context/AuthContext';

interface UploadedDocument {
  id: string;
  filename: string;
  word_count: number;
  page_count?: number;
  preview: string;
}

interface UploadedMedia {
  id: string;
  job_id: string;
  filename: string;
  file_type: 'audio' | 'video';
  status: 'pending' | 'processing' | 'completed' | 'failed';
  text?: string;
  word_count?: number;
  duration_seconds?: number;
  language?: string;
  error?: string;
}

interface DocumentUploadProps {
  onDocumentsChange?: (docIds: string[]) => void;
  onTranscriptionsChange?: (transcriptions: UploadedMedia[]) => void;
  apiBase?: string;
  enableAudioVideo?: boolean;
}

type UploadStatus = 'idle' | 'uploading' | 'success' | 'error';

// Document MIME types
const DOC_TYPES = {
  'application/pdf': '.pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
  'text/plain': '.txt',
  'text/markdown': '.md',
};

const DOC_EXTENSIONS = ['.pdf', '.docx', '.txt', '.md', '.markdown'];
const AUDIO_EXTENSIONS = ['.mp3', '.m4a', '.wav', '.webm'];
const VIDEO_EXTENSIONS = ['.mp4', '.webm', '.mov'];

// Max sizes
const MAX_DOC_SIZE_MB = 10;
const MAX_MEDIA_SIZE_MB = 25; // Whisper API limit

export function DocumentUpload({
  onDocumentsChange,
  onTranscriptionsChange,
  apiBase = '',
  enableAudioVideo = true,
}: DocumentUploadProps) {
  const { tokens } = useAuth();
  const [documents, setDocuments] = useState<UploadedDocument[]>([]);
  const [mediaFiles, setMediaFiles] = useState<UploadedMedia[]>([]);
  const [status, setStatus] = useState<UploadStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Build accepted extensions based on enableAudioVideo prop
  const allExtensions = useMemo(
    () =>
      enableAudioVideo
        ? [...DOC_EXTENSIONS, ...AUDIO_EXTENSIONS, ...VIDEO_EXTENSIONS]
        : DOC_EXTENSIONS,
    [enableAudioVideo],
  );

  // Determine file type from extension
  const getFileType = (filename: string): 'document' | 'audio' | 'video' => {
    const ext = '.' + filename.split('.').pop()?.toLowerCase();
    if (AUDIO_EXTENSIONS.includes(ext)) return 'audio';
    if (VIDEO_EXTENSIONS.includes(ext)) return 'video';
    return 'document';
  };

  // Poll for transcription status
  useEffect(() => {
    const pendingJobs = mediaFiles.filter(
      (m) => m.status === 'pending' || m.status === 'processing',
    );

    if (pendingJobs.length === 0) return;

    const pollInterval = setInterval(async () => {
      for (const job of pendingJobs) {
        try {
          const headers: HeadersInit = {};
          if (tokens?.access_token) {
            headers['Authorization'] = `Bearer ${tokens.access_token}`;
          }
          const response = await fetch(`${apiBase}/api/transcription/${job.job_id}`, { headers });
          if (!response.ok) continue;

          const data = await response.json();

          if (data.status === 'completed' || data.status === 'failed') {
            setMediaFiles((prev) => {
              const updated = prev.map((m) =>
                m.job_id === job.job_id
                  ? {
                      ...m,
                      status: data.status,
                      text: data.text,
                      word_count: data.word_count,
                      duration_seconds: data.duration_seconds,
                      language: data.language,
                      error: data.error,
                    }
                  : m,
              );
              onTranscriptionsChange?.(updated);
              return updated;
            });
          }
        } catch {
          // Ignore polling errors
        }
      }
    }, 2000);

    return () => clearInterval(pollInterval);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- Token is stable during polling
  }, [mediaFiles, apiBase, onTranscriptionsChange]);

  // Upload document file
  const uploadDocument = useCallback(
    async (file: File) => {
      const formData = new FormData();
      formData.append('file', file);

      const headers: HeadersInit = {};
      if (tokens?.access_token) {
        headers['Authorization'] = `Bearer ${tokens.access_token}`;
      }

      const response = await fetch(`${apiBase}/api/documents/upload`, {
        method: 'POST',
        body: formData,
        headers,
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
      };

      setDocuments((prev) => {
        const updated = [...prev, newDoc];
        onDocumentsChange?.(updated.map((d) => d.id));
        return updated;
      });
    },
    [apiBase, onDocumentsChange, tokens?.access_token],
  );

  // Upload media file for transcription
  const uploadMedia = useCallback(
    async (file: File, fileType: 'audio' | 'video') => {
      const formData = new FormData();
      formData.append('file', file);

      const headers: HeadersInit = {};
      if (tokens?.access_token) {
        headers['Authorization'] = `Bearer ${tokens.access_token}`;
      }

      const response = await fetch(`${apiBase}/api/transcription/upload`, {
        method: 'POST',
        body: formData,
        headers,
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Transcription upload failed');
      }

      const newMedia: UploadedMedia = {
        id: data.job_id,
        job_id: data.job_id,
        filename: file.name,
        file_type: fileType,
        status: 'pending',
      };

      setMediaFiles((prev) => {
        const updated = [...prev, newMedia];
        onTranscriptionsChange?.(updated);
        return updated;
      });
    },
    [apiBase, onTranscriptionsChange, tokens?.access_token],
  );

  // Main upload handler
  const uploadFile = useCallback(
    async (file: File) => {
      setStatus('uploading');
      setError(null);

      try {
        const fileType = getFileType(file.name);

        if (fileType === 'document') {
          await uploadDocument(file);
        } else {
          await uploadMedia(file, fileType);
        }

        setStatus('success');
        setTimeout(() => setStatus('idle'), 2000);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Upload failed');
        setStatus('error');
      }
    },
    [uploadDocument, uploadMedia],
  );

  const handleFileSelect = useCallback(
    (files: FileList | null) => {
      if (!files || files.length === 0) return;

      const file = files[0];

      // Validate file extension
      const ext = '.' + file.name.split('.').pop()?.toLowerCase();
      if (!allExtensions.includes(ext)) {
        setError(`Unsupported file type: ${ext}. Supported: ${allExtensions.join(', ')}`);
        setStatus('error');
        return;
      }

      // Determine file category and max size
      const fileType = getFileType(file.name);
      const maxSizeMB = fileType === 'document' ? MAX_DOC_SIZE_MB : MAX_MEDIA_SIZE_MB;
      const maxSizeBytes = maxSizeMB * 1024 * 1024;

      // Validate MIME type matches extension (security check) - only for documents
      if (fileType === 'document') {
        const expectedMimes = Object.entries(DOC_TYPES)
          .filter(
            ([, extension]) => extension === ext || (ext === '.markdown' && extension === '.md'),
          )
          .map(([mime]) => mime);

        if (expectedMimes.length > 0 && file.type && !expectedMimes.includes(file.type)) {
          // Allow empty MIME type (some browsers don't set it)
          if (file.type !== '') {
            setError(
              `File MIME type (${file.type}) doesn't match extension (${ext}). Possible file spoofing.`,
            );
            setStatus('error');
            return;
          }
        }
      }

      // Validate file size
      if (file.size > maxSizeBytes) {
        setError(`File too large. Maximum size is ${maxSizeMB}MB for ${fileType} files.`);
        setStatus('error');
        return;
      }

      uploadFile(file);
    },
    [uploadFile, allExtensions],
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
      handleFileSelect(e.dataTransfer.files);
    },
    [handleFileSelect],
  );

  const removeDocument = (docId: string) => {
    setDocuments((prev) => {
      const updated = prev.filter((d) => d.id !== docId);
      onDocumentsChange?.(updated.map((d) => d.id));
      return updated;
    });
  };

  const removeMedia = (mediaId: string) => {
    setMediaFiles((prev) => {
      const updated = prev.filter((m) => m.id !== mediaId);
      onTranscriptionsChange?.(updated);
      return updated;
    });
  };

  const getFileIcon = (filename: string) => {
    const ext = filename.split('.').pop()?.toLowerCase();
    switch (ext) {
      case 'pdf':
        return '📄';
      case 'docx':
        return '📝';
      case 'txt':
        return '📃';
      case 'md':
      case 'markdown':
        return '📋';
      case 'mp3':
      case 'm4a':
      case 'wav':
      case 'webm':
        return '🎵';
      case 'mp4':
      case 'mov':
        return '🎬';
      default:
        return '📎';
    }
  };

  const getStatusBadge = (status: UploadedMedia['status']) => {
    switch (status) {
      case 'pending':
        return (
          <span className="text-xs bg-amber-500/20 text-amber-400 px-2 py-0.5 rounded">Queued</span>
        );
      case 'processing':
        return (
          <span className="text-xs bg-blue-500/20 text-blue-400 px-2 py-0.5 rounded flex items-center gap-1">
            <svg className="animate-spin h-3 w-3" viewBox="0 0 24 24">
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
            Transcribing
          </span>
        );
      case 'completed':
        return <span className="text-xs bg-success/20 text-success px-2 py-0.5 rounded">Done</span>;
      case 'failed':
        return (
          <span className="text-xs bg-[var(--crimson)]/20 text-[var(--crimson)] px-2 py-0.5 rounded">
            Failed
          </span>
        );
    }
  };

  return (
    <div className="panel" style={{ padding: 0 }}>
      <div className="p-4 border-b border-border">
        <h3 className="panel-title-sm">Documents</h3>
      </div>

      <div className="p-4 space-y-4">
        {/* Drop zone */}
        <div
          role="button"
          tabIndex={status === 'uploading' ? -1 : 0}
          aria-label="Upload a document. Click or press Enter to select a file, or drag and drop."
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              fileInputRef.current?.click();
            }
          }}
          className={`
            border-2 border-dashed rounded-lg p-4 text-center cursor-pointer transition-all
            focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface
            ${
              isDragging
                ? 'border-accent bg-accent/10'
                : 'border-border hover:border-accent/50 hover:bg-surface'
            }
            ${status === 'uploading' ? 'opacity-50 pointer-events-none' : ''}
          `}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept={allExtensions.join(',')}
            onChange={(e) => handleFileSelect(e.target.files)}
            className="hidden"
          />

          {status === 'uploading' ? (
            <div className="flex items-center justify-center gap-2 text-text-muted">
              <svg
                className="animate-spin h-5 w-5"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                />
              </svg>
              <span>Uploading...</span>
            </div>
          ) : (
            <>
              <div className="text-2xl mb-2">{enableAudioVideo ? '📎🎵🎬' : '📎'}</div>
              <div className="text-sm text-text-muted">Drop files here or click to upload</div>
              <div className="text-xs text-text-muted mt-1">
                {enableAudioVideo
                  ? 'PDF, DOCX, TXT, MD (10MB) | MP3, WAV, M4A, MP4, MOV (25MB)'
                  : 'PDF, DOCX, TXT, MD (max 10MB)'}
              </div>
            </>
          )}
        </div>

        {/* Error message */}
        {status === 'error' && error && (
          <div className="bg-[var(--crimson)]/10 border border-[var(--crimson)]/30 rounded p-2 text-sm text-[var(--crimson)]">
            {error}
          </div>
        )}

        {/* Success message */}
        {status === 'success' && (
          <div className="bg-success/10 border border-success/30 rounded p-2 text-sm text-success">
            Document uploaded successfully
          </div>
        )}

        {/* Uploaded documents list */}
        {documents.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs text-text-muted uppercase tracking-wider">
              Documents ({documents.length})
            </div>
            {documents.map((doc) => (
              <div
                key={doc.id}
                className="bg-surface border border-border rounded p-2 flex items-start gap-2"
              >
                <span className="text-lg flex-shrink-0">{getFileIcon(doc.filename)}</span>
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-sm truncate">{doc.filename}</div>
                  <div className="text-xs text-text-muted">
                    {doc.word_count.toLocaleString()} words
                    {doc.page_count && doc.page_count > 1 && ` | ${doc.page_count} pages`}
                  </div>
                  {doc.preview && (
                    <div className="text-xs text-text-muted mt-1 line-clamp-2">
                      {doc.preview.slice(0, 100)}...
                    </div>
                  )}
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    removeDocument(doc.id);
                  }}
                  className="text-text-muted hover:text-[var(--crimson)] transition-colors p-1"
                  title="Remove document"
                  aria-label={`Remove document: ${doc.filename}`}
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

        {/* Media files / transcriptions list */}
        {enableAudioVideo && mediaFiles.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs text-text-muted uppercase tracking-wider">
              Transcriptions ({mediaFiles.length})
            </div>
            {mediaFiles.map((media) => (
              <div
                key={media.id}
                className="bg-surface border border-border rounded p-2 flex items-start gap-2"
              >
                <span className="text-lg flex-shrink-0">{getFileIcon(media.filename)}</span>
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-sm truncate flex items-center gap-2">
                    {media.filename}
                    {getStatusBadge(media.status)}
                  </div>
                  <div className="text-xs text-text-muted">
                    {media.file_type === 'audio' ? 'Audio' : 'Video'}
                    {media.duration_seconds && ` | ${Math.round(media.duration_seconds)}s`}
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
                  onClick={(e) => {
                    e.stopPropagation();
                    removeMedia(media.id);
                  }}
                  className="text-text-muted hover:text-[var(--crimson)] transition-colors p-1"
                  title="Remove transcription"
                  aria-label={`Remove transcription: ${media.filename}`}
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
