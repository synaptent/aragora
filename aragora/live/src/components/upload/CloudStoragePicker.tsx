'use client';

import { useState, useCallback, useEffect } from 'react';

/**
 * Supported cloud storage providers
 */
export type CloudProvider = 'google_drive' | 'onedrive' | 'dropbox' | 's3';

/**
 * Cloud file item
 */
export interface CloudFile {
  id: string;
  name: string;
  path: string;
  size: number;
  mimeType: string;
  modifiedTime?: string;
  isFolder: boolean;
  provider: CloudProvider;
  webUrl?: string;
  thumbnailUrl?: string;
}

/**
 * API response file format
 */
interface ApiCloudFile {
  id: string;
  name: string;
  path?: string;
  size?: number;
  mime_type?: string;
  modified_time?: string;
  is_folder?: boolean;
  web_url?: string;
  thumbnail_url?: string;
}

/**
 * Provider configuration
 */
interface ProviderConfig {
  id: CloudProvider;
  name: string;
  icon: string;
  color: string;
  connected: boolean;
  accountName?: string;
}

/**
 * Props for CloudStoragePicker
 */
export interface CloudStoragePickerProps {
  /** Called when files are selected */
  onSelect: (files: CloudFile[]) => void;
  /** Called when picker is closed */
  onClose?: () => void;
  /** Allow multiple selection */
  multiple?: boolean;
  /** Filter by file extensions */
  acceptExtensions?: string[];
  /** API base URL */
  apiBase?: string;
  /** Additional CSS classes */
  className?: string;
}

/**
 * Cloud storage file picker component.
 *
 * Supports:
 * - Google Drive
 * - Microsoft OneDrive
 * - Dropbox
 * - S3 (configured buckets)
 */
export function CloudStoragePicker({
  onSelect,
  onClose,
  multiple = false,
  acceptExtensions,
  apiBase = '/api',
  className = '',
}: CloudStoragePickerProps) {
  const [providers, setProviders] = useState<ProviderConfig[]>([
    { id: 'google_drive', name: 'Google Drive', icon: '📁', color: '#4285f4', connected: false },
    { id: 'onedrive', name: 'OneDrive', icon: '☁️', color: '#0078d4', connected: false },
    { id: 'dropbox', name: 'Dropbox', icon: '📦', color: '#0061ff', connected: false },
  ]);

  const [activeProvider, setActiveProvider] = useState<CloudProvider | null>(null);
  const [, setCurrentPath] = useState<string>('/');
  const [files, setFiles] = useState<CloudFile[]>([]);
  const [selectedFiles, setSelectedFiles] = useState<CloudFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [breadcrumbs, setBreadcrumbs] = useState<{ name: string; path: string }[]>([]);

  const checkProviderStatus = useCallback(async () => {
    try {
      const response = await fetch(`${apiBase}/cloud/status`);
      if (response.ok) {
        const status = await response.json();
        setProviders((prev) =>
          prev.map((p) => ({
            ...p,
            connected: status[p.id]?.connected ?? false,
            accountName: status[p.id]?.account_name,
          })),
        );
      }
    } catch {
      // Silently fail - providers just show as disconnected
    }
  }, [apiBase]);

  // Check connection status on mount
  useEffect(() => {
    checkProviderStatus();
  }, [checkProviderStatus]);

  const connectProvider = async (provider: CloudProvider) => {
    try {
      const response = await fetch(`${apiBase}/cloud/${provider}/auth/url`);
      if (response.ok) {
        const { url } = await response.json();
        // Open OAuth popup
        const popup = window.open(url, 'oauth', 'width=600,height=700');
        // Poll for completion
        const checkPopup = setInterval(() => {
          if (popup?.closed) {
            clearInterval(checkPopup);
            checkProviderStatus();
          }
        }, 1000);
      }
    } catch {
      setError(`Failed to connect to ${provider}`);
    }
  };

  const loadFiles = useCallback(
    async (provider: CloudProvider, path: string) => {
      setLoading(true);
      setError(null);

      try {
        const params = new URLSearchParams({ path });
        const response = await fetch(`${apiBase}/cloud/${provider}/files?${params}`);

        if (!response.ok) {
          throw new Error('Failed to load files');
        }

        const data = await response.json();
        const items: CloudFile[] = (data.files as ApiCloudFile[]).map((f) => ({
          id: f.id,
          name: f.name,
          path: f.path || path + '/' + f.name,
          size: f.size || 0,
          mimeType: f.mime_type || 'application/octet-stream',
          modifiedTime: f.modified_time,
          isFolder: f.is_folder || f.mime_type === 'application/vnd.google-apps.folder',
          provider,
          webUrl: f.web_url,
          thumbnailUrl: f.thumbnail_url,
        }));

        // Filter by accepted extensions if provided
        const filtered = acceptExtensions
          ? items.filter((f) => {
              if (f.isFolder) return true;
              const ext = '.' + f.name.split('.').pop()?.toLowerCase();
              return acceptExtensions.includes(ext);
            })
          : items;

        // Sort: folders first, then by name
        filtered.sort((a, b) => {
          if (a.isFolder !== b.isFolder) return a.isFolder ? -1 : 1;
          return a.name.localeCompare(b.name);
        });

        setFiles(filtered);
        setCurrentPath(path);

        // Update breadcrumbs
        const parts = path.split('/').filter(Boolean);
        setBreadcrumbs([
          { name: 'Root', path: '/' },
          ...parts.map((name, i) => ({ name, path: '/' + parts.slice(0, i + 1).join('/') })),
        ]);
      } catch {
        setError('Failed to load files');
      } finally {
        setLoading(false);
      }
    },
    [apiBase, acceptExtensions],
  );

  const handleProviderClick = (provider: ProviderConfig) => {
    if (provider.connected) {
      setActiveProvider(provider.id);
      loadFiles(provider.id, '/');
    } else {
      connectProvider(provider.id);
    }
  };

  const handleFileClick = (file: CloudFile) => {
    if (file.isFolder) {
      loadFiles(file.provider, file.path);
    } else {
      if (multiple) {
        setSelectedFiles((prev) => {
          const exists = prev.some((f) => f.id === file.id);
          return exists ? prev.filter((f) => f.id !== file.id) : [...prev, file];
        });
      } else {
        setSelectedFiles([file]);
      }
    }
  };

  const handleConfirm = () => {
    if (selectedFiles.length > 0) {
      onSelect(selectedFiles);
    }
  };

  const handleBack = () => {
    if (breadcrumbs.length > 1) {
      const parentPath = breadcrumbs[breadcrumbs.length - 2].path;
      loadFiles(activeProvider!, parentPath);
    } else {
      setActiveProvider(null);
      setFiles([]);
      setSelectedFiles([]);
    }
  };

  const formatSize = (bytes: number): string => {
    if (bytes === 0) return '-';
    const units = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
  };

  return (
    <div
      className={`bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-700 ${className}`}
    >
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center gap-2">
          {activeProvider && (
            <button
              onClick={handleBack}
              className="p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M15 19l-7-7 7-7"
                />
              </svg>
            </button>
          )}
          <h3 className="font-semibold">
            {activeProvider
              ? providers.find((p) => p.id === activeProvider)?.name
              : 'Select Cloud Storage'}
          </h3>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        )}
      </div>

      {/* Breadcrumbs */}
      {activeProvider && breadcrumbs.length > 0 && (
        <div className="px-4 py-2 border-b border-gray-100 dark:border-gray-800 text-sm">
          <div className="flex items-center gap-1 text-gray-500 dark:text-gray-400 overflow-x-auto">
            {breadcrumbs.map((crumb, i) => (
              <span key={crumb.path} className="flex items-center">
                {i > 0 && <span className="mx-1">/</span>}
                <button
                  onClick={() => loadFiles(activeProvider, crumb.path)}
                  className="hover:text-blue-600 dark:hover:text-blue-400"
                >
                  {crumb.name}
                </button>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Content */}
      <div className="p-4 min-h-[300px] max-h-[400px] overflow-y-auto">
        {error && <div className="text-red-600 dark:text-red-400 text-center py-4">{error}</div>}

        {!activeProvider && (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {providers.map((provider) => (
              <button
                key={provider.id}
                onClick={() => handleProviderClick(provider)}
                className="flex flex-col items-center gap-2 p-6 border border-gray-200 dark:border-gray-700 rounded-lg hover:border-blue-500 dark:hover:border-blue-400 transition-colors"
              >
                <span className="text-3xl">{provider.icon}</span>
                <span className="font-medium">{provider.name}</span>
                {provider.connected ? (
                  <span className="text-xs text-green-600 dark:text-green-400">
                    {provider.accountName || 'Connected'}
                  </span>
                ) : (
                  <span className="text-xs text-gray-500">Click to connect</span>
                )}
              </button>
            ))}
          </div>
        )}

        {activeProvider && loading && (
          <div className="flex items-center justify-center py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
          </div>
        )}

        {activeProvider && !loading && files.length === 0 && (
          <div className="text-center py-8 text-gray-500 dark:text-gray-400">No files found</div>
        )}

        {activeProvider && !loading && files.length > 0 && (
          <div className="space-y-1">
            {files.map((file) => (
              <div
                key={file.id}
                onClick={() => handleFileClick(file)}
                className={`flex items-center gap-3 p-2 rounded cursor-pointer transition-colors ${
                  selectedFiles.some((f) => f.id === file.id)
                    ? 'bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800'
                    : 'hover:bg-gray-50 dark:hover:bg-gray-800'
                }`}
              >
                {/* Icon */}
                <span className="text-xl">{file.isFolder ? '📁' : getFileIcon(file.mimeType)}</span>

                {/* Name and details */}
                <div className="flex-1 min-w-0">
                  <div className="truncate font-medium">{file.name}</div>
                  {!file.isFolder && (
                    <div className="text-xs text-gray-500 dark:text-gray-400">
                      {formatSize(file.size)}
                      {file.modifiedTime &&
                        ` • ${new Date(file.modifiedTime).toLocaleDateString()}`}
                    </div>
                  )}
                </div>

                {/* Checkbox for multiple selection */}
                {multiple && !file.isFolder && (
                  <input
                    type="checkbox"
                    checked={selectedFiles.some((f) => f.id === file.id)}
                    onChange={() => handleFileClick(file)}
                    className="h-4 w-4 text-blue-600 rounded border-gray-300"
                    onClick={(e) => e.stopPropagation()}
                  />
                )}

                {/* Arrow for folders */}
                {file.isFolder && (
                  <svg
                    className="w-5 h-5 text-gray-400"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M9 5l7 7-7 7"
                    />
                  </svg>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      {activeProvider && selectedFiles.length > 0 && (
        <div className="flex items-center justify-between p-4 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800">
          <span className="text-sm text-gray-600 dark:text-gray-400">
            {selectedFiles.length} file{selectedFiles.length > 1 ? 's' : ''} selected
          </span>
          <button
            onClick={handleConfirm}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
          >
            Import Selected
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * Get icon for file type
 */
function getFileIcon(mimeType: string): string {
  if (mimeType.startsWith('image/')) return '🖼️';
  if (mimeType.startsWith('video/')) return '🎬';
  if (mimeType.startsWith('audio/')) return '🎵';
  if (mimeType.includes('pdf')) return '📄';
  if (mimeType.includes('spreadsheet') || mimeType.includes('excel')) return '📊';
  if (mimeType.includes('presentation') || mimeType.includes('powerpoint')) return '📽️';
  if (mimeType.includes('document') || mimeType.includes('word')) return '📝';
  if (mimeType.includes('text')) return '📃';
  if (mimeType.includes('zip') || mimeType.includes('archive')) return '🗜️';
  if (mimeType.includes('javascript') || mimeType.includes('python') || mimeType.includes('code'))
    return '💻';
  return '📎';
}

export default CloudStoragePicker;
