'use client';

import { useState } from 'react';
import {
  useGauntletWebSocket,
  GauntletAgent,
  GauntletFinding,
  GauntletVerdict,
  GauntletConnectionStatus,
} from '@/hooks/useGauntletWebSocket';

interface GauntletLiveProps {
  gauntletId: string;
  wsUrl?: string;
  onComplete?: (verdict: GauntletVerdict) => void;
}

const STATUS_CONFIG: Record<GauntletConnectionStatus, { color: string; label: string }> = {
  connecting: { color: 'bg-yellow-400', label: 'CONNECTING...' },
  streaming: { color: 'bg-green-400 animate-pulse', label: 'STRESS-TEST RUNNING' },
  complete: { color: 'bg-blue-400', label: 'GAUNTLET COMPLETE' },
  error: { color: 'bg-red-400', label: 'CONNECTION ERROR' },
};

const SEVERITY_CONFIG = {
  CRITICAL: {
    bg: 'bg-red-500/20',
    border: 'border-red-500/50',
    text: 'text-red-400',
    label: 'CRITICAL',
  },
  HIGH: {
    bg: 'bg-orange-500/20',
    border: 'border-orange-500/50',
    text: 'text-orange-400',
    label: 'HIGH',
  },
  MEDIUM: {
    bg: 'bg-yellow-500/20',
    border: 'border-yellow-500/50',
    text: 'text-yellow-400',
    label: 'MEDIUM',
  },
  LOW: {
    bg: 'bg-[var(--acid-cyan)]/20',
    border: 'border-[var(--acid-cyan)]/50',
    text: 'text-[var(--acid-cyan)]',
    label: 'LOW',
  },
};

const VERDICT_CONFIG = {
  APPROVED: {
    bg: 'bg-green-500/20',
    border: 'border-green-500',
    text: 'text-green-400',
    icon: '\u2713',
  },
  APPROVED_WITH_CONDITIONS: {
    bg: 'bg-yellow-500/20',
    border: 'border-yellow-500',
    text: 'text-yellow-400',
    icon: '\u26A0',
  },
  NEEDS_REVIEW: {
    bg: 'bg-orange-500/20',
    border: 'border-orange-500',
    text: 'text-orange-400',
    icon: '\u2691',
  },
  REJECTED: { bg: 'bg-red-500/20', border: 'border-red-500', text: 'text-red-400', icon: '\u2717' },
};

const AGENT_STATUS_CONFIG = {
  idle: { bg: 'bg-surface', border: 'border-border', text: 'text-text-muted', pulse: false },
  active: {
    bg: 'bg-[var(--accent)]/10',
    border: 'border-[var(--accent)]/50',
    text: 'text-[var(--accent)]',
    pulse: true,
  },
  complete: {
    bg: 'bg-[var(--acid-cyan)]/10',
    border: 'border-[var(--acid-cyan)]/50',
    text: 'text-[var(--acid-cyan)]',
    pulse: false,
  },
};

function AgentCard({ agent }: { agent: GauntletAgent }) {
  const config = AGENT_STATUS_CONFIG[agent.status];

  return (
    <div
      className={`p-3 rounded border ${config.bg} ${config.border} ${config.pulse ? 'animate-pulse' : ''}`}
    >
      <div className="flex items-center justify-between mb-2">
        <span className={`font-theme-data text-sm ${config.text}`}>{agent.name}</span>
        <span className="text-xs font-theme-data text-text-muted uppercase">{agent.status}</span>
      </div>
      <div className="text-xs text-text-muted font-theme-data mb-2">{agent.role}</div>
      <div className="flex gap-4 text-xs font-theme-data">
        <span className="text-red-400">{agent.attackCount} attacks</span>
        <span className="text-[var(--acid-cyan)]">{agent.probeCount} probes</span>
      </div>
    </div>
  );
}

function FindingCard({ finding }: { finding: GauntletFinding }) {
  const config = SEVERITY_CONFIG[finding.severity];

  return (
    <div className={`p-3 rounded border-l-4 ${config.bg} ${config.border}`}>
      <div className="flex items-center gap-2 mb-1">
        <span
          className={`text-xs font-theme-data uppercase px-2 py-0.5 rounded ${config.bg} ${config.text}`}
        >
          {finding.severity}
        </span>
        <span className="text-xs font-theme-data text-text-muted">{finding.category}</span>
      </div>
      <h4 className={`font-theme-data text-sm ${config.text} mb-1`}>{finding.title}</h4>
      <p className="text-xs text-text-muted font-theme-data line-clamp-2">{finding.description}</p>
      <div className="text-xs font-theme-data text-text-muted/60 mt-1">
        Source: {finding.source}
      </div>
    </div>
  );
}

function VerdictPanel({ verdict }: { verdict: GauntletVerdict }) {
  const config = VERDICT_CONFIG[verdict.verdict];

  return (
    <div className={`p-6 rounded border-2 ${config.bg} ${config.border}`}>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <span className={`text-4xl ${config.text}`}>{config.icon}</span>
          <div>
            <h3 className={`text-xl font-theme-data ${config.text}`}>
              {verdict.verdict.replace('_', ' ')}
            </h3>
            <span className="text-sm font-theme-data text-text-muted">
              Confidence: {(verdict.confidence * 100).toFixed(0)}%
            </span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 mb-4">
        <div className="p-3 bg-surface rounded">
          <div className="text-xs font-theme-data text-text-muted mb-1">Risk Score</div>
          <div className="text-2xl font-theme-data text-[var(--accent)]">
            {(verdict.riskScore * 100).toFixed(0)}
          </div>
        </div>
        <div className="p-3 bg-surface rounded">
          <div className="text-xs font-theme-data text-text-muted mb-1">Robustness</div>
          <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">
            {(verdict.robustnessScore * 100).toFixed(0)}
          </div>
        </div>
      </div>

      <div className="text-xs font-theme-data text-text-muted mb-2">Findings Summary</div>
      <div className="flex flex-wrap gap-2">
        {verdict.findings.critical > 0 && (
          <span className="px-2 py-1 bg-red-500/20 text-red-400 rounded text-xs font-theme-data">
            {verdict.findings.critical} Critical
          </span>
        )}
        {verdict.findings.high > 0 && (
          <span className="px-2 py-1 bg-orange-500/20 text-orange-400 rounded text-xs font-theme-data">
            {verdict.findings.high} High
          </span>
        )}
        {verdict.findings.medium > 0 && (
          <span className="px-2 py-1 bg-yellow-500/20 text-yellow-400 rounded text-xs font-theme-data">
            {verdict.findings.medium} Medium
          </span>
        )}
        {verdict.findings.low > 0 && (
          <span className="px-2 py-1 bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] rounded text-xs font-theme-data">
            {verdict.findings.low} Low
          </span>
        )}
        <span className="px-2 py-1 bg-surface text-text-muted rounded text-xs font-theme-data">
          {verdict.findings.total} Total
        </span>
      </div>
    </div>
  );
}

function ProgressBar({ progress, phase }: { progress: number; phase: string }) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs font-theme-data">
        <span className="text-[var(--acid-cyan)] uppercase">{phase.replace('_', ' ')}</span>
        <span className="text-text-muted">{(progress * 100).toFixed(0)}%</span>
      </div>
      <div className="h-2 bg-surface rounded overflow-hidden">
        <div
          className="h-full bg-[var(--accent)] transition-all duration-300"
          style={{ width: `${progress * 100}%` }}
        />
      </div>
    </div>
  );
}

function formatElapsed(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

export function GauntletLive({ gauntletId, wsUrl, onComplete }: GauntletLiveProps) {
  const [showFindings, setShowFindings] = useState(true);
  const [showAgents, setShowAgents] = useState(true);

  const {
    status,
    error,
    inputType,
    inputSummary,
    phase,
    progress,
    agents,
    findings,
    verdict,
    elapsedSeconds,
    reconnect,
    reconnectAttempt,
  } = useGauntletWebSocket({ gauntletId, wsUrl });

  // Notify parent when complete
  if (status === 'complete' && verdict && onComplete) {
    onComplete(verdict);
  }

  const statusConfig = STATUS_CONFIG[status];
  const agentArray = Array.from(agents.values());

  // Count findings by severity
  const findingCounts = {
    critical: findings.filter((f) => f.severity === 'CRITICAL').length,
    high: findings.filter((f) => f.severity === 'HIGH').length,
    medium: findings.filter((f) => f.severity === 'MEDIUM').length,
    low: findings.filter((f) => f.severity === 'LOW').length,
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-surface border border-[var(--accent)]/30 p-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            <div className="flex items-center gap-2 text-xs font-theme-data mb-2">
              <span className={`w-2 h-2 rounded-full ${statusConfig.color}`} />
              <span className="text-text-muted uppercase">{statusConfig.label}</span>
              <span className="text-text-muted">|</span>
              <span className="text-[var(--acid-cyan)]">{formatElapsed(elapsedSeconds)}</span>
            </div>

            {inputType && (
              <div className="mb-2">
                <span className="text-xs font-theme-data text-text-muted">Input: </span>
                <span className="text-xs font-theme-data text-[var(--accent)] uppercase">
                  {inputType}
                </span>
              </div>
            )}

            {inputSummary && (
              <p className="text-sm font-theme-data text-text-muted line-clamp-2">{inputSummary}</p>
            )}
          </div>

          <div className="flex flex-col items-end gap-2">
            {/* Reconnection indicator */}
            {reconnectAttempt > 0 && status === 'connecting' && (
              <div className="flex items-center gap-2 px-3 py-1 bg-yellow-500/20 border border-yellow-500/30 rounded">
                <span className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse" />
                <span className="text-xs font-theme-data text-yellow-400">
                  RECONNECTING ({reconnectAttempt}/15)
                </span>
              </div>
            )}
            {status === 'error' && (
              <button
                onClick={reconnect}
                className="px-3 py-1 text-xs font-theme-data bg-[var(--accent)] text-bg hover:bg-[var(--accent)]/80 transition-colors"
              >
                [RECONNECT]
              </button>
            )}
            <div className="text-xs text-text-muted font-theme-data">ID: {gauntletId}</div>
          </div>
        </div>

        {error && (
          <div className="mt-4 p-3 bg-red-500/10 border border-red-500/30 rounded text-red-400 text-xs font-theme-data">
            Error: {error}
          </div>
        )}
      </div>

      {/* Progress Bar */}
      {status === 'streaming' && (
        <div className="bg-surface border border-[var(--accent)]/30 p-4">
          <ProgressBar progress={progress} phase={phase} />
        </div>
      )}

      {/* Verdict Panel (when complete) */}
      {verdict && <VerdictPanel verdict={verdict} />}

      {/* Live Findings Summary */}
      {status === 'streaming' && findings.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {findingCounts.critical > 0 && (
            <span className="px-2 py-1 bg-red-500/20 border border-red-500/30 text-red-400 rounded text-xs font-theme-data animate-pulse">
              {findingCounts.critical} CRITICAL
            </span>
          )}
          {findingCounts.high > 0 && (
            <span className="px-2 py-1 bg-orange-500/20 border border-orange-500/30 text-orange-400 rounded text-xs font-theme-data">
              {findingCounts.high} HIGH
            </span>
          )}
          {findingCounts.medium > 0 && (
            <span className="px-2 py-1 bg-yellow-500/20 border border-yellow-500/30 text-yellow-400 rounded text-xs font-theme-data">
              {findingCounts.medium} MEDIUM
            </span>
          )}
          {findingCounts.low > 0 && (
            <span className="px-2 py-1 bg-[var(--acid-cyan)]/20 border border-[var(--acid-cyan)]/30 text-[var(--acid-cyan)] rounded text-xs font-theme-data">
              {findingCounts.low} LOW
            </span>
          )}
        </div>
      )}

      {/* Main Content Grid */}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* Agents Panel */}
        <div className="bg-surface border border-[var(--accent)]/30">
          <div className="px-4 py-3 border-b border-[var(--accent)]/20 bg-bg/50 flex items-center justify-between">
            <span className="text-xs font-theme-data text-[var(--accent)] uppercase tracking-wider">
              {'>'} AGENTS ({agentArray.length})
            </span>
            <button
              onClick={() => setShowAgents(!showAgents)}
              className="text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
            >
              {showAgents ? '[COLLAPSE]' : '[EXPAND]'}
            </button>
          </div>

          {showAgents && (
            <div className="p-4 space-y-3 max-h-[400px] overflow-y-auto">
              {agentArray.length === 0 ? (
                <div className="text-center py-8 text-text-muted font-theme-data">
                  <div className="animate-pulse">Waiting for agents...</div>
                </div>
              ) : (
                agentArray.map((agent) => <AgentCard key={agent.name} agent={agent} />)
              )}
            </div>
          )}
        </div>

        {/* Findings Panel */}
        <div className="bg-surface border border-[var(--accent)]/30">
          <div className="px-4 py-3 border-b border-[var(--accent)]/20 bg-bg/50 flex items-center justify-between">
            <span className="text-xs font-theme-data text-[var(--accent)] uppercase tracking-wider">
              {'>'} FINDINGS ({findings.length})
            </span>
            <button
              onClick={() => setShowFindings(!showFindings)}
              className="text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
            >
              {showFindings ? '[COLLAPSE]' : '[EXPAND]'}
            </button>
          </div>

          {showFindings && (
            <div className="p-4 space-y-3 max-h-[400px] overflow-y-auto">
              {findings.length === 0 ? (
                <div className="text-center py-8 text-text-muted font-theme-data">
                  {status === 'streaming' ? (
                    <div className="animate-pulse">Scanning for vulnerabilities...</div>
                  ) : (
                    <div>No findings discovered</div>
                  )}
                </div>
              ) : (
                findings.map((finding) => (
                  <FindingCard key={finding.finding_id} finding={finding} />
                ))
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default GauntletLive;
