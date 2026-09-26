'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { logger } from '@/utils/logger';
import type { StreamEvent } from '@/types/events';

interface CalibrationAgent {
  name: string;
  elo: number;
  calibration_score: number;
  brier_score: number;
  accuracy: number;
  games: number;
}

interface CalibrationBucket {
  bucket: string;
  predicted: number;
  actual: number;
  count: number;
}

interface AgentCalibration {
  agent: string;
  ece: number;
  buckets: CalibrationBucket[];
  domain_calibration: Record<string, number> | null;
}

interface CalibrationPanelProps {
  apiBase: string;
  events?: StreamEvent[];
}

export function CalibrationPanel({ apiBase, events = [] }: CalibrationPanelProps) {
  const [expanded, setExpanded] = useState(true); // Show by default
  const [agents, setAgents] = useState<CalibrationAgent[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [agentDetail, setAgentDetail] = useState<AgentCalibration | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Extract calibration_update events from stream
  const calibrationEvents = useMemo(
    () => events.filter((e) => e.type === 'calibration_update'),
    [events],
  );
  const latestCalibrationEvent = calibrationEvents[calibrationEvents.length - 1];

  const fetchLeaderboard = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${apiBase}/api/calibration/leaderboard?limit=10`);
      if (!response.ok) throw new Error('Failed to fetch calibration data');
      const data = await response.json();
      setAgents(data.agents || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch calibration');
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  const fetchAgentDetail = useCallback(
    async (agentName: string) => {
      try {
        const response = await fetch(`${apiBase}/api/agent/${agentName}/calibration`);
        if (!response.ok) throw new Error('Failed to fetch agent calibration');
        const data = await response.json();
        setAgentDetail(data);
      } catch (err) {
        logger.error('Failed to fetch agent calibration:', err);
      }
    },
    [apiBase],
  );

  // Initial fetch on expand
  useEffect(() => {
    if (expanded) {
      fetchLeaderboard();
    }
  }, [expanded, fetchLeaderboard]);

  // Refresh when calibration_update event arrives
  useEffect(() => {
    if (latestCalibrationEvent && expanded) {
      // Refetch to get updated leaderboard
      fetchLeaderboard();
    }
  }, [latestCalibrationEvent, expanded, fetchLeaderboard]);

  useEffect(() => {
    if (selectedAgent) {
      fetchAgentDetail(selectedAgent);
    } else {
      setAgentDetail(null);
    }
  }, [selectedAgent, fetchAgentDetail]);

  // Score color based on calibration quality
  const getScoreColor = (score: number) => {
    if (score >= 0.8) return 'text-[var(--accent)]';
    if (score >= 0.6) return 'text-[var(--acid-cyan)]';
    if (score >= 0.4) return 'text-warning';
    return 'text-error';
  };

  // Brier score color (lower is better, 0 is perfect)
  const getBrierColor = (brier: number) => {
    if (brier <= 0.1) return 'text-[var(--accent)]';
    if (brier <= 0.2) return 'text-[var(--acid-cyan)]';
    if (brier <= 0.3) return 'text-warning';
    return 'text-error';
  };

  return (
    <div className="panel" style={{ padding: 0 }}>
      {/* Header */}
      <button onClick={() => setExpanded(!expanded)} className="panel-collapsible-header w-full">
        <div className="flex items-center gap-2">
          <span className="text-[var(--acid-cyan)] font-theme-data text-sm">[CALIBRATION]</span>
          <span className="text-text-muted text-xs">Confidence accuracy scores</span>
        </div>
        <span className="panel-toggle">{expanded ? '[-]' : '[+]'}</span>
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-3">
          {loading ? (
            <div className="text-text-muted text-xs text-center py-4 animate-pulse">
              Loading calibration data...
            </div>
          ) : error ? (
            <div className="text-warning text-xs text-center py-4">{error}</div>
          ) : agents.length === 0 ? (
            <div className="text-text-muted text-xs text-center py-4">
              No calibration data available
            </div>
          ) : (
            <>
              {/* Leaderboard */}
              <div className="space-y-1 max-h-48 overflow-y-auto">
                {agents.map((agent, idx) => (
                  <button
                    key={agent.name}
                    onClick={() =>
                      setSelectedAgent(selectedAgent === agent.name ? null : agent.name)
                    }
                    className={`w-full text-left border p-2 text-xs transition-colors ${
                      selectedAgent === agent.name
                        ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                        : 'border-[var(--accent)]/20 hover:border-[var(--accent)]/40'
                    }`}
                  >
                    <div className="flex justify-between items-center">
                      <div className="flex items-center gap-2">
                        <span className="text-text-muted w-4">#{idx + 1}</span>
                        <span className="font-theme-data text-[var(--acid-cyan)]">
                          {agent.name}
                        </span>
                      </div>
                      <span className={getScoreColor(agent.calibration_score)}>
                        {(agent.calibration_score * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div className="flex justify-between mt-1 text-text-muted/70">
                      <span>
                        Brier:{' '}
                        <span className={getBrierColor(agent.brier_score)}>
                          {agent.brier_score.toFixed(3)}
                        </span>
                      </span>
                      <span>Acc: {(agent.accuracy * 100).toFixed(0)}%</span>
                      <span>{agent.games} games</span>
                    </div>
                  </button>
                ))}
              </div>

              {/* Agent Detail */}
              {agentDetail && (
                <div className="border border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/5 p-3 space-y-2">
                  <div className="flex justify-between items-center">
                    <span className="font-theme-data text-[var(--acid-cyan)] text-sm">
                      {agentDetail.agent}
                    </span>
                    <span className="text-xs text-text-muted">
                      ECE:{' '}
                      <span className={getBrierColor(agentDetail.ece)}>
                        {agentDetail.ece.toFixed(3)}
                      </span>
                    </span>
                  </div>

                  {/* Calibration buckets visualization */}
                  {agentDetail.buckets && agentDetail.buckets.length > 0 && (
                    <div className="space-y-1">
                      <div className="text-xs text-text-muted">Calibration by confidence:</div>
                      {agentDetail.buckets.map((bucket) => (
                        <div key={bucket.bucket} className="flex items-center gap-2 text-xs">
                          <span className="w-16 text-text-muted">{bucket.bucket}</span>
                          <div className="flex-1 h-2 bg-bg/50 relative">
                            <div
                              className="absolute h-full bg-[var(--acid-cyan)]/50"
                              style={{ width: `${bucket.predicted * 100}%` }}
                            />
                            <div
                              className="absolute h-full bg-[var(--accent)]"
                              style={{ width: `${bucket.actual * 100}%`, opacity: 0.7 }}
                            />
                          </div>
                          <span className="w-8 text-right">{bucket.count}</span>
                        </div>
                      ))}
                      <div className="text-xs text-text-muted/50 flex gap-4 mt-1">
                        <span>
                          <span className="inline-block w-2 h-2 bg-[var(--acid-cyan)]/50 mr-1" />
                          predicted
                        </span>
                        <span>
                          <span className="inline-block w-2 h-2 bg-[var(--accent)] mr-1" />
                          actual
                        </span>
                      </div>
                    </div>
                  )}

                  {/* Domain calibration */}
                  {agentDetail.domain_calibration &&
                    Object.keys(agentDetail.domain_calibration).length > 0 && (
                      <div className="mt-2 pt-2 border-t border-[var(--acid-cyan)]/20">
                        <div className="text-xs text-text-muted mb-1">By domain:</div>
                        <div className="flex flex-wrap gap-2">
                          {Object.entries(agentDetail.domain_calibration).map(([domain, score]) => (
                            <span
                              key={domain}
                              className={`text-xs px-1 py-0.5 border border-[var(--accent)]/30 ${getScoreColor(score as number)}`}
                            >
                              {domain}: {((score as number) * 100).toFixed(0)}%
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                </div>
              )}

              {/* Legend */}
              <div className="text-xs text-text-muted/50 text-center">
                Calibration = how well confidence matches accuracy
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
