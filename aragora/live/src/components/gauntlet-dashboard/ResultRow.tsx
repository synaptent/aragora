'use client';

import React, { useState } from 'react';
import { VerdictBadge } from './VerdictBadge';
import type { GauntletResult } from './types';

interface ResultRowProps {
  result: GauntletResult;
  onClick: () => void;
  isSelected: boolean;
  onExport: (format: string) => void;
  onCompare: () => void;
}

export function ResultRow({ result, onClick, isSelected, onExport, onCompare }: ResultRowProps) {
  const [showActions, setShowActions] = useState(false);

  return (
    <div
      className={`
        p-4 border-l-4 transition-all cursor-pointer
        ${isSelected ? 'bg-surface border-[var(--accent)]' : 'bg-surface/30 border-transparent hover:border-[var(--accent)]/50'}
      `}
      onClick={onClick}
      onMouseEnter={() => setShowActions(true)}
      onMouseLeave={() => setShowActions(false)}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <VerdictBadge verdict={result.verdict} />
            <span className="text-xs font-theme-data text-text-muted">
              {result.gauntlet_id.slice(-12)}
            </span>
          </div>
          <p className="text-sm font-theme-data text-text truncate">{result.input_summary}</p>
          <div className="flex items-center gap-4 mt-2 text-xs font-theme-data text-text-muted">
            <span>{new Date(result.created_at).toLocaleString()}</span>
            {result.duration_seconds && <span>{result.duration_seconds}s</span>}
          </div>
        </div>

        <div className="flex flex-col items-end gap-2">
          <div className="flex items-center gap-2">
            {result.critical_count > 0 && (
              <span className="px-2 py-0.5 bg-acid-red/20 text-acid-red text-xs font-theme-data rounded">
                {result.critical_count} CRIT
              </span>
            )}
            {result.high_count > 0 && (
              <span className="px-2 py-0.5 bg-warning/20 text-warning text-xs font-theme-data rounded">
                {result.high_count} HIGH
              </span>
            )}
          </div>

          {showActions && (
            <div className="flex gap-1">
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onExport('html');
                }}
                className="px-2 py-1 text-xs font-theme-data bg-[var(--accent)]/10 text-[var(--accent)] hover:bg-[var(--accent)]/20 rounded transition-colors"
              >
                HTML
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onExport('md');
                }}
                className="px-2 py-1 text-xs font-theme-data bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/20 rounded transition-colors"
              >
                MD
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onCompare();
                }}
                className="px-2 py-1 text-xs font-theme-data bg-accent/10 text-accent hover:bg-accent/20 rounded transition-colors"
              >
                CMP
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
