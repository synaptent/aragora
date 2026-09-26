'use client';

import { useState, useCallback } from 'react';
import { useFocusTrap } from '@/hooks/useFocusTrap';
import { API_BASE_URL } from '@/config';

interface DebateExportModalProps {
  debateId: string;
  isOpen: boolean;
  onClose: () => void;
  apiBase?: string;
}

type ExportFormat = 'json' | 'csv' | 'dot' | 'html' | 'txt' | 'md';
type ExportTable = 'summary' | 'messages' | 'critiques' | 'votes' | 'verifications';

const DEFAULT_API_BASE = API_BASE_URL;

const FORMAT_DESCRIPTIONS: Record<ExportFormat, string> = {
  json: 'Complete debate data in JSON format',
  csv: 'Tabular data for spreadsheet analysis',
  dot: 'GraphViz DOT format for visualization',
  html: 'Standalone HTML page for sharing',
  txt: 'Plain text transcript for easy reading',
  md: 'Markdown transcript for documentation',
};

const TABLE_OPTIONS: { value: ExportTable; label: string }[] = [
  { value: 'summary', label: 'Summary (overview + agents)' },
  { value: 'messages', label: 'Messages (all agent responses)' },
  { value: 'critiques', label: 'Critiques (all critique data)' },
  { value: 'votes', label: 'Votes (voting history)' },
  { value: 'verifications', label: 'Verifications (proof attempts)' },
];

export function DebateExportModal({
  debateId,
  isOpen,
  onClose,
  apiBase = DEFAULT_API_BASE,
}: DebateExportModalProps) {
  const [format, setFormat] = useState<ExportFormat>('json');
  const [selectedTable, setSelectedTable] = useState<ExportTable>('summary');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const focusTrapRef = useFocusTrap<HTMLDivElement>({ isActive: isOpen, onEscape: onClose });

  const handleExport = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      // Build export URL
      const params = new URLSearchParams();
      if (format === 'csv') {
        params.set('table', selectedTable);
      }

      const url = `${apiBase}/api/debates/${debateId}/export/${format}?${params}`;
      const response = await fetch(url);

      if (!response.ok) {
        throw new Error(`Export failed: ${response.statusText}`);
      }

      // Get the data
      const blob = await response.blob();

      // Determine filename
      const extension = format === 'dot' ? 'gv' : format;
      const filename = `debate-${debateId}-${format === 'csv' ? selectedTable : 'full'}.${extension}`;

      // Create download link
      const downloadUrl = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(downloadUrl);

      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Export failed');
    } finally {
      setLoading(false);
    }
  }, [debateId, format, selectedTable, apiBase, onClose]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="export-modal-title"
    >
      <div
        ref={focusTrapRef}
        className="bg-zinc-900 border border-zinc-700 rounded-lg p-6 max-w-md w-full mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="export-modal-title" className="text-lg font-semibold text-white mb-4">
          Export Debate
        </h2>

        {/* Format Selection */}
        <div className="mb-4">
          <label className="block text-sm text-zinc-400 mb-2">Format</label>
          <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="Export format">
            {(['txt', 'md', 'json', 'csv', 'html', 'dot'] as ExportFormat[]).map((f) => (
              <button
                key={f}
                onClick={() => setFormat(f)}
                role="radio"
                aria-checked={format === f}
                aria-label={`Export as ${f.toUpperCase()}: ${FORMAT_DESCRIPTIONS[f]}`}
                className={`p-3 rounded border text-left ${
                  format === f
                    ? 'border-blue-500 bg-blue-500/10 text-blue-400'
                    : 'border-zinc-700 hover:border-zinc-600 text-zinc-300'
                }`}
              >
                <div className="font-medium uppercase text-sm">{f}</div>
                <div className="text-xs text-zinc-500 mt-1">{FORMAT_DESCRIPTIONS[f]}</div>
              </button>
            ))}
          </div>
        </div>

        {/* CSV Table Selection */}
        {format === 'csv' && (
          <div className="mb-4">
            <label htmlFor="csv-table-select" className="block text-sm text-zinc-400 mb-2">
              Table
            </label>
            <select
              id="csv-table-select"
              value={selectedTable}
              onChange={(e) => setSelectedTable(e.target.value as ExportTable)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-zinc-300"
            >
              {TABLE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Error Display */}
        {error && (
          <div className="mb-4 p-3 bg-red-900/20 border border-red-800 rounded text-red-400 text-sm">
            {error}
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-3 justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 text-zinc-400 hover:text-zinc-300"
            disabled={loading}
            aria-label="Cancel export"
          >
            Cancel
          </button>
          <button
            onClick={handleExport}
            disabled={loading}
            aria-label={loading ? 'Exporting debate data' : 'Export debate data'}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded disabled:opacity-50"
          >
            {loading ? 'Exporting...' : 'Export'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default DebateExportModal;
