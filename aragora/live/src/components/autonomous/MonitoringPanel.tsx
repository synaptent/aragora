'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '@/config';

interface Trend {
  direction: string;
  current_value: number;
  change_percent: number;
  data_points: number;
  confidence: number;
}

interface Anomaly {
  id: string;
  metric_name: string;
  value: number;
  expected_value: number;
  deviation: number;
  timestamp: string;
  severity: string;
  description: string;
}

interface MonitoringPanelProps {
  apiBase: string;
}

const DIRECTION_STYLES: Record<string, { icon: string; color: string }> = {
  increasing: { icon: '↑', color: 'text-[var(--accent)]' },
  decreasing: { icon: '↓', color: 'text-red-400' },
  stable: { icon: '→', color: 'text-white/50' },
  volatile: { icon: '↕', color: 'text-yellow-500' },
};

export function MonitoringPanel({ apiBase }: MonitoringPanelProps) {
  const [trends, setTrends] = useState<Record<string, Trend>>({});
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'trends' | 'anomalies'>('trends');

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const [trendsRes, anomaliesRes] = await Promise.all([
        apiFetch<{ trends: Record<string, Trend> }>(`${apiBase}/autonomous/monitoring/trends`),
        apiFetch<{ anomalies: Anomaly[] }>(`${apiBase}/autonomous/monitoring/anomalies?hours=24`),
      ]);
      if (trendsRes.error) {
        throw new Error(trendsRes.error);
      }
      if (anomaliesRes.error) {
        throw new Error(anomaliesRes.error);
      }
      setTrends(trendsRes.data?.trends ?? {});
      setAnomalies(anomaliesRes.data?.anomalies ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch monitoring data');
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000); // Auto-refresh every 30s
    return () => clearInterval(interval);
  }, [fetchData]);

  if (loading && Object.keys(trends).length === 0) {
    return <div className="text-white/50 animate-pulse">Loading monitoring data...</div>;
  }

  if (error) {
    return (
      <div className="p-4 bg-red-500/10 border border-red-500/30 rounded text-red-400">
        {error}
        <button onClick={fetchData} className="ml-4 text-sm underline">
          Retry
        </button>
      </div>
    );
  }

  const renderTrends = () => {
    const trendEntries = Object.entries(trends);

    if (trendEntries.length === 0) {
      return (
        <div className="text-center py-12 text-white/50">
          <div className="text-4xl mb-2">📊</div>
          <div>No trend data available</div>
          <div className="text-xs mt-1">Start recording metrics to see trends</div>
        </div>
      );
    }

    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {trendEntries.map(([name, trend]) => {
          const dirStyle = DIRECTION_STYLES[trend.direction] ?? DIRECTION_STYLES.stable;

          return (
            <div key={name} className="border border-white/10 bg-white/5 rounded-lg p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-white/70">{name}</span>
                <span className={`text-lg ${dirStyle.color}`}>{dirStyle.icon}</span>
              </div>
              <div className="text-2xl font-bold text-white">{trend.current_value.toFixed(2)}</div>
              <div className="flex items-center gap-2 mt-1 text-xs">
                <span
                  className={
                    trend.change_percent > 0
                      ? 'text-[var(--accent)]'
                      : trend.change_percent < 0
                        ? 'text-red-400'
                        : 'text-white/50'
                  }
                >
                  {trend.change_percent > 0 ? '+' : ''}
                  {trend.change_percent.toFixed(1)}%
                </span>
                <span className="text-white/40">•</span>
                <span className="text-white/40">{trend.data_points} points</span>
                <span className="text-white/40">•</span>
                <span className="text-white/40">{(trend.confidence * 100).toFixed(0)}% conf</span>
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  const renderAnomalies = () => {
    if (anomalies.length === 0) {
      return (
        <div className="text-center py-12 text-white/50">
          <div className="text-4xl mb-2">✓</div>
          <div>No anomalies detected in the last 24 hours</div>
        </div>
      );
    }

    return (
      <div className="space-y-2">
        {anomalies.map((anomaly) => {
          const severityColor =
            anomaly.severity === 'critical'
              ? 'border-red-500/50 bg-red-500/10'
              : anomaly.severity === 'high'
                ? 'border-orange-500/50 bg-orange-500/10'
                : 'border-yellow-500/50 bg-yellow-500/10';

          return (
            <div key={anomaly.id} className={`border rounded-lg p-4 ${severityColor}`}>
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-white">{anomaly.metric_name}</span>
                    <span
                      className={`px-1.5 py-0.5 rounded text-xs uppercase ${
                        anomaly.severity === 'critical'
                          ? 'bg-red-500/20 text-red-400'
                          : anomaly.severity === 'high'
                            ? 'bg-orange-500/20 text-orange-400'
                            : 'bg-yellow-500/20 text-yellow-500'
                      }`}
                    >
                      {anomaly.severity}
                    </span>
                  </div>
                  <div className="text-sm text-white/50 mt-1">{anomaly.description}</div>
                  <div className="flex items-center gap-4 mt-2 text-xs text-white/40">
                    <span>Value: {anomaly.value.toFixed(2)}</span>
                    <span>Expected: {anomaly.expected_value.toFixed(2)}</span>
                    <span>{anomaly.deviation.toFixed(1)}σ deviation</span>
                    <span>{new Date(anomaly.timestamp).toLocaleString()}</span>
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div role="tablist" aria-label="Monitoring views" className="flex gap-2">
          <button
            role="tab"
            aria-selected={activeTab === 'trends'}
            aria-controls="trends-panel"
            onClick={() => setActiveTab('trends')}
            className={`px-3 py-1.5 text-sm rounded transition-colors ${
              activeTab === 'trends' ? 'bg-white/10 text-white' : 'text-white/50 hover:text-white'
            }`}
          >
            Trends ({Object.keys(trends).length})
          </button>
          <button
            role="tab"
            aria-selected={activeTab === 'anomalies'}
            aria-controls="anomalies-panel"
            onClick={() => setActiveTab('anomalies')}
            className={`px-3 py-1.5 text-sm rounded transition-colors ${
              activeTab === 'anomalies'
                ? 'bg-white/10 text-white'
                : 'text-white/50 hover:text-white'
            }`}
          >
            Anomalies ({anomalies.length})
          </button>
        </div>
        <button
          onClick={fetchData}
          disabled={loading}
          aria-label="Refresh monitoring data"
          className="text-xs text-white/50 hover:text-white"
        >
          {loading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {/* Content */}
      {activeTab === 'trends' ? (
        <div role="tabpanel" id="trends-panel" aria-labelledby="trends-tab">
          {renderTrends()}
        </div>
      ) : (
        <div role="tabpanel" id="anomalies-panel" aria-labelledby="anomalies-tab">
          {renderAnomalies()}
        </div>
      )}
    </div>
  );
}

export default MonitoringPanel;
