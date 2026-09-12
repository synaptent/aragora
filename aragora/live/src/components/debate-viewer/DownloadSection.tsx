'use client';

import { useState, useCallback } from 'react';
import { API_BASE_URL } from '@/config';
import { AudioDownloadSection } from './AudioDownloadSection';

interface DownloadSectionProps {
  debateId: string;
  isCompleted?: boolean;
}

type ExportFormat = 'json' | 'csv' | 'md' | 'txt' | 'html';

interface FormatConfig {
  label: string;
  extension: string;
  mimeType: string;
}

const EXPORT_FORMATS: Record<ExportFormat, FormatConfig> = {
  json: { label: 'JSON', extension: 'json', mimeType: 'application/json' },
  csv: { label: 'CSV', extension: 'csv', mimeType: 'text/csv' },
  md: { label: 'Markdown', extension: 'md', mimeType: 'text/markdown' },
  txt: { label: 'Text', extension: 'txt', mimeType: 'text/plain' },
  html: { label: 'HTML', extension: 'html', mimeType: 'text/html' },
};

export function DownloadSection({ debateId, isCompleted = true }: DownloadSectionProps) {
  const [downloading, setDownloading] = useState<ExportFormat | null>(null);
  const [error, setError] = useState<string | null>(null);

  const downloadFormat = useCallback(
    async (format: ExportFormat) => {
      setDownloading(format);
      setError(null);

      try {
        const response = await fetch(`${API_BASE_URL}/api/debates/${debateId}/export/${format}`);

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.error || `Export failed (${response.status})`);
        }

        // Get the content
        const content = await response.text();
        const config = EXPORT_FORMATS[format];

        // Create blob and download
        const blob = new Blob([content], { type: config.mimeType });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `debate-${debateId}.${config.extension}`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Download failed');
      } finally {
        setDownloading(null);
      }
    },
    [debateId],
  );

  if (!isCompleted) {
    return (
      <div className="text-xs font-theme-data text-text-muted">
        [EXPORTS AVAILABLE AFTER DEBATE COMPLETES]
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Section Header */}
      <div className="text-xs font-theme-data text-text-muted uppercase tracking-wider">
        Download Transcript
      </div>

      {/* Error Display */}
      {error && (
        <div className="text-xs font-theme-data text-red-400 bg-red-900/20 px-2 py-1 border border-red-500/30">
          {error}
        </div>
      )}

      {/* Export Format Buttons */}
      <div className="flex flex-wrap gap-2">
        {(Object.entries(EXPORT_FORMATS) as [ExportFormat, FormatConfig][]).map(
          ([format, config]) => (
            <button
              key={format}
              onClick={() => downloadFormat(format)}
              disabled={downloading !== null}
              className={`
                px-3 py-1.5 text-xs font-theme-data border transition-colors
                ${
                  downloading === format
                    ? 'bg-accent/20 border-accent text-accent animate-pulse'
                    : 'bg-bg border-border text-text-muted hover:border-accent/40 hover:text-accent'
                }
                disabled:opacity-50 disabled:cursor-not-allowed
              `}
            >
              {downloading === format ? `[${config.label}...]` : `[${config.label}]`}
            </button>
          ),
        )}
      </div>

      {/* Audio Section Divider */}
      <div className="border-t border-border/50 pt-3">
        <div className="text-xs font-theme-data text-text-muted uppercase tracking-wider mb-2">
          Audio Podcast
        </div>
        <AudioDownloadSection debateId={debateId} />
      </div>
    </div>
  );
}

export default DownloadSection;
