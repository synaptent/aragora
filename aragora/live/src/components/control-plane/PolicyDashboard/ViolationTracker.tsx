'use client';

import { useState, useMemo } from 'react';

export interface ComplianceViolation {
  id: string;
  rule_id: string;
  rule_name: string;
  framework_id: string;
  vertical_id: string;
  severity: 'critical' | 'high' | 'medium' | 'low';
  status: 'open' | 'investigating' | 'resolved' | 'false_positive';
  description: string;
  source: string;
  detected_at: string;
  resolved_at?: string;
}

export interface ViolationTrackerProps {
  violations: ComplianceViolation[];
  onSelectViolation?: (violation: ComplianceViolation) => void;
  verticals: Array<{ id: string; name: string }>;
  selectedVertical: string | null;
  onVerticalChange: (vertical: string | null) => void;
  className?: string;
}

const SEVERITY_COLORS: Record<string, { bg: string; text: string }> = {
  critical: { bg: 'bg-red-900/30', text: 'text-red-400' },
  high: { bg: 'bg-orange-900/30', text: 'text-orange-400' },
  medium: { bg: 'bg-yellow-900/30', text: 'text-yellow-400' },
  low: { bg: 'bg-blue-900/30', text: 'text-blue-400' },
};

const STATUS_COLORS: Record<string, { bg: string; text: string }> = {
  open: { bg: 'bg-red-900/30', text: 'text-red-400' },
  investigating: { bg: 'bg-yellow-900/30', text: 'text-yellow-400' },
  resolved: { bg: 'bg-green-900/30', text: 'text-green-400' },
  false_positive: { bg: 'bg-gray-900/30', text: 'text-gray-400' },
};

type SeverityFilter = 'all' | 'critical' | 'high' | 'medium' | 'low';

export function ViolationTracker({
  violations,
  onSelectViolation,
  verticals,
  selectedVertical,
  onVerticalChange,
  className = '',
}: ViolationTrackerProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>('all');
  const [statusFilter, setStatusFilter] = useState<string>('all');

  const filteredViolations = useMemo(() => {
    let result = violations;
    if (selectedVertical) result = result.filter((v) => v.vertical_id === selectedVertical);
    if (severityFilter !== 'all') result = result.filter((v) => v.severity === severityFilter);
    if (statusFilter !== 'all') result = result.filter((v) => v.status === statusFilter);
    return result.sort((a, b) => {
      const order = { critical: 0, high: 1, medium: 2, low: 3 };
      return order[a.severity] - order[b.severity];
    });
  }, [violations, selectedVertical, severityFilter, statusFilter]);

  const severityCounts = useMemo(
    () => ({
      all: violations.filter((v) => v.status !== 'resolved').length,
      critical: violations.filter((v) => v.severity === 'critical' && v.status !== 'resolved')
        .length,
      high: violations.filter((v) => v.severity === 'high' && v.status !== 'resolved').length,
      medium: violations.filter((v) => v.severity === 'medium' && v.status !== 'resolved').length,
      low: violations.filter((v) => v.severity === 'low' && v.status !== 'resolved').length,
    }),
    [violations],
  );

  const handleClick = (v: ComplianceViolation) => {
    setExpandedId(expandedId === v.id ? null : v.id);
    onSelectViolation?.(v);
  };

  const formatDate = (dateStr: string) => {
    const diffHours = Math.floor((Date.now() - new Date(dateStr).getTime()) / 3600000);
    if (diffHours < 1) return 'Just now';
    if (diffHours < 24) return `${diffHours}h ago`;
    return `${Math.floor(diffHours / 24)}d ago`;
  };

  return (
    <div className={className}>
      <div className="flex flex-wrap gap-3 mb-4">
        <select
          value={selectedVertical || ''}
          onChange={(e) => onVerticalChange(e.target.value || null)}
          className="px-3 py-2 text-sm bg-bg border border-border rounded focus:border-[var(--accent)] focus:outline-none"
        >
          <option value="">All Verticals</option>
          {verticals.map((v) => (
            <option key={v.id} value={v.id}>
              {v.name}
            </option>
          ))}
        </select>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="px-3 py-2 text-sm bg-bg border border-border rounded focus:border-[var(--accent)] focus:outline-none"
        >
          <option value="all">All Status</option>
          <option value="open">Open</option>
          <option value="investigating">Investigating</option>
          <option value="resolved">Resolved</option>
        </select>
      </div>

      <div className="flex flex-wrap gap-1 mb-4">
        {(['all', 'critical', 'high', 'medium', 'low'] as SeverityFilter[]).map((sev) => (
          <button
            key={sev}
            onClick={() => setSeverityFilter(sev)}
            className={`px-3 py-1 text-xs font-theme-data rounded ${
              severityFilter === sev
                ? sev === 'all'
                  ? 'bg-[var(--accent)] text-bg'
                  : `${SEVERITY_COLORS[sev].bg} ${SEVERITY_COLORS[sev].text}`
                : 'bg-surface text-text-muted hover:text-text'
            }`}
          >
            {sev.charAt(0).toUpperCase() + sev.slice(1)} ({severityCounts[sev]})
          </button>
        ))}
      </div>

      {filteredViolations.length === 0 ? (
        <div className="text-center py-8 text-text-muted">No violations found</div>
      ) : (
        <div className="space-y-2">
          {filteredViolations.map((v) => (
            <div
              key={v.id}
              onClick={() => handleClick(v)}
              className={`p-4 bg-bg border rounded-lg cursor-pointer transition-all ${
                expandedId === v.id
                  ? 'border-[var(--accent)]'
                  : 'border-border hover:border-text-muted'
              }`}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-3">
                  <div className={`w-3 h-3 rounded-full mt-1 ${SEVERITY_COLORS[v.severity].bg}`} />
                  <div>
                    <h4 className="font-theme-data font-bold text-text">{v.rule_name}</h4>
                    <p className="text-sm text-text-muted mt-1 line-clamp-1">{v.description}</p>
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <span
                    className={`px-2 py-0.5 text-xs font-theme-data uppercase rounded ${SEVERITY_COLORS[v.severity].bg} ${SEVERITY_COLORS[v.severity].text}`}
                  >
                    {v.severity}
                  </span>
                  <span
                    className={`px-2 py-0.5 text-xs font-theme-data rounded ${STATUS_COLORS[v.status].bg} ${STATUS_COLORS[v.status].text}`}
                  >
                    {v.status}
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-4 mt-3 text-xs text-text-muted">
                <span>{v.framework_id.toUpperCase()}</span>
                <span className="font-theme-data">{v.source}</span>
                <span>{formatDate(v.detected_at)}</span>
              </div>
              {expandedId === v.id && (
                <div className="mt-4 pt-4 border-t border-border">
                  <code className="block px-3 py-2 bg-surface rounded text-sm font-theme-data text-[var(--acid-cyan)] mb-4">
                    {v.source}
                  </code>
                  <div className="flex gap-2">
                    {v.status === 'open' && (
                      <>
                        <button className="flex-1 px-3 py-1.5 text-xs font-theme-data bg-yellow-900/30 text-yellow-400 border border-yellow-800/30 rounded">
                          Investigate
                        </button>
                        <button className="flex-1 px-3 py-1.5 text-xs font-theme-data bg-green-900/30 text-green-400 border border-green-800/30 rounded">
                          Resolve
                        </button>
                      </>
                    )}
                    <button className="px-3 py-1.5 text-xs font-theme-data bg-surface border border-border rounded hover:border-[var(--accent)]">
                      View Details
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
