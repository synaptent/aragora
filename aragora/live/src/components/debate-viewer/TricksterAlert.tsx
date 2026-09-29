'use client';

import { useState, useEffect } from 'react';
import { API_BASE_URL } from '@/config';
import { logger } from '@/utils/logger';

interface HollowConsensusAlert {
  round: number;
  severity: number;
  evidence_quality: number;
  convergence: number;
  gaps: Record<string, string[]>;
}

interface TricksterIntervention {
  round: number;
  type: string;
  target_agents: string[];
  challenge: string;
  priority: number;
}

interface TricksterData {
  debate_id: string;
  trickster_enabled: boolean;
  hollow_consensus_alerts: HollowConsensusAlert[];
  interventions: TricksterIntervention[];
  total_alerts: number;
  total_interventions: number;
  config: {
    sensitivity: number;
    min_quality_threshold: number;
    hollow_detection_threshold: number;
  };
}

interface TricksterAlertProps {
  debateId: string;
}

const INTERVENTION_ICONS: Record<string, string> = {
  challenge_prompt: '💬',
  quality_role: '🎭',
  extended_round: '⏳',
  breakpoint: '🛑',
  novelty_challenge: '💡',
  evidence_gap: '📋',
  echo_chamber: '🔊',
};

const SEVERITY_COLORS: Record<string, string> = {
  low: 'border-yellow-500/30 bg-yellow-500/10',
  medium: 'border-orange-500/30 bg-orange-500/10',
  high: 'border-red-500/30 bg-red-500/10',
};

function getSeverityLevel(severity: number): string {
  if (severity >= 0.7) return 'high';
  if (severity >= 0.4) return 'medium';
  return 'low';
}

export function TricksterAlert({ debateId }: TricksterAlertProps) {
  const [data, setData] = useState<TricksterData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    async function fetchTricksterData() {
      try {
        setLoading(true);
        const response = await fetch(`${API_BASE_URL}/api/debates/${debateId}/trickster`);
        if (!response.ok) {
          if (response.status === 404) {
            setError('Trickster analysis not available for this debate');
          } else {
            throw new Error(`HTTP ${response.status}`);
          }
          return;
        }
        const result = await response.json();
        setData(result);
      } catch (err) {
        logger.error('Failed to fetch trickster data:', err);
        setError('Failed to load trickster analysis');
      } finally {
        setLoading(false);
      }
    }

    fetchTricksterData();
  }, [debateId]);

  if (loading) {
    return (
      <div className="bg-surface border border-[var(--accent)]/30 p-4">
        <div className="text-xs font-theme-data text-text-muted animate-pulse">
          Checking for hollow consensus...
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="bg-surface border border-yellow-500/30 p-4">
        <div className="text-xs font-theme-data text-yellow-500">
          {error || 'No trickster data available'}
        </div>
      </div>
    );
  }

  // If no alerts, show a success indicator
  if (data.total_alerts === 0) {
    return (
      <div className="bg-surface border border-green-500/30 p-4">
        <div className="flex items-center gap-2">
          <span className="text-green-400">✓</span>
          <span className="text-xs font-theme-data text-green-400">
            CONSENSUS INTEGRITY: No hollow consensus detected
          </span>
        </div>
      </div>
    );
  }

  const maxSeverity = Math.max(...data.hollow_consensus_alerts.map((a) => a.severity));
  const severityLevel = getSeverityLevel(maxSeverity);

  return (
    <div className={`bg-surface border ${SEVERITY_COLORS[severityLevel]}`}>
      {/* Header */}
      <div
        className="px-4 py-3 border-b border-current/20 cursor-pointer flex items-center justify-between"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2">
          <span className="text-lg">🎭</span>
          <span
            className={`text-xs font-theme-data uppercase tracking-wider ${
              severityLevel === 'high'
                ? 'text-red-400'
                : severityLevel === 'medium'
                  ? 'text-orange-400'
                  : 'text-yellow-400'
            }`}
          >
            TRICKSTER ALERT: {data.total_alerts} hollow consensus{' '}
            {data.total_alerts === 1 ? 'warning' : 'warnings'}
          </span>
        </div>
        <span className="text-xs font-theme-data text-text-muted">{expanded ? '[-]' : '[+]'}</span>
      </div>

      {expanded && (
        <div className="p-4 space-y-4">
          {/* Summary */}
          <div className="bg-bg/50 border border-border rounded p-3">
            <div className="text-xs font-theme-data text-text-muted uppercase mb-2">
              Detection Summary
            </div>
            <div className="grid grid-cols-3 gap-4 text-xs font-theme-data">
              <div>
                <span className="text-text-muted">Alerts: </span>
                <span className="text-text">{data.total_alerts}</span>
              </div>
              <div>
                <span className="text-text-muted">Interventions: </span>
                <span className="text-text">{data.total_interventions}</span>
              </div>
              <div>
                <span className="text-text-muted">Sensitivity: </span>
                <span className="text-text">{Math.round(data.config.sensitivity * 100)}%</span>
              </div>
            </div>
          </div>

          {/* Alerts */}
          <div className="space-y-2">
            <div className="text-xs font-theme-data text-text-muted uppercase">
              Hollow Consensus Alerts
            </div>
            {data.hollow_consensus_alerts.map((alert, idx) => {
              const level = getSeverityLevel(alert.severity);
              return (
                <div key={idx} className={`p-3 border rounded ${SEVERITY_COLORS[level]}`}>
                  <div className="flex items-center justify-between mb-2">
                    <div className="text-xs font-theme-data font-bold">Round {alert.round}</div>
                    <div className="flex gap-4 text-xs font-theme-data text-text-muted">
                      <span>Severity: {Math.round(alert.severity * 100)}%</span>
                      <span>Evidence Quality: {Math.round(alert.evidence_quality * 100)}%</span>
                      <span>Convergence: {Math.round(alert.convergence * 100)}%</span>
                    </div>
                  </div>
                  {alert.gaps && Object.keys(alert.gaps).length > 0 && (
                    <div className="mt-2">
                      <div className="text-xs font-theme-data text-text-muted mb-1">
                        Evidence Gaps:
                      </div>
                      <div className="space-y-1">
                        {Object.entries(alert.gaps).map(([agent, gaps]) => (
                          <div key={agent} className="text-xs font-theme-data">
                            <span className="text-text">{agent}: </span>
                            <span className="text-text-muted">{(gaps as string[]).join(', ')}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Interventions */}
          {data.interventions.length > 0 && (
            <div className="space-y-2">
              <div className="text-xs font-theme-data text-text-muted uppercase">
                Trickster Interventions
              </div>
              {data.interventions.map((intervention, idx) => (
                <div key={idx} className="p-3 border border-purple-500/30 bg-purple-500/10 rounded">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span>{INTERVENTION_ICONS[intervention.type] || '🎭'}</span>
                      <span className="text-xs font-theme-data text-purple-400 uppercase">
                        {intervention.type.replace(/_/g, ' ')}
                      </span>
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">
                      Round {intervention.round} | Priority:{' '}
                      {Math.round(intervention.priority * 100)}%
                    </div>
                  </div>
                  <div className="text-xs font-theme-data text-text mb-2">
                    Target: {intervention.target_agents.join(', ')}
                  </div>
                  <div className="text-xs font-theme-data text-text-muted bg-bg/50 p-2 rounded">
                    &ldquo;{intervention.challenge}&rdquo;
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
