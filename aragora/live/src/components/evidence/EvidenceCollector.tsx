'use client';

import React, { useState, useCallback } from 'react';
import { getClient, EvidenceSnippet } from '@/lib/aragora-client';

interface EvidenceCollectorProps {
  debateId?: string;
  round?: number;
  onEvidenceCollected?: (evidence: EvidenceSnippet[]) => void;
  onEvidenceSelected?: (evidenceIds: string[]) => void;
  className?: string;
}

export function EvidenceCollector({
  debateId,
  round,
  onEvidenceCollected,
  onEvidenceSelected,
  className = '',
}: EvidenceCollectorProps) {
  const [task, setTask] = useState('');
  const [collecting, setCollecting] = useState(false);
  const [results, setResults] = useState<EvidenceSnippet[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [keywords, setKeywords] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const handleCollect = useCallback(async () => {
    if (!task.trim()) {
      setError('Please enter a topic');
      return;
    }

    setCollecting(true);
    setError(null);

    try {
      const client = getClient();
      const response = await client.evidence.collect({ task, debate_id: debateId, round });

      setResults(response.snippets);
      setKeywords(response.keywords);

      if (onEvidenceCollected) {
        onEvidenceCollected(response.snippets);
      }

      // Auto-select all collected evidence
      const newIds = new Set(response.snippets.map((s) => s.id));
      setSelectedIds(newIds);
      if (onEvidenceSelected) {
        onEvidenceSelected(Array.from(newIds));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Evidence collection failed');
    } finally {
      setCollecting(false);
    }
  }, [task, debateId, round, onEvidenceCollected, onEvidenceSelected]);

  const toggleSelection = useCallback(
    (id: string) => {
      setSelectedIds((prev) => {
        const next = new Set(prev);
        if (next.has(id)) {
          next.delete(id);
        } else {
          next.add(id);
        }
        if (onEvidenceSelected) {
          onEvidenceSelected(Array.from(next));
        }
        return next;
      });
    },
    [onEvidenceSelected],
  );

  const selectAll = useCallback(() => {
    const all = new Set(results.map((r) => r.id));
    setSelectedIds(all);
    if (onEvidenceSelected) {
      onEvidenceSelected(Array.from(all));
    }
  }, [results, onEvidenceSelected]);

  const selectNone = useCallback(() => {
    setSelectedIds(new Set());
    if (onEvidenceSelected) {
      onEvidenceSelected([]);
    }
  }, [onEvidenceSelected]);

  return (
    <div className={`border border-gray-200 dark:border-gray-700 rounded-lg ${className}`}>
      {/* Header */}
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-800"
      >
        <div className="flex items-center gap-2">
          <svg
            className={`w-5 h-5 transition-transform ${expanded ? 'rotate-90' : ''}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
          <span className="font-medium text-gray-900 dark:text-gray-100">Evidence Collection</span>
          {results.length > 0 && (
            <span className="text-sm text-gray-500 dark:text-gray-400">
              ({selectedIds.size}/{results.length} selected)
            </span>
          )}
        </div>
        {results.length > 0 && (
          <span className="text-sm text-green-600 dark:text-green-400">{results.length} items</span>
        )}
      </button>

      {/* Expandable content */}
      {expanded && (
        <div className="px-4 pb-4 border-t border-gray-200 dark:border-gray-700">
          {/* Input section */}
          <div className="mt-4">
            <textarea
              value={task}
              onChange={(e) => setTask(e.target.value)}
              placeholder="Describe the topic to gather evidence for..."
              rows={2}
              className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 resize-none"
            />
            <button
              type="button"
              onClick={handleCollect}
              disabled={collecting || !task.trim()}
              className="mt-2 w-full px-4 py-2 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700 disabled:opacity-50"
            >
              {collecting ? (
                <span className="flex items-center justify-center gap-2">
                  <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
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
                  Collecting...
                </span>
              ) : (
                'Collect Evidence'
              )}
            </button>
          </div>

          {/* Error display */}
          {error && (
            <div className="mt-3 p-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded text-sm text-red-700 dark:text-red-300">
              {error}
            </div>
          )}

          {/* Keywords */}
          {keywords.length > 0 && (
            <div className="mt-3">
              <div className="text-xs text-gray-500 dark:text-gray-400 mb-1">Keywords:</div>
              <div className="flex flex-wrap gap-1">
                {keywords.map((kw, idx) => (
                  <span
                    key={idx}
                    className="px-2 py-0.5 bg-blue-100 dark:bg-blue-800 text-blue-700 dark:text-blue-200 rounded text-xs"
                  >
                    {kw}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Results list */}
          {results.length > 0 && (
            <div className="mt-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                  Evidence Items
                </span>
                <div className="flex gap-2 text-xs">
                  <button
                    type="button"
                    onClick={selectAll}
                    className="text-blue-600 dark:text-blue-400 hover:underline"
                  >
                    Select all
                  </button>
                  <span className="text-gray-400">|</span>
                  <button
                    type="button"
                    onClick={selectNone}
                    className="text-blue-600 dark:text-blue-400 hover:underline"
                  >
                    Select none
                  </button>
                </div>
              </div>

              <div className="space-y-2 max-h-64 overflow-y-auto">
                {results.map((evidence) => (
                  <label
                    key={evidence.id}
                    className={`flex items-start gap-2 p-2 rounded border cursor-pointer transition-colors ${
                      selectedIds.has(evidence.id)
                        ? 'bg-blue-50 dark:bg-blue-900/20 border-blue-300 dark:border-blue-700'
                        : 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-750'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={selectedIds.has(evidence.id)}
                      onChange={() => toggleSelection(evidence.id)}
                      className="mt-1"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
                        {evidence.title}
                      </div>
                      <div className="text-xs text-gray-500 dark:text-gray-400 line-clamp-2">
                        {evidence.snippet}
                      </div>
                      <div className="flex items-center gap-2 mt-1">
                        <span className="text-xs px-1.5 py-0.5 bg-gray-100 dark:bg-gray-700 rounded">
                          {evidence.source}
                        </span>
                        <span className="text-xs text-gray-500">
                          {(evidence.reliability_score * 100).toFixed(0)}% reliable
                        </span>
                      </div>
                    </div>
                  </label>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default EvidenceCollector;
