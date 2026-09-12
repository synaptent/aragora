'use client';

/**
 * Report Export Modal Component
 *
 * Provides export functionality for audit findings:
 * - Format selection (JSON, Markdown, HTML, CSV)
 * - Severity/category filtering
 * - Download or copy to clipboard
 */

import { useState, useCallback } from 'react';
import { useBackend } from '@/components/BackendSelector';
import { useAuth } from '@/context/AuthContext';

export type ExportFormat = 'json' | 'markdown' | 'html' | 'csv';

interface ReportExportModalProps {
  sessionId: string;
  findingsCount: number;
  severityCounts?: Record<string, number>;
  categories?: string[];
  isOpen: boolean;
  onClose: () => void;
}

const FORMAT_INFO: Record<ExportFormat, { label: string; description: string; extension: string }> =
  {
    json: {
      label: 'JSON',
      description: 'Structured data format, ideal for programmatic access',
      extension: 'json',
    },
    markdown: {
      label: 'Markdown',
      description: 'Human-readable format, great for documentation',
      extension: 'md',
    },
    html: {
      label: 'HTML',
      description: 'Styled report for viewing in browsers',
      extension: 'html',
    },
    csv: { label: 'CSV', description: 'Spreadsheet format for data analysis', extension: 'csv' },
  };

const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low', 'info'];

export function ReportExportModal({
  sessionId,
  findingsCount,
  severityCounts = {},
  categories = [],
  isOpen,
  onClose,
}: ReportExportModalProps) {
  const { config: backendConfig } = useBackend();
  const { tokens } = useAuth();

  const [format, setFormat] = useState<ExportFormat>('json');
  const [selectedSeverities, setSelectedSeverities] = useState<Set<string>>(
    new Set(SEVERITY_ORDER),
  );
  const [selectedCategories, setSelectedCategories] = useState<Set<string>>(new Set(categories));
  const [includeEvidence, setIncludeEvidence] = useState(true);
  const [includeMetadata, setIncludeMetadata] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  // Calculate filtered count
  const filteredCount = Object.entries(severityCounts)
    .filter(([sev]) => selectedSeverities.has(sev))
    .reduce((sum, [, count]) => sum + count, 0);

  // Toggle severity filter
  const toggleSeverity = (severity: string) => {
    setSelectedSeverities((prev) => {
      const next = new Set(prev);
      if (next.has(severity)) {
        next.delete(severity);
      } else {
        next.add(severity);
      }
      return next;
    });
  };

  // Toggle category filter
  const toggleCategory = (category: string) => {
    setSelectedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(category)) {
        next.delete(category);
      } else {
        next.add(category);
      }
      return next;
    });
  };

  // Build query params
  const buildQueryParams = useCallback(() => {
    const params = new URLSearchParams();
    params.set('format', format);
    if (selectedSeverities.size < SEVERITY_ORDER.length) {
      params.set('severities', Array.from(selectedSeverities).join(','));
    }
    if (selectedCategories.size < categories.length) {
      params.set('categories', Array.from(selectedCategories).join(','));
    }
    if (!includeEvidence) params.set('include_evidence', 'false');
    if (!includeMetadata) params.set('include_metadata', 'false');
    return params.toString();
  }, [
    format,
    selectedSeverities,
    selectedCategories,
    categories.length,
    includeEvidence,
    includeMetadata,
  ]);

  // Download report
  const handleDownload = async () => {
    setExporting(true);
    setError(null);
    try {
      const queryParams = buildQueryParams();
      const response = await fetch(
        `${backendConfig.api}/api/audit/sessions/${sessionId}/report?${queryParams}`,
        { headers: { Authorization: `Bearer ${tokens?.access_token || ''}` } },
      );

      if (!response.ok) {
        throw new Error('Failed to generate report');
      }

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `audit-report-${sessionId.slice(0, 8)}.${FORMAT_INFO[format].extension}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Export failed');
    } finally {
      setExporting(false);
    }
  };

  // Copy to clipboard
  const handleCopyToClipboard = async () => {
    setExporting(true);
    setError(null);
    try {
      const queryParams = buildQueryParams();
      const response = await fetch(
        `${backendConfig.api}/api/audit/sessions/${sessionId}/report?${queryParams}`,
        { headers: { Authorization: `Bearer ${tokens?.access_token || ''}` } },
      );

      if (!response.ok) {
        throw new Error('Failed to generate report');
      }

      const text = await response.text();
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Copy failed');
    } finally {
      setExporting(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="export-modal-title"
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70"
        onClick={onClose}
        onKeyDown={(e) => e.key === 'Escape' && onClose()}
        role="button"
        tabIndex={-1}
        aria-label="Close modal"
      />

      {/* Modal */}
      <div className="relative bg-background border border-border rounded-lg shadow-xl w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="p-4 border-b border-border flex items-center justify-between">
          <h2 id="export-modal-title" className="font-theme-data text-lg">
            Export Audit Report
          </h2>
          <button
            onClick={onClose}
            className="text-muted hover:text-foreground"
            aria-label="Close export dialog"
          >
            [X]
          </button>
        </div>

        {/* Content */}
        <div className="p-4 space-y-6">
          {/* Format Selection */}
          <div>
            <label className="block text-xs font-theme-data text-muted mb-2">FORMAT</label>
            <div className="grid grid-cols-2 gap-2">
              {(Object.keys(FORMAT_INFO) as ExportFormat[]).map((f) => (
                <button
                  key={f}
                  onClick={() => setFormat(f)}
                  aria-pressed={format === f}
                  className={`p-3 rounded border text-left transition-colors ${
                    format === f
                      ? 'border-accent bg-accent/10'
                      : 'border-border hover:border-accent/50'
                  }`}
                >
                  <div className="font-theme-data text-sm mb-0.5">{FORMAT_INFO[f].label}</div>
                  <div className="text-xs text-muted">{FORMAT_INFO[f].description}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Severity Filter */}
          <div>
            <label className="block text-xs font-theme-data text-muted mb-2">
              INCLUDE SEVERITIES
            </label>
            <div className="flex flex-wrap gap-2">
              {SEVERITY_ORDER.map((sev) => {
                const count = severityCounts[sev] || 0;
                const isSelected = selectedSeverities.has(sev);
                return (
                  <button
                    key={sev}
                    onClick={() => toggleSeverity(sev)}
                    disabled={count === 0}
                    aria-pressed={isSelected}
                    aria-label={`${sev} severity: ${count} findings`}
                    className={`px-3 py-1.5 rounded border text-xs font-theme-data transition-colors ${
                      isSelected
                        ? 'border-accent bg-accent/10 text-accent'
                        : 'border-border text-muted'
                    } ${count === 0 ? 'opacity-30 cursor-not-allowed' : ''}`}
                  >
                    {sev.toUpperCase()} ({count})
                  </button>
                );
              })}
            </div>
          </div>

          {/* Category Filter */}
          {categories.length > 0 && (
            <div>
              <label className="block text-xs font-theme-data text-muted mb-2">
                INCLUDE CATEGORIES
              </label>
              <div className="flex flex-wrap gap-2">
                {categories.map((cat) => {
                  const isSelected = selectedCategories.has(cat);
                  return (
                    <button
                      key={cat}
                      onClick={() => toggleCategory(cat)}
                      aria-pressed={isSelected}
                      aria-label={`Category: ${cat}`}
                      className={`px-3 py-1.5 rounded border text-xs font-theme-data transition-colors ${
                        isSelected
                          ? 'border-accent bg-accent/10 text-accent'
                          : 'border-border text-muted'
                      }`}
                    >
                      {cat.toUpperCase()}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Options */}
          <div className="space-y-3">
            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={includeEvidence}
                onChange={(e) => setIncludeEvidence(e.target.checked)}
                className="rounded"
              />
              <div>
                <div className="text-sm font-theme-data">Include evidence text</div>
                <div className="text-xs text-muted">Quoted sections from documents</div>
              </div>
            </label>
            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={includeMetadata}
                onChange={(e) => setIncludeMetadata(e.target.checked)}
                className="rounded"
              />
              <div>
                <div className="text-sm font-theme-data">Include metadata</div>
                <div className="text-xs text-muted">Session config, timestamps, agent info</div>
              </div>
            </label>
          </div>

          {/* Summary */}
          <div className="p-3 bg-surface rounded">
            <div className="flex items-center justify-between text-sm font-theme-data">
              <span>Findings to export:</span>
              <span className="text-accent">
                {filteredCount} / {findingsCount}
              </span>
            </div>
          </div>

          {/* Error */}
          {error && (
            <div className="p-3 bg-acid-red/10 border border-acid-red/30 rounded text-acid-red text-sm font-theme-data">
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-border flex items-center gap-3">
          <button onClick={onClose} className="btn btn-ghost flex-1">
            CANCEL
          </button>
          <button
            onClick={handleCopyToClipboard}
            disabled={exporting || filteredCount === 0}
            className="btn btn-ghost flex-1"
          >
            {copied ? 'COPIED!' : 'COPY'}
          </button>
          <button
            onClick={handleDownload}
            disabled={exporting || filteredCount === 0}
            className="btn btn-primary flex-1"
          >
            {exporting ? 'EXPORTING...' : 'DOWNLOAD'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default ReportExportModal;
