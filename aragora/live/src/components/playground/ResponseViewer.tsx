'use client';

import React, { useState } from 'react';

interface ResponseViewerProps {
  status: number | null;
  data: unknown;
  error: string | null;
  duration: number;
  headers: Record<string, string>;
}

function statusColor(status: number | null): string {
  if (!status) return 'text-[var(--text-muted)]';
  if (status < 300) return 'text-emerald-400';
  if (status < 400) return 'text-amber-400';
  return 'text-red-400';
}

export function ResponseViewer({ status, data, error, duration, headers }: ResponseViewerProps) {
  const [showHeaders, setShowHeaders] = useState(false);

  if (!status && !error) {
    return (
      <div className="h-full flex items-center justify-center bg-[var(--bg)]">
        <p className="font-theme-data text-xs text-[var(--text-muted)]">
          Send a request to see the response here.
        </p>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-[var(--bg)] overflow-hidden">
      {/* Status bar */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-[var(--border)] shrink-0">
        {status && (
          <span className={`text-sm font-theme-data font-bold ${statusColor(status)}`}>
            {status}
          </span>
        )}
        {error && <span className="text-sm font-theme-data font-bold text-red-400">ERROR</span>}
        <span className="text-xs font-theme-data text-[var(--text-muted)]">{duration}ms</span>
        <button
          onClick={() => setShowHeaders(!showHeaders)}
          className="ml-auto text-[10px] font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
        >
          {showHeaders ? 'HIDE HEADERS' : 'SHOW HEADERS'}
        </button>
      </div>

      {/* Headers */}
      {showHeaders && Object.keys(headers).length > 0 && (
        <div className="px-4 py-2 border-b border-[var(--border)] bg-[var(--surface)]/30 shrink-0 max-h-32 overflow-y-auto">
          {Object.entries(headers).map(([k, v]) => (
            <div key={k} className="flex gap-2 text-[10px] font-theme-data">
              <span className="text-[var(--acid-green)]">{k}:</span>
              <span className="text-[var(--text-muted)] break-all">{v}</span>
            </div>
          ))}
        </div>
      )}

      {/* Body */}
      <div className="flex-1 overflow-auto p-4">
        {error ? (
          <pre className="text-xs font-theme-data text-red-400 whitespace-pre-wrap">{error}</pre>
        ) : (
          <pre className="text-xs font-theme-data text-[var(--text)] whitespace-pre-wrap">
            {typeof data === 'string' ? data : JSON.stringify(data, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}
