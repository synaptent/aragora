'use client';

import { useState, useMemo } from 'react';

export type AuditEventType =
  | 'gauntlet_start'
  | 'gauntlet_end'
  | 'redteam_start'
  | 'redteam_attack'
  | 'redteam_end'
  | 'probe_start'
  | 'probe_result'
  | 'probe_end'
  | 'audit_start'
  | 'audit_finding'
  | 'audit_end'
  | 'verification_start'
  | 'verification_result'
  | 'verification_end'
  | 'risk_assessment'
  | 'finding_added'
  | 'verdict_determined'
  | 'receipt_generated';

export interface AuditEvent {
  event_id: string;
  event_type: AuditEventType;
  timestamp: string;
  source: string;
  description: string;
  details: Record<string, unknown>;
  severity?: 'info' | 'warning' | 'error';
  agent?: string;
  parent_event_id?: string;
}

export interface AuditTrail {
  trail_id: string;
  gauntlet_id: string;
  created_at: string;
  input_summary: string;
  input_type: string;
  verdict: string;
  confidence: number;
  total_findings: number;
  agents_involved: string[];
  duration_seconds: number;
  redteam_attacks: number;
  probes_run: number;
  audit_findings: number;
  verifications_attempted: number;
  verifications_successful: number;
  events: AuditEvent[];
  checksum: string;
}

export interface AuditTrailViewerProps {
  trail: AuditTrail;
  onExport?: (format: 'json' | 'csv' | 'md') => void;
  onVerify?: () => void;
  className?: string;
}

type EventFilter = 'all' | 'redteam' | 'probe' | 'audit' | 'verification' | 'findings';

const EVENT_ICONS: Record<string, string> = {
  gauntlet_start: '>>',
  gauntlet_end: '<<',
  redteam_start: '[!]',
  redteam_attack: '<!>',
  redteam_end: '[!]',
  probe_start: '[?]',
  probe_result: '[=]',
  probe_end: '[?]',
  audit_start: '[#]',
  audit_finding: '[*]',
  audit_end: '[#]',
  verification_start: '[v]',
  verification_result: '[+]',
  verification_end: '[v]',
  risk_assessment: '[~]',
  finding_added: '[.]',
  verdict_determined: '[!]',
  receipt_generated: '[@]',
};

const SEVERITY_COLORS = {
  info: {
    bg: 'bg-[var(--acid-cyan)]/20',
    text: 'text-[var(--acid-cyan)]',
    border: 'border-[var(--acid-cyan)]/30',
  },
  warning: { bg: 'bg-yellow-900/30', text: 'text-yellow-400', border: 'border-yellow-800/30' },
  error: { bg: 'bg-red-900/30', text: 'text-red-400', border: 'border-red-800/30' },
};

const VERDICT_COLORS: Record<string, { bg: string; text: string }> = {
  approved: { bg: 'bg-green-900/30', text: 'text-green-400' },
  rejected: { bg: 'bg-red-900/30', text: 'text-red-400' },
  conditional: { bg: 'bg-yellow-900/30', text: 'text-yellow-400' },
  needs_review: { bg: 'bg-orange-900/30', text: 'text-orange-400' },
};

/**
 * AuditTrailViewer - Visualizes the complete audit trail from a debate session.
 *
 * Shows timeline of events, agent activity, evidence chains, and supports
 * export to multiple formats for compliance documentation.
 */
export function AuditTrailViewer({
  trail,
  onExport,
  onVerify,
  className = '',
}: AuditTrailViewerProps) {
  const [filter, setFilter] = useState<EventFilter>('all');
  const [expandedEventId, setExpandedEventId] = useState<string | null>(null);
  const [showAgentFilter, setShowAgentFilter] = useState<string | null>(null);

  const filteredEvents = useMemo(() => {
    let events = trail.events;

    // Filter by event type category
    if (filter !== 'all') {
      const typeMap: Record<EventFilter, AuditEventType[]> = {
        all: [],
        redteam: ['redteam_start', 'redteam_attack', 'redteam_end'],
        probe: ['probe_start', 'probe_result', 'probe_end'],
        audit: ['audit_start', 'audit_finding', 'audit_end'],
        verification: ['verification_start', 'verification_result', 'verification_end'],
        findings: ['finding_added', 'risk_assessment'],
      };
      events = events.filter((e) => typeMap[filter].includes(e.event_type));
    }

    // Filter by agent
    if (showAgentFilter) {
      events = events.filter((e) => e.agent === showAgentFilter);
    }

    return events;
  }, [trail.events, filter, showAgentFilter]);

  const formatTime = (timestamp: string) => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };

  const formatDuration = (seconds: number) => {
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}m ${secs.toFixed(0)}s`;
  };

  const verdictColor = VERDICT_COLORS[trail.verdict.toLowerCase()] || VERDICT_COLORS.needs_review;

  return (
    <div className={`bg-bg border border-border rounded-lg ${className}`}>
      {/* Header */}
      <div className="p-4 border-b border-border">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className="text-[var(--accent)] font-theme-data text-lg">[AUDIT]</span>
            <h2 className="font-theme-data text-text font-bold">Decision Audit Trail</h2>
          </div>
          <div className="flex items-center gap-2">
            {onVerify && (
              <button
                onClick={onVerify}
                className="px-3 py-1.5 text-xs font-theme-data bg-surface border border-border rounded hover:border-[var(--accent)] transition-colors"
              >
                Verify Integrity
              </button>
            )}
            {onExport && (
              <div className="flex border border-border rounded overflow-hidden">
                <button
                  onClick={() => onExport('json')}
                  className="px-2 py-1.5 text-xs font-theme-data bg-surface hover:bg-[var(--accent)]/20 transition-colors"
                >
                  JSON
                </button>
                <button
                  onClick={() => onExport('csv')}
                  className="px-2 py-1.5 text-xs font-theme-data bg-surface border-l border-border hover:bg-[var(--accent)]/20 transition-colors"
                >
                  CSV
                </button>
                <button
                  onClick={() => onExport('md')}
                  className="px-2 py-1.5 text-xs font-theme-data bg-surface border-l border-border hover:bg-[var(--accent)]/20 transition-colors"
                >
                  MD
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Summary Stats */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
          <div className="bg-surface p-3 rounded">
            <div className="text-xs text-text-muted font-theme-data mb-1">VERDICT</div>
            <div className={`text-lg font-theme-data font-bold ${verdictColor.text}`}>
              {trail.verdict.toUpperCase()}
            </div>
          </div>
          <div className="bg-surface p-3 rounded">
            <div className="text-xs text-text-muted font-theme-data mb-1">CONFIDENCE</div>
            <div className="text-lg font-theme-data font-bold text-[var(--acid-cyan)]">
              {(trail.confidence * 100).toFixed(0)}%
            </div>
          </div>
          <div className="bg-surface p-3 rounded">
            <div className="text-xs text-text-muted font-theme-data mb-1">FINDINGS</div>
            <div className="text-lg font-theme-data font-bold text-[var(--acid-yellow)]">
              {trail.total_findings}
            </div>
          </div>
          <div className="bg-surface p-3 rounded">
            <div className="text-xs text-text-muted font-theme-data mb-1">DURATION</div>
            <div className="text-lg font-theme-data font-bold text-text">
              {formatDuration(trail.duration_seconds)}
            </div>
          </div>
        </div>

        {/* Trail Info */}
        <div className="flex flex-wrap gap-4 text-xs font-theme-data text-text-muted">
          <span>
            Trail: <code className="text-[var(--accent)]">{trail.trail_id}</code>
          </span>
          <span>
            Checksum: <code className="text-[var(--acid-cyan)]">{trail.checksum}</code>
          </span>
          <span>Created: {new Date(trail.created_at).toLocaleString()}</span>
        </div>
      </div>

      {/* Activity Summary */}
      <div className="p-4 border-b border-border bg-surface/30">
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 text-center">
          <div>
            <div className="text-xl font-theme-data font-bold text-red-400">
              {trail.redteam_attacks}
            </div>
            <div className="text-xs text-text-muted font-theme-data">Red-Team Attacks</div>
          </div>
          <div>
            <div className="text-xl font-theme-data font-bold text-[var(--acid-cyan)]">
              {trail.probes_run}
            </div>
            <div className="text-xs text-text-muted font-theme-data">Probes Run</div>
          </div>
          <div>
            <div className="text-xl font-theme-data font-bold text-yellow-400">
              {trail.audit_findings}
            </div>
            <div className="text-xs text-text-muted font-theme-data">Audit Findings</div>
          </div>
          <div>
            <div className="text-xl font-theme-data font-bold text-green-400">
              {trail.verifications_successful}/{trail.verifications_attempted}
            </div>
            <div className="text-xs text-text-muted font-theme-data">Verifications</div>
          </div>
          <div>
            <div className="text-xl font-theme-data font-bold text-[var(--accent)]">
              {trail.agents_involved.length}
            </div>
            <div className="text-xs text-text-muted font-theme-data">Agents</div>
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="p-4 border-b border-border">
        <div className="flex flex-wrap gap-2 mb-3">
          {(['all', 'redteam', 'probe', 'audit', 'verification', 'findings'] as EventFilter[]).map(
            (f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-3 py-1 text-xs font-theme-data rounded transition-colors ${
                  filter === f
                    ? 'bg-[var(--accent)] text-bg'
                    : 'bg-surface text-text-muted hover:text-text'
                }`}
              >
                {f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            ),
          )}
        </div>

        {/* Agent Filter */}
        {trail.agents_involved.length > 0 && (
          <div className="flex flex-wrap gap-1">
            <span className="text-xs text-text-muted font-theme-data mr-2">Agents:</span>
            <button
              onClick={() => setShowAgentFilter(null)}
              className={`px-2 py-0.5 text-xs font-theme-data rounded ${
                showAgentFilter === null
                  ? 'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)]'
                  : 'bg-surface text-text-muted'
              }`}
            >
              All
            </button>
            {trail.agents_involved.map((agent) => (
              <button
                key={agent}
                onClick={() => setShowAgentFilter(agent)}
                className={`px-2 py-0.5 text-xs font-theme-data rounded ${
                  showAgentFilter === agent
                    ? 'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)]'
                    : 'bg-surface text-text-muted'
                }`}
              >
                {agent}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Event Timeline */}
      <div className="p-4 max-h-96 overflow-y-auto">
        {filteredEvents.length === 0 ? (
          <div className="text-center py-8 text-text-muted font-theme-data">
            No events match the current filter
          </div>
        ) : (
          <div className="space-y-2">
            {filteredEvents.map((event, idx) => {
              const severity = event.severity || 'info';
              const colors = SEVERITY_COLORS[severity];
              const isExpanded = expandedEventId === event.event_id;

              return (
                <div
                  key={event.event_id}
                  onClick={() => setExpandedEventId(isExpanded ? null : event.event_id)}
                  className={`p-3 rounded border cursor-pointer transition-all ${colors.bg} ${colors.border} ${
                    isExpanded ? 'ring-1 ring-acid-green' : ''
                  }`}
                >
                  <div className="flex items-start gap-3">
                    {/* Timeline connector */}
                    <div className="flex flex-col items-center">
                      <span className={`font-theme-data text-xs ${colors.text}`}>
                        {EVENT_ICONS[event.event_type] || '[?]'}
                      </span>
                      {idx < filteredEvents.length - 1 && (
                        <div className="w-px h-full bg-border mt-1" />
                      )}
                    </div>

                    {/* Event content */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2">
                        <span className={`font-theme-data text-xs font-bold ${colors.text}`}>
                          {event.event_type.toUpperCase().replace(/_/g, ' ')}
                        </span>
                        <span className="text-xs text-text-muted font-theme-data">
                          {formatTime(event.timestamp)}
                        </span>
                      </div>
                      <p className="text-sm text-text mt-1">{event.description}</p>

                      <div className="flex items-center gap-3 mt-2 text-xs text-text-muted">
                        <span className="font-theme-data">Source: {event.source}</span>
                        {event.agent && (
                          <span className="font-theme-data text-[var(--acid-cyan)]">
                            Agent: {event.agent}
                          </span>
                        )}
                      </div>

                      {/* Expanded details */}
                      {isExpanded && Object.keys(event.details).length > 0 && (
                        <div className="mt-3 pt-3 border-t border-border/50">
                          <div className="text-xs text-text-muted font-theme-data mb-2">
                            DETAILS
                          </div>
                          <pre className="text-xs font-theme-data bg-bg/50 p-2 rounded overflow-x-auto">
                            {JSON.stringify(event.details, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="p-4 border-t border-border bg-surface/30 text-xs text-text-muted font-theme-data text-center">
        {filteredEvents.length} events shown | Input: {trail.input_type} | &quot;
        {trail.input_summary.slice(0, 50)}...&quot;
      </div>
    </div>
  );
}

export default AuditTrailViewer;
