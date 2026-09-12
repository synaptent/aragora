'use client';

import { useEffect, useState } from 'react';

interface QualityData {
  period: string;
  consensus_metrics: {
    overall_consensus_rate_percent: number;
    consensus_rate_trend: Array<{ date: string; rate: number }>;
    strong_consensus_percent: number;
    weak_consensus_percent: number;
    no_consensus_percent: number;
  };
  confidence_metrics: {
    avg_confidence_score: number;
    confidence_distribution: { high: number; medium: number; low: number };
    confidence_trend: string;
  };
  stability_metrics: {
    decision_reversal_rate_percent: number;
    avg_revisions_per_debate: number;
    final_position_changes: number;
  };
  quality_by_topic: Array<{
    topic: string;
    debates: number;
    consensus_rate: number;
    avg_confidence: number;
  }>;
}

interface QualityMetricsProps {
  backendUrl: string;
}

export function QualityMetrics({ backendUrl }: QualityMetricsProps) {
  const [data, setData] = useState<QualityData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchData() {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch(`${backendUrl}/api/v1/intelligence/quality-analysis`);
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        const result = await response.json();
        setData(result);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch data');
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, [backendUrl]);

  if (loading) {
    return (
      <div className="card p-6">
        <div className="animate-pulse">
          <div className="h-6 bg-surface rounded w-1/3 mb-4"></div>
          <div className="grid grid-cols-3 gap-4">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-32 bg-surface rounded"></div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card p-6 border-red-500/50">
        <p className="text-red-500 font-theme-data text-sm">Error: {error}</p>
      </div>
    );
  }

  if (!data) return null;

  const totalConfidence =
    data.confidence_metrics.confidence_distribution.high +
    data.confidence_metrics.confidence_distribution.medium +
    data.confidence_metrics.confidence_distribution.low;

  return (
    <div className="card p-6">
      <h2 className="text-lg font-theme-data text-[var(--accent)] mb-4">Quality Metrics</h2>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        {/* Consensus Distribution */}
        <div className="bg-surface/50 rounded-lg p-4 border border-[var(--accent)]/20">
          <h3 className="text-sm font-theme-data text-[var(--accent)] mb-3">
            Consensus Distribution
          </h3>
          <div className="space-y-2">
            <div>
              <div className="flex justify-between text-xs font-theme-data mb-1">
                <span className="text-text-muted">Strong (&gt;80%)</span>
                <span className="text-green-400">
                  {data.consensus_metrics.strong_consensus_percent}%
                </span>
              </div>
              <div className="h-2 bg-bg rounded-full overflow-hidden">
                <div
                  className="h-full bg-green-400"
                  style={{ width: `${data.consensus_metrics.strong_consensus_percent}%` }}
                ></div>
              </div>
            </div>
            <div>
              <div className="flex justify-between text-xs font-theme-data mb-1">
                <span className="text-text-muted">Weak (60-80%)</span>
                <span className="text-yellow-400">
                  {data.consensus_metrics.weak_consensus_percent}%
                </span>
              </div>
              <div className="h-2 bg-bg rounded-full overflow-hidden">
                <div
                  className="h-full bg-yellow-400"
                  style={{ width: `${data.consensus_metrics.weak_consensus_percent}%` }}
                ></div>
              </div>
            </div>
            <div>
              <div className="flex justify-between text-xs font-theme-data mb-1">
                <span className="text-text-muted">None (&lt;60%)</span>
                <span className="text-red-400">{data.consensus_metrics.no_consensus_percent}%</span>
              </div>
              <div className="h-2 bg-bg rounded-full overflow-hidden">
                <div
                  className="h-full bg-red-400"
                  style={{ width: `${data.consensus_metrics.no_consensus_percent}%` }}
                ></div>
              </div>
            </div>
          </div>
        </div>

        {/* Confidence Distribution */}
        <div className="bg-surface/50 rounded-lg p-4 border border-[var(--accent)]/20">
          <h3 className="text-sm font-theme-data text-[var(--accent)] mb-3">
            Confidence Distribution
          </h3>
          <div className="text-center mb-3">
            <p className="text-2xl font-theme-data text-[var(--accent)]">
              {(data.confidence_metrics.avg_confidence_score * 100).toFixed(0)}%
            </p>
            <p className="text-xs text-text-muted">Average Confidence</p>
          </div>
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs font-theme-data">
              <div className="w-3 h-3 rounded bg-green-400"></div>
              <span>High: {data.confidence_metrics.confidence_distribution.high}</span>
              <span className="text-text-muted">
                (
                {(
                  (data.confidence_metrics.confidence_distribution.high / totalConfidence) *
                  100
                ).toFixed(0)}
                %)
              </span>
            </div>
            <div className="flex items-center gap-2 text-xs font-theme-data">
              <div className="w-3 h-3 rounded bg-yellow-400"></div>
              <span>Medium: {data.confidence_metrics.confidence_distribution.medium}</span>
              <span className="text-text-muted">
                (
                {(
                  (data.confidence_metrics.confidence_distribution.medium / totalConfidence) *
                  100
                ).toFixed(0)}
                %)
              </span>
            </div>
            <div className="flex items-center gap-2 text-xs font-theme-data">
              <div className="w-3 h-3 rounded bg-red-400"></div>
              <span>Low: {data.confidence_metrics.confidence_distribution.low}</span>
              <span className="text-text-muted">
                (
                {(
                  (data.confidence_metrics.confidence_distribution.low / totalConfidence) *
                  100
                ).toFixed(0)}
                %)
              </span>
            </div>
          </div>
        </div>

        {/* Stability Metrics */}
        <div className="bg-surface/50 rounded-lg p-4 border border-[var(--accent)]/20">
          <h3 className="text-sm font-theme-data text-[var(--accent)] mb-3">Decision Stability</h3>
          <div className="space-y-4">
            <div>
              <p className="text-text-muted text-xs font-theme-data">Reversal Rate</p>
              <p className="text-xl font-theme-data">
                <span
                  className={
                    data.stability_metrics.decision_reversal_rate_percent < 5
                      ? 'text-green-400'
                      : 'text-yellow-400'
                  }
                >
                  {data.stability_metrics.decision_reversal_rate_percent}%
                </span>
              </p>
            </div>
            <div>
              <p className="text-text-muted text-xs font-theme-data">Avg Revisions/Debate</p>
              <p className="text-xl font-theme-data">
                {data.stability_metrics.avg_revisions_per_debate}
              </p>
            </div>
            <div>
              <p className="text-text-muted text-xs font-theme-data">Position Changes</p>
              <p className="text-xl font-theme-data">
                {data.stability_metrics.final_position_changes}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Quality by Topic */}
      <div className="bg-surface/30 rounded-lg p-4 border border-[var(--accent)]/10">
        <h3 className="text-sm font-theme-data text-[var(--accent)] mb-3">Quality by Topic</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-xs font-theme-data">
            <thead>
              <tr className="text-text-muted border-b border-[var(--accent)]/20">
                <th className="text-left pb-2">Topic</th>
                <th className="text-right pb-2">Debates</th>
                <th className="text-right pb-2">Consensus</th>
                <th className="text-right pb-2">Confidence</th>
              </tr>
            </thead>
            <tbody>
              {data.quality_by_topic.map((topic) => (
                <tr key={topic.topic} className="border-b border-[var(--accent)]/10">
                  <td className="py-2">{topic.topic}</td>
                  <td className="text-right py-2">{topic.debates}</td>
                  <td className="text-right py-2">
                    <span
                      className={
                        topic.consensus_rate >= 90
                          ? 'text-green-400'
                          : topic.consensus_rate >= 80
                            ? 'text-yellow-400'
                            : 'text-red-400'
                      }
                    >
                      {topic.consensus_rate}%
                    </span>
                  </td>
                  <td className="text-right py-2">
                    <span
                      className={
                        topic.avg_confidence >= 0.85
                          ? 'text-green-400'
                          : topic.avg_confidence >= 0.75
                            ? 'text-yellow-400'
                            : 'text-red-400'
                      }
                    >
                      {(topic.avg_confidence * 100).toFixed(0)}%
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Trend Chart (simplified) */}
      <div className="mt-4">
        <h3 className="text-sm font-theme-data text-[var(--accent)] mb-2">Consensus Rate Trend</h3>
        <div className="flex items-end gap-1 h-16">
          {data.consensus_metrics.consensus_rate_trend.map((point, _index) => (
            <div
              key={point.date}
              className="flex-1 bg-[var(--accent)]/30 hover:bg-[var(--accent)]/50 transition-colors relative group"
              style={{ height: `${point.rate}%` }}
            >
              <div className="absolute -top-6 left-1/2 transform -translate-x-1/2 text-xs font-theme-data opacity-0 group-hover:opacity-100 transition-opacity">
                {point.rate}%
              </div>
            </div>
          ))}
        </div>
        <div className="flex justify-between mt-1 text-xs text-text-muted font-theme-data">
          {data.consensus_metrics.consensus_rate_trend.map((point) => (
            <span key={point.date}>{point.date.slice(5)}</span>
          ))}
        </div>
      </div>
    </div>
  );
}
