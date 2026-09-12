'use client';

import { useDedupClusters } from '@/hooks/useUnifiedMemory';
import { useState } from 'react';

export function DedupClusters() {
  const { clusters, totalDuplicates, loading } = useDedupClusters();
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  if (loading)
    return (
      <div className="animate-pulse p-4 text-[var(--text-muted)] font-theme-data">
        Loading dedup clusters...
      </div>
    );

  return (
    <div className="space-y-4">
      <div className="font-theme-data text-xs text-[var(--text-muted)]">
        {clusters.length} clusters, {totalDuplicates} total near-duplicates
      </div>

      {clusters.length === 0 ? (
        <p className="text-[var(--text-muted)] font-theme-data text-sm p-4">
          No duplicate clusters found. Enable CrossSystemDedupEngine for near-duplicate detection.
        </p>
      ) : (
        <div className="space-y-2">
          {clusters.map((c) => (
            <div key={c.cluster_id} className="card p-3">
              <button
                onClick={() => toggle(c.cluster_id)}
                className="w-full flex items-center justify-between"
              >
                <span className="font-theme-data text-xs text-[var(--text)]">
                  Cluster {c.cluster_id}
                </span>
                <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                  {c.entries.length} entries
                </span>
              </button>
              {expanded.has(c.cluster_id) && (
                <div className="mt-2 space-y-1 pl-2 border-l border-[var(--acid-green)]/20">
                  {c.entries.map((e, i) => (
                    <div
                      key={i}
                      className={`p-2 rounded text-xs font-theme-data ${e.source === c.canonical ? 'bg-[var(--acid-green)]/10 text-[var(--acid-green)]' : 'text-[var(--text-muted)]'}`}
                    >
                      <div className="flex justify-between mb-0.5">
                        <span className="text-[9px]">
                          {e.source} {e.source === c.canonical ? '(canonical)' : ''}
                        </span>
                        <span className="text-[9px]">
                          {(e.similarity * 100).toFixed(0)}% similar
                        </span>
                      </div>
                      <p>{e.content}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
