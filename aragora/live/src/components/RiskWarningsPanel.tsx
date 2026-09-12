'use client';

import { useState, useEffect, useMemo, useCallback } from 'react';
import type { StreamEvent } from '@/types/events';
import { useAuth } from '@/context/AuthContext';

interface RiskWarning {
  domain: string;
  risk_type: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  description: string;
  mitigation?: string;
  detected_at?: string;
}

interface RiskWarningsPanelProps {
  apiBase?: string;
  events?: StreamEvent[];
}

const severityColors: Record<string, string> = {
  low: 'text-green-400 border-green-400/30 bg-green-400/5',
  medium: 'text-yellow-400 border-yellow-400/30 bg-yellow-400/5',
  high: 'text-orange-400 border-orange-400/30 bg-orange-400/5',
  critical: 'text-red-400 border-red-400/30 bg-red-400/5',
};

export function RiskWarningsPanel({ apiBase = '', events = [] }: RiskWarningsPanelProps) {
  const { tokens } = useAuth();
  const [apiWarnings, setApiWarnings] = useState<RiskWarning[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isExpanded, setIsExpanded] = useState(false);

  // Extract risk_warning events from stream
  const eventWarnings = useMemo(
    () =>
      events
        .filter((e) => e.type === 'risk_warning')
        .map((e) => ({
          domain: (e.data as { domain?: string }).domain || 'unknown',
          risk_type: (e.data as { risk_type?: string }).risk_type || 'risk',
          severity: ((e.data as { level?: string }).level || 'medium') as RiskWarning['severity'],
          description: (e.data as { description?: string }).description || '',
          mitigation: (e.data as { mitigations?: string[] }).mitigations?.join('; '),
          detected_at: new Date(e.timestamp * 1000).toISOString(),
        })),
    [events],
  );

  // Merge API warnings with event warnings (event warnings take precedence for freshness)
  const warnings = useMemo(() => {
    const eventDomains = new Set(eventWarnings.map((w) => w.domain));
    // Keep API warnings not superseded by events, then add event warnings
    return [...apiWarnings.filter((w) => !eventDomains.has(w.domain)), ...eventWarnings];
  }, [apiWarnings, eventWarnings]);

  const fetchWarnings = useCallback(async () => {
    try {
      const headers: HeadersInit = { 'Content-Type': 'application/json' };
      if (tokens?.access_token) {
        headers['Authorization'] = `Bearer ${tokens.access_token}`;
      }
      const response = await fetch(`${apiBase}/api/consensus/risk-warnings`, { headers });
      if (response.ok) {
        const data = await response.json();
        setApiWarnings(data.warnings || data || []);
      } else {
        setError('Failed to fetch risk warnings');
      }
    } catch {
      setError('Network error');
    } finally {
      setLoading(false);
    }
  }, [apiBase, tokens?.access_token]);

  useEffect(() => {
    fetchWarnings();
    // Refresh every 60 seconds (reduced need with event subscription)
    const interval = setInterval(fetchWarnings, 60000);
    return () => clearInterval(interval);
  }, [fetchWarnings]);

  const criticalCount = warnings.filter((w) => w.severity === 'critical').length;
  const highCount = warnings.filter((w) => w.severity === 'high').length;

  if (!isExpanded) {
    return (
      <div
        className={`panel panel-compact cursor-pointer transition-colors ${
          criticalCount > 0 ? 'border-red-400/50' : highCount > 0 ? 'border-orange-400/50' : ''
        }`}
        onClick={() => setIsExpanded(true)}
      >
        <div className="flex items-center justify-between">
          <h3 className="panel-title-sm flex items-center gap-2">
            <span className="text-[var(--accent)]">{'>'}</span>
            RISK_WARNINGS
            {warnings.length > 0 && <span className="panel-badge">{warnings.length}</span>}
          </h3>
          <div className="flex items-center gap-2">
            {criticalCount > 0 && (
              <span className="text-xs font-theme-data text-red-400">{criticalCount} CRITICAL</span>
            )}
            {highCount > 0 && (
              <span className="text-xs font-theme-data text-orange-400">{highCount} HIGH</span>
            )}
            <span className="panel-toggle">[EXPAND]</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <h3 className="panel-title-sm flex items-center gap-2">
          <span className="text-[var(--accent)]">{'>'}</span>
          RISK_WARNINGS
        </h3>
        <button
          onClick={() => setIsExpanded(false)}
          className="panel-toggle hover:text-[var(--accent)] transition-colors"
        >
          [COLLAPSE]
        </button>
      </div>

      {loading && (
        <div className="text-xs text-text-muted font-theme-data animate-pulse">
          Scanning for domain-specific risks...
        </div>
      )}

      {error && <div className="text-xs text-warning font-theme-data">{error}</div>}

      {!loading && !error && warnings.length === 0 && (
        <div className="text-xs text-green-400 font-theme-data">No risk warnings detected.</div>
      )}

      <div className="space-y-3 max-h-64 overflow-y-auto">
        {warnings.map((warning, idx) => (
          <div
            key={idx}
            className={`border p-3 space-y-2 ${severityColors[warning.severity] || severityColors.medium}`}
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-theme-data uppercase">
                [{warning.severity}] {warning.risk_type}
              </span>
              <span className="text-xs font-theme-data text-text-muted">{warning.domain}</span>
            </div>
            <p className="text-xs text-text leading-relaxed">{warning.description}</p>
            {warning.mitigation && (
              <p className="text-xs text-text-muted">
                <span className="text-[var(--accent)]">Mitigation:</span> {warning.mitigation}
              </p>
            )}
          </div>
        ))}
      </div>

      <div className="mt-3 text-[10px] text-text-muted font-theme-data">
        Domain-specific risk assessment from debate analysis
      </div>
    </div>
  );
}
