'use client';

import { useMemo } from 'react';
import { getAgentColors } from '@/utils/agentColors';
import type { StreamEvent, CritiqueMessage } from '@/types/events';

interface CritiqueSeverityMeterProps {
  events: StreamEvent[];
  agents: string[];
}

interface CritiqueData {
  agent: string;
  target: string;
  severity: number;
  issues: string[];
  round: number;
  timestamp: number;
}

// Severity is now 0-10 scale (0=trivial, 10=critical)
function getSeverityLabel(severity: number): string {
  if (severity >= 8) return 'CRITICAL';
  if (severity >= 6) return 'MAJOR';
  if (severity >= 4) return 'MODERATE';
  if (severity >= 2) return 'MINOR';
  return 'TRIVIAL';
}

function getSeverityColor(severity: number): string {
  if (severity >= 8) return 'text-[var(--crimson)]';
  if (severity >= 6) return 'text-orange-400';
  if (severity >= 4) return 'text-yellow-400';
  if (severity >= 2) return 'text-[var(--acid-cyan)]';
  return 'text-text-muted';
}

function getSeverityBg(severity: number): string {
  if (severity >= 8) return 'bg-[var(--crimson)]';
  if (severity >= 6) return 'bg-orange-400';
  if (severity >= 4) return 'bg-yellow-400';
  if (severity >= 2) return 'bg-[var(--acid-cyan)]';
  return 'bg-text-muted';
}

export function CritiqueSeverityMeter({ events, agents: _agents }: CritiqueSeverityMeterProps) {
  const { critiques, avgSeverity, maxSeverity, critiquesByAgent } = useMemo(() => {
    const critiqueList: CritiqueData[] = [];

    for (const event of events) {
      if (event.type === 'critique') {
        const data = event.data as unknown as CritiqueMessage;
        critiqueList.push({
          agent: data.agent,
          target: data.target,
          severity: data.severity ?? 5, // Default to middle of 0-10 scale
          issues: data.issues || [],
          round: event.round || 0,
          timestamp: event.timestamp,
        });
      }
    }

    // Calculate stats
    const avg =
      critiqueList.length > 0
        ? critiqueList.reduce((sum, c) => sum + c.severity, 0) / critiqueList.length
        : 0;
    const max = critiqueList.length > 0 ? Math.max(...critiqueList.map((c) => c.severity)) : 0;

    // Group by agent (who gave the critique)
    const byAgent = new Map<string, CritiqueData[]>();
    for (const critique of critiqueList) {
      const existing = byAgent.get(critique.agent) || [];
      byAgent.set(critique.agent, [...existing, critique]);
    }

    return {
      critiques: critiqueList,
      avgSeverity: avg,
      maxSeverity: max,
      critiquesByAgent: byAgent,
    };
  }, [events]);

  if (critiques.length === 0) {
    return (
      <div className="bg-surface border border-accent/30">
        <div className="px-4 py-3 border-b border-accent/20 bg-bg/50">
          <span className="text-xs font-theme-data text-accent uppercase tracking-wider">
            {'>'} CRITIQUE INTENSITY
          </span>
        </div>
        <div className="p-4 text-xs font-theme-data text-text-muted/60 italic">
          No critiques recorded yet...
        </div>
      </div>
    );
  }

  return (
    <div className="bg-surface border border-accent/30">
      <div className="px-4 py-3 border-b border-accent/20 bg-bg/50 flex items-center justify-between">
        <span className="text-xs font-theme-data text-accent uppercase tracking-wider">
          {'>'} CRITIQUE INTENSITY
        </span>
        <span className={`text-xs font-theme-data ${getSeverityColor(maxSeverity)}`}>
          {getSeverityLabel(maxSeverity)}
        </span>
      </div>

      <div className="p-4 space-y-4">
        {/* Average Severity Gauge */}
        <div className="space-y-2">
          <div className="flex justify-between text-xs font-theme-data text-text-muted">
            <span>Average Severity</span>
            <span>{avgSeverity.toFixed(1)}/10</span>
          </div>
          <div className="h-2 bg-bg border border-accent/20 overflow-hidden flex">
            {/* Gradient bar showing severity distribution (0-10 scale) */}
            <div
              className={`h-full transition-all duration-300 ${getSeverityBg(avgSeverity)}`}
              style={{ width: `${(avgSeverity / 10) * 100}%`, opacity: 0.7 }}
            />
          </div>
        </div>

        {/* Critique Count */}
        <div className="text-xs font-theme-data text-text-muted">
          {critiques.length} critique{critiques.length !== 1 ? 's' : ''} recorded
        </div>

        {/* Per-Agent Critique Summary */}
        <div className="space-y-2">
          {Array.from(critiquesByAgent.entries()).map(([agent, agentCritiques]) => {
            const colors = getAgentColors(agent);
            const agentAvg =
              agentCritiques.reduce((sum, c) => sum + c.severity, 0) / agentCritiques.length;

            return (
              <div key={agent} className="flex items-center gap-2">
                <span
                  className={`px-2 py-0.5 text-xs font-theme-data ${colors.bg} ${colors.text} ${colors.border} border min-w-[80px]`}
                >
                  {agent.split('-')[0]}
                </span>
                <div className="flex-1 h-1.5 bg-bg border border-accent/10 overflow-hidden">
                  <div
                    className={`h-full ${getSeverityBg(agentAvg)}`}
                    style={{ width: `${(agentAvg / 10) * 100}%`, opacity: 0.7 }}
                  />
                </div>
                <span
                  className={`text-xs font-theme-data ${getSeverityColor(agentAvg)} w-12 text-right`}
                >
                  {agentCritiques.length}×
                </span>
              </div>
            );
          })}
        </div>

        {/* Recent Critiques (last 3) */}
        {critiques.length > 0 && (
          <div className="pt-2 border-t border-accent/20 space-y-2">
            <div className="text-xs font-theme-data text-text-muted">Recent Issues</div>
            {critiques
              .slice(-3)
              .reverse()
              .map((critique, idx) => (
                <div key={idx} className="text-xs font-theme-data">
                  <div className="flex items-center gap-2 mb-1">
                    <span className={getSeverityColor(critique.severity)}>
                      [{getSeverityLabel(critique.severity)}]
                    </span>
                    <span className="text-text-muted">
                      {critique.agent.split('-')[0]} → {critique.target.split('-')[0]}
                    </span>
                  </div>
                  {critique.issues.length > 0 && (
                    <div className="text-text-muted/80 pl-2 border-l border-accent/20 truncate">
                      {critique.issues[0]}
                    </div>
                  )}
                </div>
              ))}
          </div>
        )}
      </div>
    </div>
  );
}
