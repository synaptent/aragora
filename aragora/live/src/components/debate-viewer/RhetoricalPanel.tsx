'use client';

import { useState, useEffect } from 'react';
import { API_BASE_URL } from '@/config';
import { logger } from '@/utils/logger';

interface RhetoricalObservation {
  pattern: string;
  agent: string;
  round_num: number;
  confidence: number;
  excerpt: string;
  audience_commentary: string;
  timestamp: number;
}

interface RhetoricalData {
  debate_id: string;
  observations: RhetoricalObservation[];
  dynamics: {
    total_observations: number;
    dominant_pattern: string | null;
    agent_styles: Record<string, string[]>;
    debate_tenor: string;
  };
  pattern_counts: Record<string, number>;
  total_observations: number;
}

interface RhetoricalPanelProps {
  debateId: string;
}

const PATTERN_ICONS: Record<string, string> = {
  concession: '🤝',
  rebuttal: '⚔️',
  synthesis: '🔗',
  appeal_to_authority: '👨‍🎓',
  appeal_to_evidence: '📊',
  technical_depth: '🔬',
  rhetorical_question: '❓',
  analogy: '🎭',
  qualification: '⚖️',
};

const PATTERN_COLORS: Record<string, string> = {
  concession: 'text-green-400 bg-green-400/10 border-green-400/30',
  rebuttal: 'text-red-400 bg-red-400/10 border-red-400/30',
  synthesis: 'text-purple-400 bg-purple-400/10 border-purple-400/30',
  appeal_to_authority: 'text-yellow-400 bg-yellow-400/10 border-yellow-400/30',
  appeal_to_evidence: 'text-blue-400 bg-blue-400/10 border-blue-400/30',
  technical_depth: 'text-cyan-400 bg-cyan-400/10 border-cyan-400/30',
  rhetorical_question: 'text-orange-400 bg-orange-400/10 border-orange-400/30',
  analogy: 'text-pink-400 bg-pink-400/10 border-pink-400/30',
  qualification: 'text-gray-400 bg-gray-400/10 border-gray-400/30',
};

export function RhetoricalPanel({ debateId }: RhetoricalPanelProps) {
  const [data, setData] = useState<RhetoricalData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [selectedPattern, setSelectedPattern] = useState<string | null>(null);

  useEffect(() => {
    async function fetchRhetoricalData() {
      try {
        setLoading(true);
        const response = await fetch(`${API_BASE_URL}/api/debates/${debateId}/rhetorical`);
        if (!response.ok) {
          if (response.status === 404) {
            setError('Rhetorical analysis not available for this debate');
          } else {
            throw new Error(`HTTP ${response.status}`);
          }
          return;
        }
        const result = await response.json();
        setData(result);
      } catch (err) {
        logger.error('Failed to fetch rhetorical data:', err);
        setError('Failed to load rhetorical analysis');
      } finally {
        setLoading(false);
      }
    }

    fetchRhetoricalData();
  }, [debateId]);

  if (loading) {
    return (
      <div className="bg-surface border border-[var(--accent)]/30 p-4">
        <div className="text-xs font-theme-data text-text-muted animate-pulse">
          Loading rhetorical analysis...
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="bg-surface border border-yellow-500/30 p-4">
        <div className="text-xs font-theme-data text-yellow-500">
          {error || 'No rhetorical data available'}
        </div>
      </div>
    );
  }

  const filteredObservations = selectedPattern
    ? data.observations.filter((o) => o.pattern === selectedPattern)
    : data.observations;

  return (
    <div className="bg-surface border border-[var(--accent)]/30">
      {/* Header */}
      <div
        className="px-4 py-3 border-b border-[var(--accent)]/20 bg-bg/50 cursor-pointer flex items-center justify-between"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2">
          <span className="text-xs font-theme-data text-[var(--accent)] uppercase tracking-wider">
            {'>'} RHETORICAL ANALYSIS
          </span>
          <span className="text-xs font-theme-data text-text-muted">
            ({data.total_observations} patterns detected)
          </span>
        </div>
        <span className="text-xs font-theme-data text-[var(--accent)]">
          {expanded ? '[-]' : '[+]'}
        </span>
      </div>

      {expanded && (
        <div className="p-4 space-y-4">
          {/* Pattern Summary */}
          <div className="flex flex-wrap gap-2">
            {Object.entries(data.pattern_counts)
              .filter(([, count]) => count > 0)
              .sort(([, a], [, b]) => b - a)
              .map(([pattern, count]) => (
                <button
                  key={pattern}
                  onClick={() => setSelectedPattern(selectedPattern === pattern ? null : pattern)}
                  className={`px-2 py-1 text-xs font-theme-data border rounded transition-all ${
                    selectedPattern === pattern
                      ? PATTERN_COLORS[pattern] + ' ring-1 ring-current'
                      : 'border-border text-text-muted hover:border-text'
                  }`}
                >
                  {PATTERN_ICONS[pattern] || '?'} {pattern.replace(/_/g, ' ')} ({count})
                </button>
              ))}
          </div>

          {/* Debate Dynamics */}
          {data.dynamics && (
            <div className="bg-bg/50 border border-border rounded p-3">
              <div className="text-xs font-theme-data text-text-muted uppercase mb-2">
                Debate Dynamics
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs font-theme-data">
                <div>
                  <span className="text-text-muted">Tenor: </span>
                  <span className="text-text">{data.dynamics.debate_tenor || 'Unknown'}</span>
                </div>
                {data.dynamics.dominant_pattern && (
                  <div>
                    <span className="text-text-muted">Dominant: </span>
                    <span className="text-text">
                      {PATTERN_ICONS[data.dynamics.dominant_pattern]}{' '}
                      {data.dynamics.dominant_pattern.replace(/_/g, ' ')}
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Observations List */}
          <div className="space-y-2 max-h-[400px] overflow-y-auto">
            {filteredObservations.slice(0, 20).map((obs, idx) => (
              <div
                key={idx}
                className={`p-3 border rounded ${PATTERN_COLORS[obs.pattern] || 'border-border'}`}
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-sm">{PATTERN_ICONS[obs.pattern] || '?'}</span>
                    <span className="text-xs font-theme-data font-bold uppercase">
                      {obs.pattern.replace(/_/g, ' ')}
                    </span>
                  </div>
                  <div className="text-xs font-theme-data text-text-muted">
                    {obs.agent} | Round {obs.round_num} | {Math.round(obs.confidence * 100)}%
                    confidence
                  </div>
                </div>
                <div className="text-xs font-theme-data text-text mb-2 italic">
                  &ldquo;{obs.audience_commentary}&rdquo;
                </div>
                <div className="text-xs font-theme-data text-text-muted bg-bg/50 p-2 rounded">
                  &ldquo;{obs.excerpt}&rdquo;
                </div>
              </div>
            ))}
            {filteredObservations.length > 20 && (
              <div className="text-xs font-theme-data text-text-muted text-center py-2">
                + {filteredObservations.length - 20} more observations
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
