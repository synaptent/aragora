'use client';

import { useState, useRef, useCallback, useEffect } from 'react';

interface FolderFile {
  path: string;
  name: string;
  size: number;
  webkitRelativePath?: string;
}

interface ScanResult {
  rootPath: string;
  totalFilesFound: number;
  includedCount: number;
  excludedCount: number;
  includedSizeBytes: number;
  includedFiles: Array<{
    path: string;
    absolutePath: string;
    sizeBytes: number;
    extension: string;
    mimeType: string;
  }>;
  excludedFiles: Array<{ path: string; reason: string; details: string }>;
  warnings: string[];
}

interface UploadProgress {
  folderId: string;
  status: 'pending' | 'scanning' | 'uploading' | 'completed' | 'failed';
  scan: {
    totalFilesFound: number;
    includedCount: number;
    excludedCount: number;
    totalSizeBytes: number;
  };
  progress: {
    filesUploaded: number;
    filesFailed: number;
    bytesUploaded: number;
    percentComplete: number;
  };
  results: {
    documentIds: string[];
    errors: Array<{ file?: string; error: string }>;
    errorCount: number;
  };
}

interface FolderUploadDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onComplete?: (documentIds: string[]) => void;
  apiBase?: string;
  authToken?: string;
}

const DEFAULT_EXCLUDE_PATTERNS = [
  '**/.git/**',
  '**/node_modules/**',
  '**/__pycache__/**',
  '**/.venv/**',
  '**/dist/**',
  '**/build/**',
  '**/*.pyc',
  '**/.DS_Store',
];

export function FolderUploadDialog({
  isOpen,
  onClose,
  onComplete,
  apiBase = '',
  authToken = '',
}: FolderUploadDialogProps) {
  const [selectedFiles, setSelectedFiles] = useState<FolderFile[]>([]);
  const [folderPath, setFolderPath] = useState<string>('');
  const [scanResult, setScanResult] = useState<ScanResult | null>(null);
  const [uploadProgress, setUploadProgress] = useState<UploadProgress | null>(null);
  const [status, setStatus] = useState<'idle' | 'scanning' | 'uploading' | 'completed' | 'error'>(
    'idle',
  );
  const [error, setError] = useState<string | null>(null);
  const [showExcluded, setShowExcluded] = useState(false);

  // Config state
  const [maxDepth, setMaxDepth] = useState(10);
  const [maxFileSizeMb, setMaxFileSizeMb] = useState(100);
  const [maxTotalSizeMb, setMaxTotalSizeMb] = useState(500);
  const [maxFileCount, setMaxFileCount] = useState(1000);
  const [excludePatterns, setExcludePatterns] = useState<string[]>(DEFAULT_EXCLUDE_PATTERNS);
  const [newPattern, setNewPattern] = useState('');

  const folderInputRef = useRef<HTMLInputElement>(null);
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Clean up polling on unmount
  useEffect(() => {
    const interval = pollIntervalRef.current;
    return () => {
      if (interval) {
        clearInterval(interval);
      }
    };
  }, []);

  const handleFolderSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    // Extract folder path from first file's webkitRelativePath
    const firstFile = files[0];
    const relativePath = firstFile.webkitRelativePath || '';
    const folderName = relativePath.split('/')[0] || 'Selected Folder';

    setFolderPath(folderName);

    // Convert FileList to array of FolderFile
    const folderFiles: FolderFile[] = Array.from(files).map((file) => ({
      path: file.webkitRelativePath || file.name,
      name: file.name,
      size: file.size,
      webkitRelativePath: file.webkitRelativePath,
    }));

    setSelectedFiles(folderFiles);
    setScanResult(null);
    setStatus('idle');
    setError(null);
  }, []);

  const formatSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
  };

  // Client-side folder scan (for preview when using browser file picker)
  const scanFolderClient = useCallback(() => {
    if (selectedFiles.length === 0) return;

    setStatus('scanning');

    // Simulate scan by applying patterns to selected files
    const includedFiles: ScanResult['includedFiles'] = [];
    const excludedFiles: ScanResult['excludedFiles'] = [];
    let includedSize = 0;

    for (const file of selectedFiles) {
      const path = file.path;

      // Check exclusion patterns
      let excluded = false;
      let excludeReason = '';
      let excludeDetails = '';

      for (const pattern of excludePatterns) {
        if (matchGlobPattern(path, pattern)) {
          excluded = true;
          excludeReason = 'pattern';
          excludeDetails = `Matched pattern: ${pattern}`;
          break;
        }
      }

      // Check file size
      if (!excluded && file.size > maxFileSizeMb * 1024 * 1024) {
        excluded = true;
        excludeReason = 'size';
        excludeDetails = `File size ${formatSize(file.size)} exceeds limit of ${maxFileSizeMb}MB`;
      }

      // Check total count
      if (!excluded && includedFiles.length >= maxFileCount) {
        excluded = true;
        excludeReason = 'count';
        excludeDetails = `Exceeds max file count of ${maxFileCount}`;
      }

      // Check total size
      if (!excluded && includedSize + file.size > maxTotalSizeMb * 1024 * 1024) {
        excluded = true;
        excludeReason = 'size';
        excludeDetails = `Would exceed total size limit of ${maxTotalSizeMb}MB`;
      }

      if (excluded) {
        excludedFiles.push({ path, reason: excludeReason, details: excludeDetails });
      } else {
        const ext = '.' + file.name.split('.').pop()?.toLowerCase();
        includedFiles.push({
          path,
          absolutePath: path,
          sizeBytes: file.size,
          extension: ext,
          mimeType: getMimeType(ext),
        });
        includedSize += file.size;
      }
    }

    setScanResult({
      rootPath: folderPath,
      totalFilesFound: selectedFiles.length,
      includedCount: includedFiles.length,
      excludedCount: excludedFiles.length,
      includedSizeBytes: includedSize,
      includedFiles,
      excludedFiles,
      warnings: [],
    });
    setStatus('idle');
  }, [selectedFiles, excludePatterns, maxFileSizeMb, maxTotalSizeMb, maxFileCount, folderPath]);

  // Simple glob pattern matching
  const matchGlobPattern = (path: string, pattern: string): boolean => {
    // Convert glob pattern to regex
    const regexPattern = pattern
      .replace(/\*\*/g, '___GLOBSTAR___')
      .replace(/\*/g, '[^/]*')
      .replace(/___GLOBSTAR___/g, '.*')
      .replace(/\?/g, '.');

    try {
      const regex = new RegExp(
        `^${regexPattern}$|/${regexPattern}$|^${regexPattern}/|/${regexPattern}/`,
      );
      return regex.test(path);
    } catch {
      return false;
    }
  };

  const getMimeType = (ext: string): string => {
    const mimeTypes: Record<string, string> = {
      '.pdf': 'application/pdf',
      '.txt': 'text/plain',
      '.md': 'text/markdown',
      '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      '.doc': 'application/msword',
    };
    return mimeTypes[ext.toLowerCase()] || 'application/octet-stream';
  };

  const addPattern = () => {
    if (newPattern.trim() && !excludePatterns.includes(newPattern.trim())) {
      setExcludePatterns([...excludePatterns, newPattern.trim()]);
      setNewPattern('');
    }
  };

  const removePattern = (pattern: string) => {
    setExcludePatterns(excludePatterns.filter((p) => p !== pattern));
  };

  const startUpload = useCallback(async () => {
    if (!scanResult || scanResult.includedCount === 0) {
      setError('No files to upload');
      return;
    }

    setStatus('uploading');
    setError(null);

    try {
      // For browser-based folder selection, we need to upload files directly
      // since the backend can't access local filesystem paths
      const formData = new FormData();
      const input = folderInputRef.current;

      if (!input?.files) {
        throw new Error('No files selected');
      }

      // Filter to only included files
      const includedPaths = new Set(scanResult.includedFiles.map((f) => f.path));
      const filesToUpload: File[] = [];

      for (let i = 0; i < input.files.length; i++) {
        const file = input.files[i];
        const relativePath = file.webkitRelativePath || file.name;
        if (includedPaths.has(relativePath)) {
          filesToUpload.push(file);
        }
      }

      // Upload in batch
      for (const file of filesToUpload) {
        formData.append('files', file);
      }

      // Add metadata
      formData.append('folder_name', folderPath);
      formData.append(
        'config',
        JSON.stringify({ maxDepth, excludePatterns, maxFileSizeMb, maxTotalSizeMb, maxFileCount }),
      );

      const response = await fetch(`${apiBase}/api/documents/batch`, {
        method: 'POST',
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
        body: formData,
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || 'Upload failed');
      }

      const data = await response.json();

      setUploadProgress({
        folderId: data.batch_id || 'local',
        status: 'completed',
        scan: {
          totalFilesFound: scanResult.totalFilesFound,
          includedCount: scanResult.includedCount,
          excludedCount: scanResult.excludedCount,
          totalSizeBytes: scanResult.includedSizeBytes,
        },
        progress: {
          filesUploaded: data.processed || filesToUpload.length,
          filesFailed: data.failed || 0,
          bytesUploaded: scanResult.includedSizeBytes,
          percentComplete: 100,
        },
        results: {
          documentIds: data.document_ids || [],
          errors: data.errors || [],
          errorCount: data.failed || 0,
        },
      });

      setStatus('completed');
      onComplete?.(data.document_ids || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed');
      setStatus('error');
    }
  }, [
    scanResult,
    apiBase,
    authToken,
    folderPath,
    maxDepth,
    excludePatterns,
    maxFileSizeMb,
    maxTotalSizeMb,
    maxFileCount,
    onComplete,
  ]);

  const handleClose = () => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
    }
    setSelectedFiles([]);
    setFolderPath('');
    setScanResult(null);
    setUploadProgress(null);
    setStatus('idle');
    setError(null);
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="folder-upload-title"
    >
      <div className="bg-surface border border-border rounded-lg w-full max-w-3xl max-h-[90vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="p-4 border-b border-border flex items-center justify-between">
          <h2 id="folder-upload-title" className="text-lg font-theme-data font-bold">
            FOLDER UPLOAD
          </h2>
          <button
            onClick={handleClose}
            className="text-muted hover:text-foreground"
            aria-label="Close folder upload dialog"
          >
            <svg
              className="w-5 h-5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {/* Folder Selection */}
          {!selectedFiles.length && (
            <div
              className="border-2 border-dashed border-border rounded-lg p-8 text-center cursor-pointer hover:border-accent/50 transition-colors focus:outline-none focus:border-accent"
              onClick={() => folderInputRef.current?.click()}
              onKeyDown={(e) =>
                (e.key === 'Enter' || e.key === ' ') && folderInputRef.current?.click()
              }
              role="button"
              tabIndex={0}
              aria-label="Select folder to upload"
            >
              <input
                ref={folderInputRef}
                type="file"
                webkitdirectory="true"
                directory="true"
                multiple
                onChange={handleFolderSelect}
                className="hidden"
                aria-label="Folder file picker"
              />
              <div className="text-4xl mb-3" aria-hidden="true">
                📂
              </div>
              <div className="text-lg font-theme-data mb-2">SELECT FOLDER</div>
              <div className="text-sm text-muted">Click to select a folder to upload</div>
            </div>
          )}

          {/* Folder Selected */}
          {selectedFiles.length > 0 && !scanResult && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="font-theme-data font-bold">{folderPath}</div>
                  <div className="text-sm text-muted">{selectedFiles.length} files found</div>
                </div>
                <button
                  onClick={() => {
                    setSelectedFiles([]);
                    setFolderPath('');
                    if (folderInputRef.current) folderInputRef.current.value = '';
                  }}
                  className="text-sm text-muted hover:text-foreground"
                >
                  Change
                </button>
              </div>

              {/* Config Section */}
              <div className="card p-4 space-y-4">
                <div className="text-sm font-theme-data font-bold">UPLOAD SETTINGS</div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs text-muted">Max Depth</label>
                    <input
                      type="number"
                      value={maxDepth}
                      onChange={(e) => setMaxDepth(parseInt(e.target.value) || 10)}
                      className="input w-full mt-1"
                      min={1}
                      max={100}
                    />
                  </div>
                  <div>
                    <label className="text-xs text-muted">Max Files</label>
                    <input
                      type="number"
                      value={maxFileCount}
                      onChange={(e) => setMaxFileCount(parseInt(e.target.value) || 1000)}
                      className="input w-full mt-1"
                      min={1}
                    />
                  </div>
                  <div>
                    <label className="text-xs text-muted">Max File Size (MB)</label>
                    <input
                      type="number"
                      value={maxFileSizeMb}
                      onChange={(e) => setMaxFileSizeMb(parseInt(e.target.value) || 100)}
                      className="input w-full mt-1"
                      min={1}
                    />
                  </div>
                  <div>
                    <label className="text-xs text-muted">Max Total Size (MB)</label>
                    <input
                      type="number"
                      value={maxTotalSizeMb}
                      onChange={(e) => setMaxTotalSizeMb(parseInt(e.target.value) || 500)}
                      className="input w-full mt-1"
                      min={1}
                    />
                  </div>
                </div>

                {/* Exclude Patterns */}
                <div>
                  <label className="text-xs text-muted">Exclude Patterns (gitignore-style)</label>
                  <div className="flex gap-2 mt-1">
                    <input
                      type="text"
                      value={newPattern}
                      onChange={(e) => setNewPattern(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && addPattern()}
                      placeholder="e.g. **/*.log"
                      className="input flex-1"
                    />
                    <button
                      onClick={addPattern}
                      className="btn btn-secondary"
                      aria-label="Add exclude pattern"
                    >
                      Add
                    </button>
                  </div>
                  <div className="flex flex-wrap gap-2 mt-2">
                    {excludePatterns.map((pattern) => (
                      <span
                        key={pattern}
                        className="inline-flex items-center gap-1 px-2 py-1 bg-surface border border-border rounded text-xs font-theme-data"
                      >
                        {pattern}
                        <button
                          onClick={() => removePattern(pattern)}
                          className="text-muted hover:text-foreground"
                          aria-label={`Remove pattern ${pattern}`}
                        >
                          x
                        </button>
                      </span>
                    ))}
                  </div>
                </div>
              </div>

              <button onClick={scanFolderClient} className="btn btn-primary w-full">
                SCAN FOLDER
              </button>
            </div>
          )}

          {/* Scan Results */}
          {scanResult && status !== 'uploading' && status !== 'completed' && (
            <div className="space-y-4">
              <div className="grid grid-cols-4 gap-4">
                <div className="card p-3 text-center">
                  <div className="text-2xl font-bold">{scanResult.totalFilesFound}</div>
                  <div className="text-xs text-muted">Total Found</div>
                </div>
                <div className="card p-3 text-center">
                  <div className="text-2xl font-bold text-[var(--accent)]">
                    {scanResult.includedCount}
                  </div>
                  <div className="text-xs text-muted">To Upload</div>
                </div>
                <div className="card p-3 text-center">
                  <div className="text-2xl font-bold text-[var(--acid-yellow)]">
                    {scanResult.excludedCount}
                  </div>
                  <div className="text-xs text-muted">Excluded</div>
                </div>
                <div className="card p-3 text-center">
                  <div className="text-2xl font-bold">
                    {formatSize(scanResult.includedSizeBytes)}
                  </div>
                  <div className="text-xs text-muted">Total Size</div>
                </div>
              </div>

              {/* File List Preview */}
              <div className="card p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="text-sm font-theme-data font-bold">
                    FILES TO UPLOAD ({scanResult.includedCount})
                  </div>
                  {scanResult.excludedCount > 0 && (
                    <button
                      onClick={() => setShowExcluded(!showExcluded)}
                      className="text-xs text-muted hover:text-foreground"
                    >
                      {showExcluded
                        ? 'Show included'
                        : `Show excluded (${scanResult.excludedCount})`}
                    </button>
                  )}
                </div>
                <div className="max-h-48 overflow-y-auto space-y-1">
                  {(showExcluded
                    ? scanResult.excludedFiles
                    : scanResult.includedFiles.slice(0, 50)
                  ).map((file, i) => (
                    <div
                      key={i}
                      className="flex items-center justify-between text-xs font-theme-data py-1 border-b border-border last:border-0"
                    >
                      <span
                        className={`truncate flex-1 ${showExcluded ? 'text-muted line-through' : ''}`}
                      >
                        {file.path}
                      </span>
                      {showExcluded && 'details' in file && (
                        <span className="text-[var(--acid-yellow)] ml-2">{file.details}</span>
                      )}
                      {!showExcluded && 'sizeBytes' in file && (
                        <span className="text-muted ml-2">{formatSize(file.sizeBytes)}</span>
                      )}
                    </div>
                  ))}
                  {!showExcluded && scanResult.includedFiles.length > 50 && (
                    <div className="text-xs text-muted py-1">
                      ... and {scanResult.includedFiles.length - 50} more files
                    </div>
                  )}
                </div>
              </div>

              {/* Warnings */}
              {scanResult.warnings.length > 0 && (
                <div className="bg-acid-yellow/10 border border-acid-yellow/30 rounded p-3">
                  <div className="text-sm font-theme-data font-bold text-[var(--acid-yellow)] mb-1">
                    WARNINGS
                  </div>
                  {scanResult.warnings.map((warning, i) => (
                    <div key={i} className="text-xs text-[var(--acid-yellow)]">
                      {warning}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Upload Progress */}
          {status === 'uploading' && (
            <div className="card p-4 text-center">
              <div className="animate-spin w-8 h-8 border-2 border-accent border-t-transparent rounded-full mx-auto mb-3" />
              <div className="font-theme-data">UPLOADING...</div>
              <div className="text-sm text-muted">Please wait while files are being uploaded</div>
            </div>
          )}

          {/* Upload Complete */}
          {status === 'completed' && uploadProgress && (
            <div className="card p-4 text-center">
              <div className="text-4xl mb-3">✅</div>
              <div className="font-theme-data text-lg mb-2">UPLOAD COMPLETE</div>
              <div className="text-sm text-muted">
                {uploadProgress.progress.filesUploaded} files uploaded successfully
                {uploadProgress.progress.filesFailed > 0 && (
                  <span className="text-acid-red">
                    {' '}
                    ({uploadProgress.progress.filesFailed} failed)
                  </span>
                )}
              </div>
              {uploadProgress.results.errorCount > 0 && (
                <div className="mt-2 text-xs text-acid-red">
                  {uploadProgress.results.errors.slice(0, 3).map((err, i) => (
                    <div key={i}>
                      {err.file}: {err.error}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="bg-acid-red/10 border border-acid-red/30 rounded p-3 text-acid-red text-sm">
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-border flex justify-end gap-3">
          <button onClick={handleClose} className="btn btn-secondary">
            {status === 'completed' ? 'CLOSE' : 'CANCEL'}
          </button>
          {scanResult && status !== 'uploading' && status !== 'completed' && (
            <button
              onClick={startUpload}
              className="btn btn-primary"
              disabled={scanResult.includedCount === 0}
            >
              UPLOAD {scanResult.includedCount} FILES
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
