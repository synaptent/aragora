'use client';

import { useState, useEffect, useRef, useMemo } from 'react';
import { useGauntletWebSocket, GauntletEvent, GauntletFinding } from '@/hooks/useGauntletWebSocket';

interface AttackFeedProps {
  gauntletId: string;
  wsUrl?: string;
  maxEvents?: number;
  autoScroll?: boolean;
  showAgentStats?: boolean;
  compact?: boolean;
  onFindingClick?: (finding: GauntletFinding) => void;
}

const EVENT_CONFIG: Record<string, { icon: string; color: string; label: string }> = {
  gauntlet_start: { icon: '\u{1F3C1}', color: 'text-[var(--accent)]', label: 'START' },
  gauntlet_phase: { icon: '\u{1F504}', color: 'text-[var(--acid-cyan)]', label: 'PHASE' },
  gauntlet_agent_active: { icon: '\u{1F916}', color: 'text-[var(--accent)]', label: 'AGENT' },
  gauntlet_attack: { icon: '\u{26A1}', color: 'text-acid-red', label: 'ATTACK' },
  gauntlet_probe: { icon: '\u{1F50D}', color: 'text-[var(--acid-yellow)]', label: 'PROBE' },
  gauntlet_finding: { icon: '\u{1F6A8}', color: 'text-warning', label: 'FINDING' },
  gauntlet_verification: { icon: '\u{2705}', color: 'text-[var(--acid-cyan)]', label: 'VERIFY' },
  gauntlet_risk: { icon: '\u{26A0}', color: 'text-warning', label: 'RISK' },
  gauntlet_progress: { icon: '\u{1F4CA}', color: 'text-text-muted', label: 'PROGRESS' },
  gauntlet_verdict: { icon: '\u{2696}', color: 'text-accent', label: 'VERDICT' },
  gauntlet_complete: { icon: '\u{1F3C6}', color: 'text-[var(--accent)]', label: 'COMPLETE' },
};

const SEVERITY_CONFIG: Record<string, { bg: string; text: string }> = {
  CRITICAL: { bg: 'bg-acid-red/20', text: 'text-acid-red' },
  HIGH: { bg: 'bg-warning/20', text: 'text-warning' },
  MEDIUM: { bg: 'bg-acid-yellow/20', text: 'text-[var(--acid-yellow)]' },
  LOW: { bg: 'bg-[var(--acid-cyan)]/20', text: 'text-[var(--acid-cyan)]' },
};

function formatTime(timestamp: number): string {
  const date = new Date(timestamp);
  return date.toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function EventRow({
  event,
  compact = false,
  onFindingClick,
}: {
  event: GauntletEvent;
  compact?: boolean;
  onFindingClick?: (finding: GauntletFinding) => void;
}) {
  const config = EVENT_CONFIG[event.type] || {
    icon: '\u2022',
    color: 'text-text-muted',
    label: 'EVENT',
  };
  const data = event.data as Record<string, unknown>;

  // Skip progress events in compact mode
  if (compact && event.type === 'gauntlet_progress') {
    return null;
  }

  const renderEventContent = () => {
    switch (event.type) {
      case 'gauntlet_start':
        return (
          <span className="text-text">
            Gauntlet started - {String(data.input_type || 'unknown')} input
          </span>
        );

      case 'gauntlet_phase':
        return (
          <span className="text-text">
            Phase:{' '}
            <span className="text-[var(--acid-cyan)] uppercase">
              {String(data.phase).replace(/_/g, ' ')}
            </span>
          </span>
        );

      case 'gauntlet_agent_active':
        return (
          <span className="text-text">
            Agent <span className="text-[var(--accent)]">{String(data.agent)}</span> activated
            {typeof data.role === 'string' && (
              <span className="text-text-muted"> ({data.role})</span>
            )}
          </span>
        );

      case 'gauntlet_attack':
        return (
          <span className="text-text">
            <span className="text-acid-red">{String(data.agent)}</span> launched attack
            {typeof data.attack_type === 'string' && (
              <span className="text-text-muted"> ({data.attack_type})</span>
            )}
          </span>
        );

      case 'gauntlet_probe':
        return (
          <span className="text-text">
            <span className="text-[var(--acid-yellow)]">{String(data.agent)}</span> probing
            {typeof data.target === 'string' && (
              <span className="text-text-muted"> {data.target}</span>
            )}
          </span>
        );

      case 'gauntlet_finding': {
        const severity = String(data.severity || 'MEDIUM').toUpperCase();
        const severityConfig = SEVERITY_CONFIG[severity] || SEVERITY_CONFIG.MEDIUM;
        return (
          <button
            onClick={() => {
              if (onFindingClick) {
                onFindingClick({
                  finding_id: String(data.finding_id || ''),
                  severity: severity as GauntletFinding['severity'],
                  category: String(data.category || ''),
                  title: String(data.title || ''),
                  description: String(data.description || ''),
                  source: String(data.source || ''),
                });
              }
            }}
            className={`text-left ${severityConfig.text} hover:underline`}
          >
            <span className={`px-1 ${severityConfig.bg} rounded mr-1`}>{severity}</span>
            {String(data.title || 'Unknown')}
          </button>
        );
      }

      case 'gauntlet_verdict': {
        const verdict = String(data.verdict || 'UNKNOWN');
        const confidence = typeof data.confidence === 'number' ? data.confidence : 0;
        return (
          <span className="text-text">
            Verdict:{' '}
            <span
              className={
                verdict === 'APPROVED'
                  ? 'text-[var(--accent)]'
                  : verdict === 'REJECTED'
                    ? 'text-acid-red'
                    : 'text-[var(--acid-yellow)]'
              }
            >
              {verdict}
            </span>
            <span className="text-text-muted"> ({(confidence * 100).toFixed(0)}% confidence)</span>
          </span>
        );
      }

      case 'gauntlet_complete':
        return (
          <span className="text-[var(--accent)]">
            Gauntlet complete - {Number(data.findings_count) || 0} findings in{' '}
            {Number(data.duration_seconds) || 0}s
          </span>
        );

      case 'gauntlet_progress':
        return (
          <span className="text-text-muted">
            Progress: {((data.progress as number) * 100).toFixed(0)}%
          </span>
        );

      default:
        return (
          <span className="text-text-muted">
            {event.type.replace('gauntlet_', '').replace(/_/g, ' ')}
          </span>
        );
    }
  };

  return (
    <div
      className={`flex items-start gap-2 ${compact ? 'py-1' : 'py-2'} border-b border-border/30 last:border-0`}
    >
      <span className={`${config.color} ${compact ? 'text-sm' : 'text-base'}`}>{config.icon}</span>
      <div className="flex-1 min-w-0">
        <div className={`font-theme-data ${compact ? 'text-xs' : 'text-sm'}`}>
          {renderEventContent()}
        </div>
      </div>
      <span className={`font-theme-data text-text-muted ${compact ? 'text-[10px]' : 'text-xs'}`}>
        {formatTime(event.timestamp)}
      </span>
    </div>
  );
}

function AgentStats({
  agents,
}: {
  agents: Map<string, { name: string; status: string; attackCount: number; probeCount: number }>;
}) {
  const agentArray = Array.from(agents.values());

  if (agentArray.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2 p-2 bg-bg/50 border-b border-border">
      {agentArray.map((agent) => (
        <div
          key={agent.name}
          className={`px-2 py-1 rounded text-xs font-theme-data flex items-center gap-2 ${
            agent.status === 'active'
              ? 'bg-[var(--accent)]/10 border border-[var(--accent)]/30 text-[var(--accent)] animate-pulse'
              : agent.status === 'complete'
                ? 'bg-[var(--acid-cyan)]/10 border border-[var(--acid-cyan)]/30 text-[var(--acid-cyan)]'
                : 'bg-surface border border-border text-text-muted'
          }`}
        >
          <span>{agent.name}</span>
          <span className="text-acid-red">
            {agent.attackCount}
            {'\u26A1'}
          </span>
          <span className="text-[var(--acid-yellow)]">
            {agent.probeCount}
            {'\uD83D\uDD0D'}
          </span>
        </div>
      ))}
    </div>
  );
}

export function AttackFeed({
  gauntletId,
  wsUrl,
  maxEvents = 100,
  autoScroll = true,
  showAgentStats = true,
  compact = false,
  onFindingClick,
}: AttackFeedProps) {
  const [isPaused, setIsPaused] = useState(false);
  const feedRef = useRef<HTMLDivElement>(null);

  const {
    status,
    error,
    phase,
    progress,
    agents,
    findings,
    events,
    verdict,
    elapsedSeconds,
    reconnect,
  } = useGauntletWebSocket({ gauntletId, wsUrl });

  // Filter and limit events
  const displayEvents = useMemo(() => {
    // Filter out frequent progress events for cleaner display
    const filtered = events.filter((e, i) => {
      if (e.type === 'gauntlet_progress') {
        // Only show every 10th progress event
        return i % 10 === 0;
      }
      return true;
    });
    return filtered.slice(-maxEvents);
  }, [events, maxEvents]);

  // Auto-scroll to bottom
  useEffect(() => {
    if (autoScroll && !isPaused && feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [displayEvents, autoScroll, isPaused]);

  // Stats
  const stats = useMemo(() => {
    const totalAttacks = Array.from(agents.values()).reduce((sum, a) => sum + a.attackCount, 0);
    const totalProbes = Array.from(agents.values()).reduce((sum, a) => sum + a.probeCount, 0);
    return {
      attacks: totalAttacks,
      probes: totalProbes,
      findings: findings.length,
      critical: findings.filter((f) => f.severity === 'CRITICAL').length,
      high: findings.filter((f) => f.severity === 'HIGH').length,
    };
  }, [agents, findings]);

  const formatElapsed = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className="bg-surface border border-[var(--accent)]/30 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-[var(--accent)]/20 bg-bg/50 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-xs font-theme-data text-[var(--accent)] uppercase tracking-wider">
            {'>'} LIVE ATTACK FEED
          </span>
          <span
            className={`w-2 h-2 rounded-full ${
              status === 'streaming'
                ? 'bg-[var(--accent)] animate-pulse'
                : status === 'connecting'
                  ? 'bg-acid-yellow animate-pulse'
                  : status === 'complete'
                    ? 'bg-[var(--acid-cyan)]'
                    : 'bg-acid-red'
            }`}
          />
          <span className="text-xs font-theme-data text-text-muted uppercase">{status}</span>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-xs font-theme-data text-[var(--acid-cyan)]">
            {formatElapsed(elapsedSeconds)}
          </span>
          <span className="text-xs font-theme-data text-text-muted">
            {(progress * 100).toFixed(0)}%
          </span>
          {status === 'error' && (
            <button
              onClick={reconnect}
              className="px-2 py-1 text-xs font-theme-data bg-[var(--accent)]/10 text-[var(--accent)] hover:bg-[var(--accent)]/20 rounded"
            >
              RECONNECT
            </button>
          )}
        </div>
      </div>

      {/* Phase indicator */}
      {status === 'streaming' && (
        <div className="px-4 py-2 bg-surface/50 border-b border-border flex items-center justify-between">
          <span className="text-xs font-theme-data text-text-muted">
            PHASE:{' '}
            <span className="text-[var(--acid-cyan)] uppercase">{phase.replace(/_/g, ' ')}</span>
          </span>
          <div className="flex gap-4 text-xs font-theme-data">
            <span className="text-acid-red">{stats.attacks} attacks</span>
            <span className="text-[var(--acid-yellow)]">{stats.probes} probes</span>
            <span className="text-warning">{stats.findings} findings</span>
          </div>
        </div>
      )}

      {/* Agent stats */}
      {showAgentStats && <AgentStats agents={agents} />}

      {/* Error message */}
      {error && (
        <div className="px-4 py-2 bg-acid-red/10 border-b border-acid-red/30">
          <span className="text-xs font-theme-data text-acid-red">{error}</span>
        </div>
      )}

      {/* Event feed */}
      <div
        ref={feedRef}
        className={`overflow-y-auto px-4 ${compact ? 'max-h-[300px]' : 'max-h-[400px]'}`}
        onMouseEnter={() => setIsPaused(true)}
        onMouseLeave={() => setIsPaused(false)}
      >
        {displayEvents.length === 0 && status === 'connecting' && (
          <div className="py-8 text-center">
            <div className="text-[var(--accent)] font-theme-data animate-pulse">
              Connecting to stress test...
            </div>
          </div>
        )}
        {displayEvents.length === 0 && status === 'streaming' && (
          <div className="py-8 text-center">
            <div className="text-text-muted font-theme-data">Waiting for events...</div>
          </div>
        )}
        {displayEvents.map((event, index) => (
          <EventRow
            key={`${event.seq}-${index}`}
            event={event}
            compact={compact}
            onFindingClick={onFindingClick}
          />
        ))}
      </div>

      {/* Verdict (when complete) */}
      {verdict && (
        <div
          className={`p-4 border-t border-border ${
            verdict.verdict === 'APPROVED'
              ? 'bg-[var(--accent)]/10'
              : verdict.verdict === 'REJECTED'
                ? 'bg-acid-red/10'
                : 'bg-acid-yellow/10'
          }`}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="text-2xl">
                {verdict.verdict === 'APPROVED'
                  ? '\u2713'
                  : verdict.verdict === 'REJECTED'
                    ? '\u2717'
                    : '\u26A0'}
              </span>
              <div>
                <div
                  className={`font-theme-data text-lg ${
                    verdict.verdict === 'APPROVED'
                      ? 'text-[var(--accent)]'
                      : verdict.verdict === 'REJECTED'
                        ? 'text-acid-red'
                        : 'text-[var(--acid-yellow)]'
                  }`}
                >
                  {verdict.verdict.replace(/_/g, ' ')}
                </div>
                <div className="text-xs font-theme-data text-text-muted">
                  {(verdict.confidence * 100).toFixed(0)}% confidence
                </div>
              </div>
            </div>
            <div className="flex gap-2 text-xs font-theme-data">
              {verdict.findings.critical > 0 && (
                <span className="px-2 py-1 bg-acid-red/20 text-acid-red rounded">
                  {verdict.findings.critical} CRIT
                </span>
              )}
              {verdict.findings.high > 0 && (
                <span className="px-2 py-1 bg-warning/20 text-warning rounded">
                  {verdict.findings.high} HIGH
                </span>
              )}
              {verdict.findings.medium > 0 && (
                <span className="px-2 py-1 bg-acid-yellow/20 text-[var(--acid-yellow)] rounded">
                  {verdict.findings.medium} MED
                </span>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Footer */}
      <div className="px-4 py-2 border-t border-border bg-bg/50 flex items-center justify-between text-xs font-theme-data text-text-muted">
        <span>{displayEvents.length} events</span>
        {isPaused && <span className="text-[var(--acid-yellow)]">PAUSED (hover)</span>}
        <span>ID: {gauntletId.slice(-8)}</span>
      </div>
    </div>
  );
}

export default AttackFeed;
