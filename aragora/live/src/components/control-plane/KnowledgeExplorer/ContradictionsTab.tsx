'use client';

import { useState, useCallback } from 'react';
import useSWR from 'swr';
import { API_BASE_URL } from '@/config';

interface Contradiction {
  id: string;
  node_a_id: string;
  node_a_content: string;
  node_b_id: string;
  node_b_content: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  detected_at: string;
  status: 'unresolved' | 'resolved' | 'dismissed';
}

interface ContradictionsResponse {
  contradictions: Contradiction[];
  total: number;
}

interface ContradictionStats {
  total: number;
  unresolved: number;
  resolved: number;
  dismissed: number;
  by_severity: Record<string, number>;
}

const fetcher = (url: string) => fetch(url).then((r) => r.json());

const severityColors: Record<string, string> = {
  critical: 'text-red-400 bg-red-900/20 border-red-800/30',
  high: 'text-orange-400 bg-orange-900/20 border-orange-800/30',
  medium: 'text-yellow-400 bg-yellow-900/20 border-yellow-800/30',
  low: 'text-blue-400 bg-blue-900/20 border-blue-800/30',
};

export function ContradictionsTab() {
  const [resolving, setResolving] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);

  const { data, mutate, isLoading } = useSWR<ContradictionsResponse>(
    `${API_BASE_URL}/api/v1/knowledge/mound/contradictions`,
    fetcher,
    { refreshInterval: 60000 },
  );

  const { data: statsData } = useSWR<ContradictionStats>(
    `${API_BASE_URL}/api/v1/knowledge/mound/contradictions/stats`,
    fetcher,
    { refreshInterval: 60000 },
  );

  const contradictions = data?.contradictions ?? [];
  const stats = statsData;

  const handleScan = useCallback(async () => {
    setScanning(true);
    try {
      await fetch(`${API_BASE_URL}/api/v1/knowledge/mound/contradictions/detect`, {
        method: 'POST',
      });
      await mutate();
    } finally {
      setScanning(false);
    }
  }, [mutate]);

  const handleResolve = useCallback(
    async (id: string, resolution: 'keep_a' | 'keep_b' | 'dismiss') => {
      setResolving(id);
      try {
        await fetch(`${API_BASE_URL}/api/v1/knowledge/mound/contradictions/${id}/resolve`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ resolution }),
        });
        await mutate();
      } finally {
        setResolving(null);
      }
    },
    [mutate],
  );

  if (isLoading && contradictions.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-text-muted text-sm">
        Loading contradictions...
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Stats bar */}
      {stats && (
        <div className="flex items-center justify-between">
          <div className="flex gap-6 text-sm">
            <span className="text-red-400">
              Unresolved: <span className="font-theme-data">{stats.unresolved}</span>
            </span>
            <span className="text-green-400">
              Resolved: <span className="font-theme-data">{stats.resolved}</span>
            </span>
            <span className="text-text-muted">
              Dismissed: <span className="font-theme-data">{stats.dismissed}</span>
            </span>
          </div>
          <button
            onClick={handleScan}
            disabled={scanning}
            className="px-3 py-1 text-xs bg-[var(--accent)]/10 text-[var(--accent)] border border-[var(--accent)]/30 rounded hover:bg-[var(--accent)]/20 disabled:opacity-50 transition-colors"
          >
            {scanning ? 'Scanning...' : 'Run Detection Scan'}
          </button>
        </div>
      )}

      {/* Contradictions list */}
      <div className="space-y-3">
        {contradictions.map((c) => (
          <div
            key={c.id}
            className={`p-4 rounded-lg border ${severityColors[c.severity] || 'border-border'}`}
          >
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-theme-data uppercase tracking-wider">{c.severity}</span>
              <span className="text-xs text-text-muted">
                {new Date(c.detected_at).toLocaleDateString()}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-4 mb-3">
              <div className="p-2 bg-black/20 rounded text-xs">
                <div className="text-text-muted mb-1 font-theme-data">Node A</div>
                <div className="text-text line-clamp-3">{c.node_a_content}</div>
              </div>
              <div className="p-2 bg-black/20 rounded text-xs">
                <div className="text-text-muted mb-1 font-theme-data">Node B</div>
                <div className="text-text line-clamp-3">{c.node_b_content}</div>
              </div>
            </div>

            {c.status === 'unresolved' && (
              <div className="flex gap-2">
                <button
                  onClick={() => handleResolve(c.id, 'keep_a')}
                  disabled={resolving === c.id}
                  className="px-2 py-1 text-xs bg-green-900/20 text-green-400 border border-green-800/30 rounded hover:bg-green-900/40 disabled:opacity-50"
                >
                  Keep A
                </button>
                <button
                  onClick={() => handleResolve(c.id, 'keep_b')}
                  disabled={resolving === c.id}
                  className="px-2 py-1 text-xs bg-blue-900/20 text-blue-400 border border-blue-800/30 rounded hover:bg-blue-900/40 disabled:opacity-50"
                >
                  Keep B
                </button>
                <button
                  onClick={() => handleResolve(c.id, 'dismiss')}
                  disabled={resolving === c.id}
                  className="px-2 py-1 text-xs bg-surface text-text-muted border border-border rounded hover:bg-surface/80 disabled:opacity-50"
                >
                  Dismiss
                </button>
              </div>
            )}

            {c.status !== 'unresolved' && (
              <span className="text-xs text-text-muted italic">{c.status}</span>
            )}
          </div>
        ))}
      </div>

      {contradictions.length === 0 && !isLoading && (
        <div className="text-center py-8">
          <div className="text-text-muted text-sm mb-2">No contradictions detected</div>
          <button
            onClick={handleScan}
            disabled={scanning}
            className="text-xs text-[var(--accent)] hover:underline disabled:opacity-50"
          >
            {scanning ? 'Scanning...' : 'Run a detection scan'}
          </button>
        </div>
      )}
    </div>
  );
}
