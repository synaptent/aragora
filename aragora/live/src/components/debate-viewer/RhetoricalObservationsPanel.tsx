'use client';

import { useMemo, useState } from 'react';
import { getAgentColors } from '@/utils/agentColors';
import type { StreamEvent, RhetoricalObservationData } from '@/types/events';

interface RhetoricalObservationsPanelProps {
  events: StreamEvent[];
}

interface RhetoricalObservation {
  agent: string;
  patterns: string[];
  round: number;
  analysis?: string;
  timestamp: number;
}

const PATTERN_ICONS: Record<string, string> = {
  appeal_to_authority: '[AUTH]',
  appeal_to_emotion: '[EMOT]',
  logical_fallacy: '[FALL]',
  strawman: '[STRAW]',
  whataboutism: '[WHAT]',
  ad_hominem: '[AD_H]',
  evidence_based: '[EVID]',
  clarification: '[CLAR]',
  concession: '[CONC]',
  reframing: '[REFR]',
  default: '[RHET]',
};

function getPatternIcon(pattern: string): string {
  const key = pattern.toLowerCase().replace(/\s+/g, '_');
  return PATTERN_ICONS[key] || PATTERN_ICONS.default;
}

function getPatternColor(pattern: string): string {
  const key = pattern.toLowerCase();
  if (key.includes('fallacy') || key.includes('strawman') || key.includes('ad_hominem')) {
    return 'text-[var(--crimson)]';
  }
  if (key.includes('evidence') || key.includes('clarification')) {
    return 'text-[var(--accent)]';
  }
  if (key.includes('emotion') || key.includes('appeal')) {
    return 'text-yellow-400';
  }
  return 'text-[var(--acid-cyan)]';
}

export function RhetoricalObservationsPanel({ events }: RhetoricalObservationsPanelProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const observations = useMemo(() => {
    const obsList: RhetoricalObservation[] = [];

    for (const event of events) {
      if (event.type === 'rhetorical_observation') {
        const data = event.data as RhetoricalObservationData;
        obsList.push({
          agent: data.agent,
          patterns: data.patterns || [],
          round: data.round || event.round || 0,
          analysis: data.analysis,
          timestamp: event.timestamp,
        });
      }
    }

    return obsList.sort((a, b) => b.timestamp - a.timestamp);
  }, [events]);

  // Group by agent for summary
  const patternsByAgent = useMemo(() => {
    const byAgent = new Map<string, Set<string>>();
    for (const obs of observations) {
      if (!byAgent.has(obs.agent)) {
        byAgent.set(obs.agent, new Set());
      }
      for (const pattern of obs.patterns) {
        byAgent.get(obs.agent)!.add(pattern);
      }
    }
    return byAgent;
  }, [observations]);

  if (observations.length === 0) {
    return null;
  }

  return (
    <div className="bg-surface border border-purple/30">
      <div
        className="px-4 py-3 border-b border-purple/20 bg-bg/50 flex items-center justify-between cursor-pointer"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <span className="text-xs font-theme-data text-purple uppercase tracking-wider">
          {'>'} RHETORICAL ANALYSIS
        </span>
        <div className="flex items-center gap-2">
          <span className="text-xs font-theme-data text-text-muted">
            {observations.length} observation{observations.length !== 1 ? 's' : ''}
          </span>
          <span className="text-xs font-theme-data text-purple">{isExpanded ? '[-]' : '[+]'}</span>
        </div>
      </div>

      {/* Collapsed Summary */}
      {!isExpanded && (
        <div className="p-4">
          <div className="flex flex-wrap gap-2">
            {Array.from(patternsByAgent.entries()).map(([agent, patterns]) => {
              const colors = getAgentColors(agent);
              return (
                <div key={agent} className="flex items-center gap-1">
                  <span className={`text-xs font-theme-data ${colors.text}`}>
                    {agent.split('-')[0]}:
                  </span>
                  {Array.from(patterns)
                    .slice(0, 3)
                    .map((pattern, idx) => (
                      <span
                        key={idx}
                        className={`text-xs font-theme-data ${getPatternColor(pattern)}`}
                        title={pattern}
                      >
                        {getPatternIcon(pattern)}
                      </span>
                    ))}
                  {patterns.size > 3 && (
                    <span className="text-xs font-theme-data text-text-muted">
                      +{patterns.size - 3}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Expanded View */}
      {isExpanded && (
        <div className="p-4 space-y-3 max-h-80 overflow-y-auto">
          {observations.map((obs, idx) => {
            const colors = getAgentColors(obs.agent);
            return (
              <div key={idx} className={`p-3 border ${colors.border} ${colors.bg}`}>
                <div className="flex items-center justify-between mb-2">
                  <span className={`text-xs font-theme-data ${colors.text}`}>{obs.agent}</span>
                  <span className="text-xs font-theme-data text-text-muted">Round {obs.round}</span>
                </div>

                {/* Patterns */}
                <div className="flex flex-wrap gap-1 mb-2">
                  {obs.patterns.map((pattern, pidx) => (
                    <span
                      key={pidx}
                      className={`px-1.5 py-0.5 text-xs font-theme-data ${getPatternColor(pattern)} bg-bg/50 border border-current/30`}
                    >
                      {pattern}
                    </span>
                  ))}
                </div>

                {/* Analysis */}
                {obs.analysis && (
                  <div className="text-xs font-theme-data text-text-muted border-t border-current/20 pt-2 mt-2">
                    {obs.analysis}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
