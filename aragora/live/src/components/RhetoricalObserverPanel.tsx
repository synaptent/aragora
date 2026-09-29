'use client';

import { useMemo } from 'react';
import type { StreamEvent, RhetoricalObservationData } from '@/types/events';

interface RhetoricalObserverPanelProps {
  events: StreamEvent[];
}

interface Observation {
  agent: string;
  patterns: string[];
  round: number;
  analysis?: string;
  timestamp: number;
}

// Pattern type to color/icon mapping
const PATTERN_STYLES: Record<string, { color: string; icon: string; description: string }> = {
  concession: { color: 'text-yellow-400', icon: '🤝', description: 'Acknowledged opposing point' },
  rebuttal: { color: 'text-red-400', icon: '⚔️', description: 'Directly countered argument' },
  synthesis: { color: 'text-green-400', icon: '🔗', description: 'Combined multiple viewpoints' },
  appeal_to_authority: {
    color: 'text-blue-400',
    icon: '📚',
    description: 'Referenced expert/source',
  },
  appeal_to_emotion: { color: 'text-pink-400', icon: '💭', description: 'Used emotional framing' },
  technical_depth: { color: 'text-cyan-400', icon: '🔬', description: 'Deep technical analysis' },
  qualification: { color: 'text-orange-400', icon: '⚠️', description: 'Added nuance/caveats' },
  analogy: { color: 'text-purple-400', icon: '🎭', description: 'Used comparison/metaphor' },
  evidence_citation: { color: 'text-teal-400', icon: '📖', description: 'Cited specific evidence' },
  counterexample: { color: 'text-rose-400', icon: '❌', description: 'Provided counterexample' },
};

function getPatternStyle(pattern: string) {
  const normalized = pattern.toLowerCase().replace(/\s+/g, '_');
  return (
    PATTERN_STYLES[normalized] || { color: 'text-text-muted', icon: '📌', description: pattern }
  );
}

export function RhetoricalObserverPanel({ events }: RhetoricalObserverPanelProps) {
  const observations = useMemo(() => {
    const obs: Observation[] = [];

    for (const event of events) {
      if (event.type === 'rhetorical_observation') {
        const data = event.data as RhetoricalObservationData;
        obs.push({
          agent: data.agent,
          patterns: data.patterns || [],
          round: data.round,
          analysis: data.analysis,
          timestamp: event.timestamp,
        });
      }
    }

    return obs.sort((a, b) => b.timestamp - a.timestamp);
  }, [events]);

  // Aggregate patterns by agent
  const agentPatterns = useMemo(() => {
    const counts: Record<string, Record<string, number>> = {};

    for (const obs of observations) {
      if (!counts[obs.agent]) {
        counts[obs.agent] = {};
      }
      for (const pattern of obs.patterns) {
        const normalized = pattern.toLowerCase().replace(/\s+/g, '_');
        counts[obs.agent][normalized] = (counts[obs.agent][normalized] || 0) + 1;
      }
    }

    return counts;
  }, [observations]);

  if (observations.length === 0) {
    return null; // Don't render if no observations
  }

  return (
    <div className="panel" style={{ padding: 0 }}>
      {/* Header */}
      <div className="panel-collapsible-header">
        <div className="flex items-center gap-2">
          <span className="text-[var(--acid-cyan)] font-theme-data text-sm">
            [RHETORICAL OBSERVER]
          </span>
          <span className="text-text-muted text-xs">Debate pattern analysis</span>
        </div>
        <span className="text-xs text-[var(--accent)]">{observations.length} observations</span>
      </div>

      <div className="px-4 pb-4 space-y-3">
        {/* Agent Pattern Summary */}
        {Object.keys(agentPatterns).length > 0 && (
          <div className="space-y-2">
            <div className="text-xs text-text-muted">Pattern frequency by agent:</div>
            {Object.entries(agentPatterns).map(([agent, patterns]) => (
              <div key={agent} className="border border-[var(--accent)]/20 p-2">
                <div className="text-xs font-theme-data text-[var(--acid-cyan)] mb-1">{agent}</div>
                <div className="flex flex-wrap gap-1">
                  {Object.entries(patterns)
                    .sort(([, a], [, b]) => b - a)
                    .slice(0, 5)
                    .map(([pattern, count]) => {
                      const style = getPatternStyle(pattern);
                      return (
                        <span
                          key={pattern}
                          className={`text-xs px-1.5 py-0.5 border border-current/30 ${style.color}`}
                          title={style.description}
                        >
                          {style.icon} {pattern.replace(/_/g, ' ')} ({count})
                        </span>
                      );
                    })}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Recent Observations */}
        <div className="space-y-2 max-h-48 overflow-y-auto">
          <div className="text-xs text-text-muted">Recent observations:</div>
          {observations.slice(0, 10).map((obs, idx) => (
            <div
              key={`${obs.agent}-${obs.round}-${idx}`}
              className="p-2 bg-bg/50 border border-[var(--accent)]/10 text-xs"
            >
              <div className="flex items-center justify-between mb-1">
                <span className="font-theme-data text-[var(--acid-cyan)]">{obs.agent}</span>
                <span className="text-text-muted">Round {obs.round}</span>
              </div>
              <div className="flex flex-wrap gap-1 mb-1">
                {obs.patterns.map((pattern, pidx) => {
                  const style = getPatternStyle(pattern);
                  return (
                    <span
                      key={pidx}
                      className={`px-1 py-0.5 border border-current/20 ${style.color}`}
                      title={style.description}
                    >
                      {style.icon} {pattern}
                    </span>
                  );
                })}
              </div>
              {obs.analysis && (
                <div className="text-text-muted/70 italic mt-1">&quot;{obs.analysis}&quot;</div>
              )}
            </div>
          ))}
        </div>

        {/* Legend */}
        <div className="text-xs text-text-muted/50 text-center pt-2 border-t border-[var(--accent)]/10">
          Rhetorical patterns detected during debate
        </div>
      </div>
    </div>
  );
}
