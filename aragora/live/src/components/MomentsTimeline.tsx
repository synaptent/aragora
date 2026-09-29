'use client';

import { useState, useEffect, useCallback } from 'react';
import { PanelTemplate } from './shared/PanelTemplate';
import { API_BASE_URL } from '@/config';

interface Moment {
  id: string;
  type: string;
  agent: string;
  description: string;
  significance: number;
  debate_id?: string;
  other_agents?: string[];
  metadata?: Record<string, unknown>;
  created_at?: string;
}

interface MomentsSummary {
  total_moments: number;
  by_type: Record<string, number>;
  by_agent: Record<string, number>;
  most_significant?: Moment;
  recent: Moment[];
}

interface MomentsTimelineProps {
  apiBase?: string;
}

const DEFAULT_API_BASE = API_BASE_URL;

const MOMENT_ICONS: Record<string, string> = {
  upset_victory: '🏆',
  position_reversal: '🔄',
  calibration_vindication: '🎯',
  alliance_shift: '🤝',
  consensus_breakthrough: '💡',
  streak_achievement: '🔥',
  domain_mastery: '👑',
};

const MOMENT_COLORS: Record<string, string> = {
  upset_victory: 'text-yellow-400 bg-yellow-900/20 border-yellow-800/30',
  position_reversal: 'text-purple-400 bg-purple-900/20 border-purple-800/30',
  calibration_vindication: 'text-blue-400 bg-blue-900/20 border-blue-800/30',
  alliance_shift: 'text-green-400 bg-green-900/20 border-green-800/30',
  consensus_breakthrough: 'text-cyan-400 bg-cyan-900/20 border-cyan-800/30',
  streak_achievement: 'text-orange-400 bg-orange-900/20 border-orange-800/30',
  domain_mastery: 'text-pink-400 bg-pink-900/20 border-pink-800/30',
};

const getMomentIcon = (type: string): string => MOMENT_ICONS[type] || '📌';
const getMomentColor = (type: string): string =>
  MOMENT_COLORS[type] || 'text-text-muted bg-surface border-border';
const formatMomentType = (type: string): string =>
  type.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

export function MomentsTimeline({ apiBase = DEFAULT_API_BASE }: MomentsTimelineProps) {
  const [summary, setSummary] = useState<MomentsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedType, setSelectedType] = useState<string | null>(null);

  const fetchSummary = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const res = await fetch(`${apiBase}/api/moments/summary`);
      if (!res.ok) {
        if (res.status === 503) {
          setSummary(null);
          return;
        }
        throw new Error(`Failed to fetch moments: ${res.status}`);
      }

      const data = await res.json();
      setSummary(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch moments');
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    fetchSummary();
  }, [fetchSummary]);

  const filteredMoments =
    selectedType && summary
      ? summary.recent.filter((m) => m.type === selectedType)
      : summary?.recent || [];

  // Content to render inside the panel
  const renderContent = () => {
    if (!summary) return null;

    return (
      <>
        {/* Type Filter */}
        {Object.keys(summary.by_type).length > 0 && (
          <div className="flex flex-wrap gap-1 mb-4">
            <button
              onClick={() => setSelectedType(null)}
              className={`px-2 py-1 text-xs rounded transition-colors ${
                !selectedType ? 'bg-accent text-bg' : 'bg-surface text-text-muted hover:text-text'
              }`}
            >
              All
            </button>
            {Object.entries(summary.by_type).map(([type, count]) => (
              <button
                key={type}
                onClick={() => setSelectedType(type === selectedType ? null : type)}
                className={`px-2 py-1 text-xs rounded transition-colors flex items-center gap-1 ${
                  selectedType === type
                    ? 'bg-accent text-bg'
                    : 'bg-surface text-text-muted hover:text-text'
                }`}
              >
                <span>{getMomentIcon(type)}</span>
                <span>{count}</span>
              </button>
            ))}
          </div>
        )}

        {/* Most Significant */}
        {!selectedType && summary.most_significant && (
          <div className="mb-4">
            <div className="text-xs text-text-muted mb-2">HIGHLIGHT</div>
            <div
              data-testid="moments-highlight"
              className={`p-3 rounded border ${getMomentColor(summary.most_significant.type)}`}
            >
              <div className="flex items-center gap-2 mb-1">
                <span className="text-lg">{getMomentIcon(summary.most_significant.type)}</span>
                <span className="font-medium text-sm">
                  {formatMomentType(summary.most_significant.type)}
                </span>
                <span className="text-xs text-yellow-400 ml-auto">
                  {(summary.most_significant.significance * 100).toFixed(0)}%
                </span>
              </div>
              <p className="text-sm text-text-muted">{summary.most_significant.description}</p>
              <div className="text-xs text-text-muted/70 mt-1">
                {summary.most_significant.agent}
              </div>
            </div>
          </div>
        )}

        {/* Recent Moments */}
        <div className="space-y-2" data-testid="moments-recent-list">
          <div className="text-xs text-text-muted mb-2">
            {selectedType ? formatMomentType(selectedType) : 'RECENT'}
          </div>
          {filteredMoments.length > 0 ? (
            filteredMoments.map((moment) => (
              <div key={moment.id} className={`p-2 rounded border ${getMomentColor(moment.type)}`}>
                <div className="flex items-center gap-2">
                  <span>{getMomentIcon(moment.type)}</span>
                  <span className="text-sm font-medium flex-1 truncate">{moment.agent}</span>
                  <span className="text-xs opacity-70">
                    {(moment.significance * 100).toFixed(0)}%
                  </span>
                </div>
                <p className="text-xs text-text-muted mt-1 line-clamp-2">{moment.description}</p>
                {moment.created_at && (
                  <div className="text-xs text-text-muted/50 mt-1">
                    {new Date(moment.created_at).toLocaleString()}
                  </div>
                )}
              </div>
            ))
          ) : (
            <div className="text-center text-text-muted text-sm py-4">No moments of this type.</div>
          )}
        </div>

        {/* Agent Distribution */}
        {Object.keys(summary.by_agent).length > 0 && (
          <div
            className="mt-4 pt-4 border-t border-border"
            data-testid="moments-agent-distribution"
          >
            <div className="text-xs text-text-muted mb-2">BY AGENT</div>
            <div className="flex flex-wrap gap-2">
              {Object.entries(summary.by_agent)
                .sort(([, a], [, b]) => b - a)
                .slice(0, 5)
                .map(([agent, count]) => (
                  <span key={agent} className="text-xs bg-surface px-2 py-1 rounded">
                    <span className="text-text">{agent}</span>
                    <span className="text-text-muted ml-1">({count})</span>
                  </span>
                ))}
            </div>
          </div>
        )}
      </>
    );
  };

  return (
    <PanelTemplate
      title="MOMENTS"
      icon="⚡"
      loading={loading}
      error={error}
      onRefresh={fetchSummary}
      badge={summary?.total_moments}
      isEmpty={!summary || summary.total_moments === 0}
      emptyState={
        <div className="text-text-muted text-sm text-center py-4">
          No significant moments recorded yet.
        </div>
      }
    >
      {renderContent()}
    </PanelTemplate>
  );
}
