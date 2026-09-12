'use client';

import { useState, useEffect, useCallback } from 'react';
import { PanelTemplate } from './shared/PanelTemplate';
import { API_BASE_URL } from '@/config';

interface ConfidencePoint {
  debate_id: string;
  confidence: number;
  consensus_reached: boolean;
  timestamp: string;
}

interface ConsensusStats {
  total_debates: number;
  confidence_history: ConfidencePoint[];
  trend: 'improving' | 'stable' | 'declining' | 'insufficient_data';
  average_confidence: number;
  consensus_rate: number;
  consensus_reached_count: number;
}

interface Alert {
  level: 'critical' | 'warning' | 'info';
  message: string;
}

interface ConsensusQuality {
  stats: ConsensusStats;
  quality_score: number;
  alert: Alert | null;
}

interface ConsensusQualityDashboardProps {
  apiBase?: string;
}

const DEFAULT_API_BASE = API_BASE_URL;

const TREND_ICONS: Record<string, string> = {
  improving: '📈',
  stable: '➡️',
  declining: '📉',
  insufficient_data: '❓',
};

const ALERT_COLORS: Record<string, string> = {
  critical: 'bg-red-900/30 border-red-500/50 text-red-400',
  warning: 'bg-yellow-900/30 border-yellow-500/50 text-yellow-400',
  info: 'bg-blue-900/30 border-blue-500/50 text-blue-400',
};

const getScoreColor = (score: number): string => {
  if (score >= 80) return 'text-green-400';
  if (score >= 60) return 'text-yellow-400';
  if (score >= 40) return 'text-orange-400';
  return 'text-red-400';
};

const getTrendColor = (trend: string): string => {
  if (trend === 'improving') return 'text-green-400';
  if (trend === 'declining') return 'text-red-400';
  return 'text-text-muted';
};

export function ConsensusQualityDashboard({
  apiBase = DEFAULT_API_BASE,
}: ConsensusQualityDashboardProps) {
  const [data, setData] = useState<ConsensusQuality | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const res = await fetch(`${apiBase}/api/analytics/consensus-quality`);
      if (!res.ok) {
        throw new Error(`Failed to fetch consensus quality: ${res.status}`);
      }

      const result = await res.json();
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch data');
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const renderContent = () => {
    if (!data) return null;

    const { stats, quality_score, alert } = data;

    return (
      <>
        {/* Alert Banner */}
        {alert && (
          <div className={`mb-4 p-3 rounded border ${ALERT_COLORS[alert.level]}`}>
            <div className="flex items-center gap-2 text-sm">
              <span>
                {alert.level === 'critical' ? '🚨' : alert.level === 'warning' ? '⚠️' : 'ℹ️'}
              </span>
              <span>{alert.message}</span>
            </div>
          </div>
        )}

        {/* Quality Score */}
        <div className="text-center mb-4">
          <div className={`text-4xl font-bold font-theme-data ${getScoreColor(quality_score)}`}>
            {quality_score}
          </div>
          <div className="text-xs text-text-muted">Quality Score</div>
        </div>

        {/* Key Metrics */}
        <div className="grid grid-cols-3 gap-3 mb-4">
          <div className="bg-surface rounded p-3 text-center">
            <div className="text-lg font-theme-data text-text">
              {(stats.consensus_rate * 100).toFixed(0)}%
            </div>
            <div className="text-xs text-text-muted">Consensus Rate</div>
          </div>
          <div className="bg-surface rounded p-3 text-center">
            <div className="text-lg font-theme-data text-text">
              {(stats.average_confidence * 100).toFixed(0)}%
            </div>
            <div className="text-xs text-text-muted">Avg Confidence</div>
          </div>
          <div className="bg-surface rounded p-3 text-center">
            <div className={`text-lg ${getTrendColor(stats.trend)}`}>
              {TREND_ICONS[stats.trend]}{' '}
              {stats.trend.charAt(0).toUpperCase() + stats.trend.slice(1).replace(/_/g, ' ')}
            </div>
            <div className="text-xs text-text-muted">Trend</div>
          </div>
        </div>

        {/* Confidence History Chart */}
        {stats.confidence_history.length > 0 && (
          <div className="mb-4">
            <div className="text-xs text-text-muted mb-2">CONFIDENCE HISTORY</div>
            <div className="h-16 flex items-end gap-0.5">
              {stats.confidence_history.slice(-20).map((point, idx) => (
                <div
                  key={idx}
                  className="flex-1 min-w-1"
                  title={`${point.debate_id}: ${(point.confidence * 100).toFixed(0)}%`}
                >
                  <div
                    className={`w-full rounded-t ${
                      point.consensus_reached ? 'bg-green-500' : 'bg-orange-500'
                    }`}
                    style={{ height: `${Math.max(4, point.confidence * 64)}px` }}
                  />
                </div>
              ))}
            </div>
            <div className="flex justify-between text-xs text-text-muted mt-1">
              <span>Older</span>
              <span>Recent</span>
            </div>
          </div>
        )}

        {/* Summary Stats */}
        <div className="flex justify-between text-xs text-text-muted pt-3 border-t border-border">
          <span>{stats.total_debates} total debates</span>
          <span>{stats.consensus_reached_count} reached consensus</span>
        </div>
      </>
    );
  };

  return (
    <PanelTemplate
      title="CONSENSUS QUALITY"
      icon="🎯"
      loading={loading}
      error={error}
      onRefresh={fetchData}
      isEmpty={!data || data.stats.total_debates === 0}
      emptyState={
        <div className="text-text-muted text-sm text-center py-4">
          No debate data available yet.
        </div>
      }
    >
      {renderContent()}
    </PanelTemplate>
  );
}
