'use client';

import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL } from '../config';
import { useAuth } from '@/context/AuthContext';

interface ContraryView {
  agent: string;
  position: string;
  confidence: number;
  reasoning: string;
  debate_id?: string;
}

interface ContraryViewsPanelProps {
  apiBase?: string;
}

export function ContraryViewsPanel({ apiBase }: ContraryViewsPanelProps) {
  const { tokens } = useAuth();
  const [views, setViews] = useState<ContraryView[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isExpanded, setIsExpanded] = useState(false);

  // Use centralized config if no apiBase provided
  const baseUrl = apiBase || API_BASE_URL;

  const fetchViews = useCallback(async () => {
    try {
      const headers: HeadersInit = { 'Content-Type': 'application/json' };
      if (tokens?.access_token) {
        headers['Authorization'] = `Bearer ${tokens.access_token}`;
      }
      const response = await fetch(`${baseUrl}/api/consensus/contrarian-views`, { headers });
      if (response.ok) {
        const data = await response.json();
        setViews(data.views || data || []);
      } else {
        setError('Failed to fetch contrary views');
      }
    } catch {
      setError('Network error');
    } finally {
      setLoading(false);
    }
  }, [baseUrl, tokens?.access_token]);

  useEffect(() => {
    fetchViews();
    // Refresh every 30 seconds
    const interval = setInterval(fetchViews, 30000);
    return () => clearInterval(interval);
  }, [fetchViews]);

  if (!isExpanded) {
    return (
      <div
        className="panel panel-compact cursor-pointer hover:border-[var(--accent)]/30 transition-colors"
        onClick={() => setIsExpanded(true)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setIsExpanded(true);
          }
        }}
        role="button"
        tabIndex={0}
        aria-expanded={false}
        aria-label="Expand contrary views panel"
      >
        <div className="flex items-center justify-between">
          <h3 className="panel-title-sm flex items-center gap-2">
            <span className="text-[var(--accent)]">{'>'}</span>
            CONTRARY_VIEWS
            {views.length > 0 && <span className="panel-badge">{views.length}</span>}
          </h3>
          <span className="panel-toggle" aria-hidden="true">
            [EXPAND]
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <h3 className="panel-title-sm flex items-center gap-2">
          <span className="text-[var(--accent)]">{'>'}</span>
          CONTRARY_VIEWS
        </h3>
        <button
          onClick={() => setIsExpanded(false)}
          aria-label="Collapse contrary views panel"
          className="panel-toggle hover:text-[var(--accent)] transition-colors"
        >
          [COLLAPSE]
        </button>
      </div>

      {loading && (
        <div className="text-xs text-text-muted font-theme-data animate-pulse">
          Loading dissenting opinions...
        </div>
      )}

      {error && <div className="text-xs text-warning font-theme-data">{error}</div>}

      {!loading && !error && views.length === 0 && (
        <div className="text-xs text-text-muted font-theme-data">
          No contrary views recorded yet.
        </div>
      )}

      <div className="space-y-3 max-h-64 overflow-y-auto">
        {views.map((view, idx) => (
          <div key={idx} className="border border-warning/30 bg-warning/5 p-3 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-theme-data text-warning">{view.agent}</span>
              <span className="text-xs font-theme-data text-text-muted">
                {Math.round(view.confidence * 100)}% confident
              </span>
            </div>
            <p className="text-xs text-text leading-relaxed">{view.position}</p>
            {view.reasoning && (
              <p className="text-xs text-text-muted italic">&quot;{view.reasoning}&quot;</p>
            )}
          </div>
        ))}
      </div>

      <div className="mt-3 text-[10px] text-text-muted font-theme-data">
        Dissenting opinions that didn&apos;t achieve consensus
      </div>
    </div>
  );
}
