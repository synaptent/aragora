'use client';

import { useMemo } from 'react';
import type { StreamEvent, HollowConsensusData, TricksterInterventionData } from '@/types/events';

interface TricksterAlertPanelProps {
  events: StreamEvent[];
}

interface TricksterAlert {
  type: 'hollow_consensus' | 'intervention';
  round: number;
  timestamp: number;
  data: HollowConsensusData | TricksterInterventionData;
}

function getSeverityColor(metric: number): string {
  if (metric >= 0.8) return 'text-[var(--crimson)]';
  if (metric >= 0.6) return 'text-orange-400';
  if (metric >= 0.4) return 'text-yellow-400';
  return 'text-[var(--acid-cyan)]';
}

function getSeverityBg(metric: number): string {
  if (metric >= 0.8) return 'bg-[var(--crimson)]/20 border-[var(--crimson)]/40';
  if (metric >= 0.6) return 'bg-orange-400/20 border-orange-400/40';
  if (metric >= 0.4) return 'bg-yellow-400/20 border-yellow-400/40';
  return 'bg-[var(--acid-cyan)]/20 border-[var(--acid-cyan)]/40';
}

export function TricksterAlertPanel({ events }: TricksterAlertPanelProps) {
  const alerts = useMemo(() => {
    const alertList: TricksterAlert[] = [];

    for (const event of events) {
      if (event.type === 'hollow_consensus') {
        alertList.push({
          type: 'hollow_consensus',
          round: event.round || 0,
          timestamp: event.timestamp,
          data: event.data as HollowConsensusData,
        });
      } else if (event.type === 'trickster_intervention') {
        alertList.push({
          type: 'intervention',
          round: event.round || 0,
          timestamp: event.timestamp,
          data: event.data as TricksterInterventionData,
        });
      }
    }

    return alertList.sort((a, b) => b.timestamp - a.timestamp);
  }, [events]);

  if (alerts.length === 0) {
    return null;
  }

  return (
    <div className="bg-surface border border-[var(--crimson)]/30">
      <div className="px-4 py-3 border-b border-[var(--crimson)]/20 bg-bg/50 flex items-center justify-between">
        <span className="text-xs font-theme-data text-[var(--crimson)] uppercase tracking-wider">
          {'>'} TRICKSTER ALERTS
        </span>
        <span className="text-xs font-theme-data text-[var(--crimson)] animate-pulse">
          {alerts.length} alert{alerts.length !== 1 ? 's' : ''}
        </span>
      </div>

      <div className="p-4 space-y-3 max-h-64 overflow-y-auto">
        {alerts.map((alert, idx) => {
          if (alert.type === 'hollow_consensus') {
            const data = alert.data as HollowConsensusData;
            const severity = data.metric || 0.5;
            return (
              <div key={`hollow-${idx}`} className={`p-3 border ${getSeverityBg(severity)}`}>
                <div className="flex items-center justify-between mb-2">
                  <span className={`text-xs font-theme-data ${getSeverityColor(severity)}`}>
                    HOLLOW CONSENSUS
                  </span>
                  <span className="text-xs font-theme-data text-text-muted">
                    Round {alert.round}
                  </span>
                </div>
                <div className="text-xs font-theme-data text-text-primary">{data.details}</div>
                <div className="text-xs font-theme-data text-text-muted mt-1">
                  Evidence gap: {(severity * 100).toFixed(0)}%
                </div>
              </div>
            );
          } else {
            const data = alert.data as TricksterInterventionData;
            const priority = data.priority || 0.5;
            return (
              <div key={`intervention-${idx}`} className={`p-3 border ${getSeverityBg(priority)}`}>
                <div className="flex items-center justify-between mb-2">
                  <span className={`text-xs font-theme-data ${getSeverityColor(priority)}`}>
                    CHALLENGE INJECTED
                  </span>
                  <span className="text-xs font-theme-data text-text-muted">
                    Round {data.round_num}
                  </span>
                </div>
                <div className="text-xs font-theme-data text-text-primary mb-2">
                  {data.challenge}
                </div>
                <div className="flex flex-wrap gap-1">
                  <span className="text-xs font-theme-data text-text-muted">Targets:</span>
                  {data.targets.map((target) => (
                    <span
                      key={target}
                      className="px-1.5 py-0.5 text-xs font-theme-data bg-[var(--crimson)]/10 text-[var(--crimson)] border border-[var(--crimson)]/30"
                    >
                      {target.split('-')[0]}
                    </span>
                  ))}
                </div>
                <div className="text-xs font-theme-data text-text-muted mt-1">
                  Type: {data.intervention_type}
                </div>
              </div>
            );
          }
        })}
      </div>
    </div>
  );
}
