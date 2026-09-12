'use client';

import { useState, useCallback, useRef } from 'react';
import { useAdaptiveMode } from '@/context/AdaptiveModeContext';

/**
 * File type categories for smart processing
 */
export type FileCategory =
  'code' | 'document' | 'audio' | 'video' | 'image' | 'data' | 'archive' | 'unknown';

/**
 * Processing action based on file type
 */
export type ProcessingAction =
  | 'index' // Repository/code indexing
  | 'extract' // Document text extraction
  | 'transcribe' // Audio/video transcription
  | 'ocr' // Image text extraction
  | 'parse' // Data file parsing
  | 'expand' // Archive extraction
  | 'skip'; // No processing

/**
 * Upload item in the queue
 */
export interface UploadItem {
  id: string;
  file: File;
  name: string;
  size: number;
  category: FileCategory;
  suggestedAction: ProcessingAction;
  status: 'pending' | 'uploading' | 'processing' | 'completed' | 'failed';
  progress: number;
  error?: string;
  result?: { id: string; url?: string; text?: string; metadata?: Record<string, unknown> };
}

/**
 * File type detection rules
 */
const FILE_PATTERNS: Record<FileCategory, { extensions: string[]; mimePatterns: string[] }> = {
  code: {
    extensions: [
      '.py',
      '.ts',
      '.tsx',
      '.js',
      '.jsx',
      '.go',
      '.rs',
      '.java',
      '.c',
      '.cpp',
      '.h',
      '.rb',
      '.php',
      '.swift',
      '.kt',
    ],
    mimePatterns: ['text/x-', 'application/x-python', 'application/javascript'],
  },
  document: {
    extensions: [
      '.pdf',
      '.docx',
      '.doc',
      '.txt',
      '.md',
      '.markdown',
      '.rtf',
      '.odt',
      '.pptx',
      '.xlsx',
    ],
    mimePatterns: ['application/pdf', 'application/vnd', 'text/plain', 'text/markdown'],
  },
  audio: {
    extensions: ['.mp3', '.m4a', '.wav', '.webm', '.ogg', '.flac', '.aac', '.wma'],
    mimePatterns: ['audio/'],
  },
  video: {
    extensions: ['.mp4', '.webm', '.mov', '.mkv', '.avi', '.wmv'],
    mimePatterns: ['video/'],
  },
  image: {
    extensions: ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.tiff', '.bmp', '.svg'],
    mimePatterns: ['image/'],
  },
  data: {
    extensions: ['.json', '.xml', '.csv', '.yaml', '.yml', '.toml', '.sql'],
    mimePatterns: ['application/json', 'application/xml', 'text/csv'],
  },
  archive: {
    extensions: ['.zip', '.tar', '.gz', '.rar', '.7z'],
    mimePatterns: ['application/zip', 'application/x-tar', 'application/gzip'],
  },
  unknown: { extensions: [], mimePatterns: [] },
};

/**
 * Map file category to suggested processing action
 */
const CATEGORY_ACTIONS: Record<FileCategory, ProcessingAction> = {
  code: 'index',
  document: 'extract',
  audio: 'transcribe',
  video: 'transcribe',
  image: 'ocr',
  data: 'parse',
  archive: 'expand',
  unknown: 'skip',
};

/**
 * Detect file category from name and MIME type
 */
function detectFileCategory(filename: string, mimeType: string): FileCategory {
  const ext = '.' + filename.split('.').pop()?.toLowerCase();

  for (const [category, patterns] of Object.entries(FILE_PATTERNS)) {
    if (category === 'unknown') continue;

    // Check extension
    if (patterns.extensions.includes(ext)) {
      return category as FileCategory;
    }

    // Check MIME type
    for (const pattern of patterns.mimePatterns) {
      if (mimeType.startsWith(pattern) || mimeType.includes(pattern)) {
        return category as FileCategory;
      }
    }
  }

  return 'unknown';
}

export interface UnifiedMediaUploaderProps {
  /** Called when files are uploaded */
  onUpload?: (items: UploadItem[]) => void;
  /** Called when processing completes */
  onComplete?: (items: UploadItem[]) => void;
  /** API base URL */
  apiBase?: string;
  /** Enable specific file categories */
  enableCategories?: FileCategory[];
  /** Maximum file size in MB */
  maxFileSizeMB?: number;
  /** Maximum total upload size in MB */
  maxTotalSizeMB?: number;
  /** Additional CSS classes */
  className?: string;
}

export function UnifiedMediaUploader({
  onUpload,
  onComplete,
  apiBase = '',
  enableCategories,
  maxFileSizeMB = 100,
  maxTotalSizeMB = 500,
  className = '',
}: UnifiedMediaUploaderProps) {
  const { isAdvanced } = useAdaptiveMode();
  const [queue, setQueue] = useState<UploadItem[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [activeTab, setActiveTab] = useState<'files' | 'record' | 'youtube' | 'cloud'>('files');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);

  // Calculate totals
  const totalSize = queue.reduce((sum, item) => sum + item.size, 0);
  const completedCount = queue.filter((i) => i.status === 'completed').length;
  const failedCount = queue.filter((i) => i.status === 'failed').length;
  const isUploading = queue.some((i) => i.status === 'uploading' || i.status === 'processing');

  /**
   * Add files to the queue
   */
  const addFiles = useCallback(
    (files: FileList | File[]) => {
      const newItems: UploadItem[] = [];

      for (const file of Array.from(files)) {
        // Check file size
        if (file.size > maxFileSizeMB * 1024 * 1024) {
          continue; // Skip oversized files
        }

        // Check total size
        const currentTotal = totalSize + newItems.reduce((s, i) => s + i.size, 0);
        if (currentTotal + file.size > maxTotalSizeMB * 1024 * 1024) {
          break; // Stop adding if total exceeded
        }

        const category = detectFileCategory(file.name, file.type);

        // Filter by enabled categories if specified
        if (enableCategories && !enableCategories.includes(category)) {
          continue;
        }

        newItems.push({
          id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
          file,
          name: file.name,
          size: file.size,
          category,
          suggestedAction: CATEGORY_ACTIONS[category],
          status: 'pending',
          progress: 0,
        });
      }

      if (newItems.length > 0) {
        setQueue((prev) => [...prev, ...newItems]);
        onUpload?.(newItems);
      }
    },
    [totalSize, maxFileSizeMB, maxTotalSizeMB, enableCategories, onUpload],
  );

  /**
   * Handle drag events
   */
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);

      const items = e.dataTransfer.items;
      const files: File[] = [];

      // Handle folder drops via webkitGetAsEntry
      const processEntry = async (entry: FileSystemEntry, path = ''): Promise<void> => {
        if (entry.isFile) {
          const fileEntry = entry as FileSystemFileEntry;
          return new Promise((resolve) => {
            fileEntry.file((file) => {
              // Create a new file with the path prefix
              const fullPath = path ? `${path}/${file.name}` : file.name;
              Object.defineProperty(file, 'webkitRelativePath', { value: fullPath });
              files.push(file);
              resolve();
            });
          });
        } else if (entry.isDirectory) {
          const dirEntry = entry as FileSystemDirectoryEntry;
          const reader = dirEntry.createReader();
          return new Promise((resolve) => {
            reader.readEntries(async (entries) => {
              for (const e of entries) {
                await processEntry(e, path ? `${path}/${entry.name}` : entry.name);
              }
              resolve();
            });
          });
        }
      };

      // Process all dropped items
      const processItems = async () => {
        for (let i = 0; i < items.length; i++) {
          const entry = items[i].webkitGetAsEntry?.();
          if (entry) {
            await processEntry(entry);
          } else {
            const file = items[i].getAsFile();
            if (file) files.push(file);
          }
        }
        addFiles(files);
      };

      processItems();
    },
    [addFiles],
  );

  /**
   * Handle file input change
   */
  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files) {
        addFiles(e.target.files);
      }
      e.target.value = ''; // Reset for re-selection
    },
    [addFiles],
  );

  /**
   * Remove an item from the queue
   */
  const removeItem = useCallback((id: string) => {
    setQueue((prev) => prev.filter((item) => item.id !== id));
  }, []);

  /**
   * Clear all completed/failed items
   */
  const clearCompleted = useCallback(() => {
    setQueue((prev) =>
      prev.filter((item) => item.status !== 'completed' && item.status !== 'failed'),
    );
  }, []);

  /**
   * Start uploading all pending items
   */
  const startUpload = useCallback(async () => {
    const pendingItems = queue.filter((item) => item.status === 'pending');

    for (const item of pendingItems) {
      // Update status to uploading
      setQueue((prev) =>
        prev.map((i) =>
          i.id === item.id ? { ...i, status: 'uploading' as const, progress: 0 } : i,
        ),
      );

      try {
        // Determine endpoint based on category
        let endpoint = '/api/documents/upload';
        if (item.category === 'audio' || item.category === 'video') {
          endpoint = '/api/transcription/upload';
        } else if (item.category === 'code') {
          endpoint = '/api/repository/upload';
        } else if (item.category === 'image') {
          endpoint = '/api/ocr/upload';
        }

        const formData = new FormData();
        formData.append('file', item.file);
        formData.append('action', item.suggestedAction);

        const response = await fetch(`${apiBase}${endpoint}`, { method: 'POST', body: formData });

        if (!response.ok) {
          throw new Error(`Upload failed: ${response.statusText}`);
        }

        const result = await response.json();

        // Update to processing status
        setQueue((prev) =>
          prev.map((i) =>
            i.id === item.id ? { ...i, status: 'processing' as const, progress: 50 } : i,
          ),
        );

        // Wait for processing if needed (poll for status)
        if (result.job_id) {
          let attempts = 0;
          while (attempts < 60) {
            await new Promise((r) => setTimeout(r, 2000));
            const statusRes = await fetch(`${apiBase}/api/jobs/${result.job_id}`);
            const statusData = await statusRes.json();

            if (statusData.status === 'completed') {
              setQueue((prev) =>
                prev.map((i) =>
                  i.id === item.id
                    ? { ...i, status: 'completed' as const, progress: 100, result: statusData }
                    : i,
                ),
              );
              break;
            } else if (statusData.status === 'failed') {
              throw new Error(statusData.error || 'Processing failed');
            }

            attempts++;
            setQueue((prev) =>
              prev.map((i) =>
                i.id === item.id ? { ...i, progress: Math.min(90, 50 + attempts) } : i,
              ),
            );
          }
        } else {
          // Immediate completion
          setQueue((prev) =>
            prev.map((i) =>
              i.id === item.id ? { ...i, status: 'completed' as const, progress: 100, result } : i,
            ),
          );
        }
      } catch (error) {
        setQueue((prev) =>
          prev.map((i) =>
            i.id === item.id
              ? {
                  ...i,
                  status: 'failed' as const,
                  error: error instanceof Error ? error.message : 'Upload failed',
                }
              : i,
          ),
        );
      }
    }

    // Call onComplete when all done
    const completed = queue.filter((i) => i.status === 'completed');
    if (completed.length > 0) {
      onComplete?.(completed);
    }
  }, [queue, apiBase, onComplete]);

  // Format file size
  const formatSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  // Get category icon
  const getCategoryIcon = (category: FileCategory): string => {
    const icons: Record<FileCategory, string> = {
      code: '<',
      document: ']',
      audio: '~',
      video: '>',
      image: '*',
      data: '#',
      archive: '[',
      unknown: '?',
    };
    return icons[category];
  };

  return (
    <div className={`border border-[var(--accent)]/30 bg-surface ${className}`}>
      {/* Header */}
      <div className="border-b border-[var(--accent)]/20 px-4 py-3 flex items-center justify-between">
        <h3 className="text-text font-bold font-theme-data">Upload Files</h3>
        {queue.length > 0 && (
          <span className="text-xs font-theme-data text-text-muted">
            {completedCount}/{queue.length} completed
            {failedCount > 0 && (
              <span className="text-[var(--crimson)] ml-2">{failedCount} failed</span>
            )}
          </span>
        )}
      </div>

      {/* Tabs */}
      <div className="flex border-b border-[var(--accent)]/10">
        {[
          { id: 'files', label: 'Files', icon: ']' },
          { id: 'record', label: 'Record', icon: '~' },
          { id: 'youtube', label: 'YouTube', icon: '>' },
          ...(isAdvanced ? [{ id: 'cloud', label: 'Cloud', icon: '@' }] : []),
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id as typeof activeTab)}
            className={`
              px-4 py-2 font-theme-data text-sm
              transition-colors
              ${
                activeTab === tab.id
                  ? 'text-[var(--accent)] border-b-2 border-[var(--accent)] -mb-px'
                  : 'text-text-muted hover:text-text'
              }
            `}
          >
            <span className="mr-1">{tab.icon}</span>
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="p-4">
        {/* Files tab - Drag and drop */}
        {activeTab === 'files' && (
          <>
            {/* Drop zone */}
            <div
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`
                border-2 border-dashed rounded-lg p-8
                text-center cursor-pointer
                transition-colors
                ${
                  isDragging
                    ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                    : 'border-[var(--accent)]/30 hover:border-[var(--accent)]/50'
                }
              `}
            >
              <div className="text-[var(--accent)] text-3xl mb-2">+</div>
              <p className="text-text font-theme-data text-sm mb-1">Drop files or folders here</p>
              <p className="text-text-muted text-xs">or click to browse</p>

              <input
                ref={fileInputRef}
                type="file"
                multiple
                onChange={handleFileSelect}
                className="hidden"
              />
              <input
                ref={folderInputRef}
                type="file"
                {...({ webkitdirectory: 'true' } as React.InputHTMLAttributes<HTMLInputElement>)}
                onChange={handleFileSelect}
                className="hidden"
              />
            </div>

            {/* Quick buttons */}
            <div className="flex gap-2 mt-3">
              <button
                onClick={() => folderInputRef.current?.click()}
                className="px-3 py-1.5 text-xs font-theme-data text-[var(--accent)] border border-[var(--accent)]/30 hover:bg-[var(--accent)]/10 transition-colors"
              >
                [Folder]
              </button>
              {isAdvanced && (
                <>
                  <button
                    onClick={() => fileInputRef.current?.click()}
                    className="px-3 py-1.5 text-xs font-theme-data text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/30 hover:bg-[var(--acid-cyan)]/10 transition-colors"
                  >
                    [URL]
                  </button>
                </>
              )}
            </div>
          </>
        )}

        {/* Record tab placeholder */}
        {activeTab === 'record' && (
          <div className="text-center py-8">
            <div className="text-[var(--accent)] text-3xl mb-2">~</div>
            <p className="text-text-muted text-sm">Voice recording component would go here</p>
          </div>
        )}

        {/* YouTube tab placeholder */}
        {activeTab === 'youtube' && (
          <div className="text-center py-8">
            <div className="text-[var(--accent)] text-3xl mb-2">&gt;</div>
            <p className="text-text-muted text-sm">YouTube input component would go here</p>
          </div>
        )}

        {/* Cloud tab placeholder */}
        {activeTab === 'cloud' && (
          <div className="text-center py-8">
            <div className="text-[var(--acid-cyan)] text-3xl mb-2">@</div>
            <p className="text-text-muted text-sm">Cloud storage picker would go here</p>
            <div className="flex justify-center gap-2 mt-4">
              <button className="px-3 py-1.5 text-xs font-theme-data text-text-muted border border-[var(--accent)]/20 hover:border-[var(--accent)]/40 transition-colors">
                Google Drive
              </button>
              <button className="px-3 py-1.5 text-xs font-theme-data text-text-muted border border-[var(--accent)]/20 hover:border-[var(--accent)]/40 transition-colors">
                OneDrive
              </button>
              <button className="px-3 py-1.5 text-xs font-theme-data text-text-muted border border-[var(--accent)]/20 hover:border-[var(--accent)]/40 transition-colors">
                Dropbox
              </button>
            </div>
          </div>
        )}

        {/* Upload queue */}
        {queue.length > 0 && (
          <div className="mt-4 border-t border-[var(--accent)]/10 pt-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-theme-data text-text-muted">
                Upload Queue ({formatSize(totalSize)})
              </span>
              <div className="flex gap-2">
                {(completedCount > 0 || failedCount > 0) && (
                  <button
                    onClick={clearCompleted}
                    className="text-xs font-theme-data text-text-muted hover:text-text transition-colors"
                  >
                    [Clear]
                  </button>
                )}
                {queue.some((i) => i.status === 'pending') && (
                  <button
                    onClick={startUpload}
                    disabled={isUploading}
                    className={`
                      px-3 py-1 text-xs font-theme-data
                      ${
                        isUploading
                          ? 'text-text-muted cursor-wait'
                          : 'text-[var(--accent)] hover:bg-[var(--accent)]/10'
                      }
                      border border-[var(--accent)]/30 transition-colors
                    `}
                  >
                    {isUploading ? '[Uploading...]' : '[Upload All]'}
                  </button>
                )}
              </div>
            </div>

            {/* Queue items */}
            <div className="space-y-2 max-h-48 overflow-y-auto">
              {queue.map((item) => (
                <div
                  key={item.id}
                  className={`
                    flex items-center gap-3 px-3 py-2 rounded
                    ${
                      item.status === 'completed'
                        ? 'bg-[var(--accent)]/10'
                        : item.status === 'failed'
                          ? 'bg-[var(--crimson)]/10'
                          : 'bg-surface'
                    }
                  `}
                >
                  {/* Category icon */}
                  <span className="text-[var(--accent)]/70 font-theme-data">
                    {getCategoryIcon(item.category)}
                  </span>

                  {/* File info */}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-theme-data text-text truncate">{item.name}</p>
                    <p className="text-xs text-text-muted">
                      {formatSize(item.size)} · {item.category}
                      {item.suggestedAction !== 'skip' && (
                        <span className="text-[var(--acid-cyan)] ml-1">
                          → {item.suggestedAction}
                        </span>
                      )}
                    </p>
                  </div>

                  {/* Progress/Status */}
                  <div className="w-24 text-right">
                    {item.status === 'uploading' || item.status === 'processing' ? (
                      <div className="w-full bg-[var(--accent)]/20 h-1 rounded">
                        <div
                          className="bg-[var(--accent)] h-1 rounded transition-all"
                          style={{ width: `${item.progress}%` }}
                        />
                      </div>
                    ) : item.status === 'completed' ? (
                      <span className="text-xs text-[var(--accent)]">Done</span>
                    ) : item.status === 'failed' ? (
                      <span className="text-xs text-[var(--crimson)]" title={item.error}>
                        Failed
                      </span>
                    ) : (
                      <span className="text-xs text-text-muted">Pending</span>
                    )}
                  </div>

                  {/* Remove button */}
                  {item.status !== 'uploading' && item.status !== 'processing' && (
                    <button
                      onClick={() => removeItem(item.id)}
                      className="text-text-muted hover:text-[var(--crimson)] transition-colors"
                    >
                      &times;
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Processing pipeline visualization (advanced mode) */}
      {isAdvanced && queue.length > 0 && (
        <div className="border-t border-[var(--accent)]/10 px-4 py-3">
          <div className="flex items-center gap-2 text-xs font-theme-data text-text-muted">
            <span>[Upload]</span>
            <span className="text-[var(--accent)]/50">→</span>
            <span>[Detect Type]</span>
            <span className="text-[var(--accent)]/50">→</span>
            <span>[Process]</span>
            <span className="text-[var(--accent)]/50">→</span>
            <span>[Index/Store]</span>
            <span className="text-[var(--accent)]/50">→</span>
            <span className="text-[var(--accent)]">[Ready]</span>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Compact upload button for inline use
 */
export function UploadButton({
  onUpload,
  label = 'Upload',
  accept,
  className = '',
}: {
  onUpload: (files: FileList) => void;
  label?: string;
  accept?: string;
  className?: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <>
      <button
        onClick={() => inputRef.current?.click()}
        className={`
          px-3 py-1.5 font-theme-data text-sm
          border border-[var(--accent)]/30
          text-[var(--accent)] hover:bg-[var(--accent)]/10
          transition-colors
          ${className}
        `}
      >
        [+] {label}
      </button>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={accept}
        onChange={(e) => e.target.files && onUpload(e.target.files)}
        className="hidden"
      />
    </>
  );
}
