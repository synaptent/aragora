'use client';

/**
 * Document Preview Panel Component
 *
 * Displays document details with:
 * - Content preview (first 500 chars)
 * - Metadata (size, chunks, tokens, status)
 * - Chunk navigation
 * - Quick audit action button
 */

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { useBackend } from '@/components/BackendSelector';
import { useAuth } from '@/context/AuthContext';

interface DocumentDetails {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  chunk_count: number;
  token_count?: number;
  preview?: string;
  created_at: string;
  processed_at?: string;
  error_message?: string;
}

interface DocumentChunk {
  id: string;
  sequence: number;
  content: string;
  chunk_type: string;
  token_count: number;
  start_page?: number;
  end_page?: number;
}

interface DocumentPreviewPanelProps {
  documentId: string;
  onClose?: () => void;
  onStartAudit?: (documentId: string) => void;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(dateStr?: string): string {
  if (!dateStr) return '-';
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    completed: 'bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/40',
    processing: 'bg-acid-yellow/20 text-[var(--acid-yellow)] border-acid-yellow/40 animate-pulse',
    pending: 'bg-acid-blue/20 text-acid-blue border-acid-blue/40',
    failed: 'bg-acid-red/20 text-acid-red border-acid-red/40',
  };
  return (
    <span
      className={`px-2 py-0.5 text-xs font-theme-data rounded border ${colors[status] || colors.pending}`}
    >
      {status.toUpperCase()}
    </span>
  );
}

function ChunkTypeBadge({ type }: { type: string }) {
  const colors: Record<string, string> = {
    text: 'bg-surface text-foreground',
    code: 'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)]',
    table: 'bg-acid-purple/20 text-acid-purple',
    heading: 'bg-acid-yellow/20 text-[var(--acid-yellow)]',
    image: 'bg-acid-orange/20 text-acid-orange',
  };
  return (
    <span
      className={`px-1.5 py-0.5 text-xs font-theme-data rounded ${colors[type] || colors.text}`}
    >
      {type}
    </span>
  );
}

export function DocumentPreviewPanel({
  documentId,
  onClose,
  onStartAudit,
}: DocumentPreviewPanelProps) {
  const { config: backendConfig } = useBackend();
  const { tokens } = useAuth();

  const [document, setDocument] = useState<DocumentDetails | null>(null);
  const [chunks, setChunks] = useState<DocumentChunk[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeChunkIndex, setActiveChunkIndex] = useState(0);
  const [showChunks, setShowChunks] = useState(false);

  // Fetch document details
  const fetchDocument = useCallback(async () => {
    try {
      const response = await fetch(`${backendConfig.api}/api/documents/${documentId}`, {
        headers: { Authorization: `Bearer ${tokens?.access_token || ''}` },
      });
      if (!response.ok) throw new Error('Document not found');
      const data = await response.json();
      setDocument(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch document');
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api, documentId, tokens?.access_token]);

  // Fetch chunks when requested
  const fetchChunks = useCallback(async () => {
    try {
      const response = await fetch(`${backendConfig.api}/api/documents/${documentId}/chunks`, {
        headers: { Authorization: `Bearer ${tokens?.access_token || ''}` },
      });
      if (response.ok) {
        const data = await response.json();
        setChunks(data.chunks || []);
      }
    } catch {
      // Silent fail
    }
  }, [backendConfig.api, documentId, tokens?.access_token]);

  useEffect(() => {
    fetchDocument();
  }, [fetchDocument]);

  useEffect(() => {
    if (showChunks && chunks.length === 0) {
      fetchChunks();
    }
  }, [showChunks, chunks.length, fetchChunks]);

  if (loading) {
    return (
      <div className="p-6 text-center">
        <div className="text-muted font-theme-data animate-pulse">Loading document...</div>
      </div>
    );
  }

  if (error || !document) {
    return (
      <div className="p-6 text-center">
        <div className="text-acid-red font-theme-data mb-4">{error || 'Document not found'}</div>
        {onClose && (
          <button onClick={onClose} className="btn btn-ghost">
            Close
          </button>
        )}
      </div>
    );
  }

  const activeChunk = chunks[activeChunkIndex];

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="p-4 border-b border-border flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <StatusBadge status={document.status} />
            <span className="text-xs font-theme-data text-muted truncate">
              {document.mime_type}
            </span>
          </div>
          <h3 className="font-theme-data font-medium truncate" title={document.filename}>
            {document.filename}
          </h3>
        </div>
        {onClose && (
          <button onClick={onClose} className="text-muted hover:text-foreground ml-2">
            [X]
          </button>
        )}
      </div>

      {/* Metadata */}
      <div className="p-4 border-b border-border bg-surface/50">
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <div className="text-xs font-theme-data text-muted mb-0.5">SIZE</div>
            <div className="font-theme-data">{formatFileSize(document.size_bytes)}</div>
          </div>
          <div>
            <div className="text-xs font-theme-data text-muted mb-0.5">CHUNKS</div>
            <div className="font-theme-data">{document.chunk_count}</div>
          </div>
          <div>
            <div className="text-xs font-theme-data text-muted mb-0.5">TOKENS</div>
            <div className="font-theme-data">{document.token_count?.toLocaleString() || '-'}</div>
          </div>
          <div>
            <div className="text-xs font-theme-data text-muted mb-0.5">UPLOADED</div>
            <div className="font-theme-data text-xs">{formatDate(document.created_at)}</div>
          </div>
        </div>
      </div>

      {/* Preview or Chunks */}
      <div className="flex-1 overflow-y-auto">
        {!showChunks ? (
          // Document preview
          <div className="p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-theme-data text-muted">PREVIEW</span>
              {document.status === 'completed' && document.chunk_count > 0 && (
                <button
                  onClick={() => setShowChunks(true)}
                  className="text-xs font-theme-data text-accent hover:underline"
                >
                  VIEW CHUNKS ({document.chunk_count})
                </button>
              )}
            </div>
            {document.preview ? (
              <div className="p-3 bg-surface rounded border border-border">
                <pre className="text-sm whitespace-pre-wrap font-theme-data text-muted leading-relaxed">
                  {document.preview}
                </pre>
                {document.preview.length >= 500 && (
                  <div className="text-xs text-muted mt-2 italic">...truncated</div>
                )}
              </div>
            ) : document.status === 'processing' ? (
              <div className="p-4 text-center text-muted font-theme-data animate-pulse">
                Processing document...
              </div>
            ) : document.status === 'failed' ? (
              <div className="p-4 text-center">
                <div className="text-acid-red font-theme-data mb-2">Processing failed</div>
                {document.error_message && (
                  <div className="text-sm text-muted">{document.error_message}</div>
                )}
              </div>
            ) : (
              <div className="p-4 text-center text-muted font-theme-data">No preview available</div>
            )}
          </div>
        ) : (
          // Chunk navigation
          <div className="p-4">
            <div className="flex items-center justify-between mb-3">
              <button
                onClick={() => setShowChunks(false)}
                className="text-xs font-theme-data text-muted hover:text-foreground"
              >
                BACK TO PREVIEW
              </button>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setActiveChunkIndex(Math.max(0, activeChunkIndex - 1))}
                  disabled={activeChunkIndex === 0}
                  className="px-2 py-1 text-xs font-theme-data border border-border rounded disabled:opacity-30"
                >
                  PREV
                </button>
                <span className="text-xs font-theme-data">
                  {activeChunkIndex + 1} / {chunks.length}
                </span>
                <button
                  onClick={() =>
                    setActiveChunkIndex(Math.min(chunks.length - 1, activeChunkIndex + 1))
                  }
                  disabled={activeChunkIndex === chunks.length - 1}
                  className="px-2 py-1 text-xs font-theme-data border border-border rounded disabled:opacity-30"
                >
                  NEXT
                </button>
              </div>
            </div>

            {chunks.length === 0 ? (
              <div className="p-4 text-center text-muted font-theme-data animate-pulse">
                Loading chunks...
              </div>
            ) : activeChunk ? (
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <ChunkTypeBadge type={activeChunk.chunk_type} />
                  <span className="text-xs font-theme-data text-muted">
                    {activeChunk.token_count} tokens
                  </span>
                  {activeChunk.start_page && (
                    <span className="text-xs font-theme-data text-muted ml-auto">
                      Page {activeChunk.start_page}
                      {activeChunk.end_page && activeChunk.end_page !== activeChunk.start_page
                        ? `-${activeChunk.end_page}`
                        : ''}
                    </span>
                  )}
                </div>
                <div className="p-3 bg-surface rounded border border-border max-h-64 overflow-y-auto">
                  <pre className="text-sm whitespace-pre-wrap font-theme-data leading-relaxed">
                    {activeChunk.content}
                  </pre>
                </div>
              </div>
            ) : null}

            {/* Chunk list */}
            <div className="mt-4">
              <div className="text-xs font-theme-data text-muted mb-2">ALL CHUNKS</div>
              <div className="flex flex-wrap gap-1">
                {chunks.map((chunk, idx) => (
                  <button
                    key={chunk.id}
                    onClick={() => setActiveChunkIndex(idx)}
                    className={`px-2 py-1 text-xs font-theme-data rounded transition-colors ${
                      idx === activeChunkIndex
                        ? 'bg-accent text-background'
                        : 'bg-surface hover:bg-surface/80'
                    }`}
                    title={`${chunk.chunk_type} - ${chunk.token_count} tokens`}
                  >
                    {idx + 1}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="p-4 border-t border-border bg-surface/50">
        <div className="flex items-center gap-2">
          {document.status === 'completed' && onStartAudit && (
            <button onClick={() => onStartAudit(document.id)} className="btn btn-primary flex-1">
              START AUDIT
            </button>
          )}
          <Link
            href={`/audit/new?documents=${document.id}`}
            className="btn btn-ghost flex-1 text-center"
          >
            AUDIT OPTIONS
          </Link>
        </div>
      </div>
    </div>
  );
}

export default DocumentPreviewPanel;
