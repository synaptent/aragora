'use client';

import { useMemo } from 'react';
import { useConfidenceHistory } from '@/hooks/useKnowledgeFlow';

function truncate(s: string, n: number) {
  return s.length > n ? `${s.slice(0, n)}...` : s;
}

export function KnowledgeConfidenceHistory() {
  const { entries, loading, error } = useConfidenceHistory();

  const summarized = useMemo(() => {
    return entries
      .map((entry) => {
        const history = [...entry.confidence_history].sort(
          (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
        );
        const latest = history[history.length - 1];
        const previous = history[history.length - 2];
        const delta = latest && previous ? latest.value - previous.value : 0;
        return {
          nodeId: entry.node_id,
          preview: entry.content_preview,
          points: history.length,
          latestValue: latest?.value ?? 0,
          latestReason: latest?.reason ?? 'no reason',
          latestTimestamp: latest?.timestamp ?? '',
          delta,
        };
      })
      .sort(
        (a, b) =>
          new Date(b.latestTimestamp || 0).getTime() - new Date(a.latestTimestamp || 0).getTime(),
      );
  }, [entries]);

  if (loading) {
    return (
      <div className="animate-pulse p-4 text-[var(--text-muted)] font-theme-data">
        Loading confidence trends...
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 text-red-400 font-theme-data">Failed to load confidence history</div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-[10px] font-theme-data uppercase tracking-wider text-[var(--text-muted)]">
          Confidence History
        </h3>
        <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
          Nodes with history: <span className="text-[var(--acid-green)]">{summarized.length}</span>
        </span>
      </div>

      {summarized.length === 0 ? (
        <div className="card p-3 text-[10px] font-theme-data text-[var(--text-muted)]">
          No confidence history yet.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {summarized.slice(0, 12).map((entry) => (
            <div
              key={entry.nodeId}
              className={`card p-3 border-l-2 ${entry.delta >= 0 ? 'border-emerald-400' : 'border-red-400'}`}
            >
              <div className="flex items-center justify-between gap-3 mb-1">
                <span className="font-theme-data text-[11px] text-[var(--text)] truncate">
                  {truncate(entry.preview || entry.nodeId, 46)}
                </span>
                <span
                  className={`font-theme-data text-[10px] ${entry.delta >= 0 ? 'text-emerald-400' : 'text-red-400'}`}
                >
                  {entry.delta >= 0 ? '+' : ''}
                  {entry.delta.toFixed(3)}
                </span>
              </div>
              <div className="text-[10px] font-theme-data text-[var(--text-muted)]">
                Latest: {(entry.latestValue * 100).toFixed(1)}% • {entry.points} points
              </div>
              <div className="text-[9px] font-theme-data text-[var(--text-muted)] mt-1">
                Reason: {truncate(entry.latestReason, 68)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
