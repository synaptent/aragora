'use client';

import { useEffect, useState } from 'react';

interface ROIData {
  period: string;
  cost_efficiency: {
    cost_per_debate_usd: string;
    cost_per_consensus_usd: string;
    cost_per_user_usd: string;
    cost_trend_vs_previous_percent: number;
  };
  time_savings: {
    estimated_hours_saved: number;
    avg_time_per_manual_decision_hours: number;
    avg_time_per_ai_decision_hours: number;
    time_savings_percent: number;
    time_value_usd: string;
  };
  quality_roi: {
    decisions_with_higher_confidence: number;
    avoided_reversals: number;
    improved_consensus_quality: boolean;
    quality_score_improvement_percent: number;
  };
  roi_summary: {
    total_cost_usd: string;
    total_value_generated_usd: string;
    roi_percent: number;
    payback_period_days: number;
    value_per_dollar_spent: string;
  };
  benchmark: {
    industry_avg_cost_per_decision: string;
    our_cost_per_decision: string;
    savings_vs_industry_percent: number;
  };
}

interface ROIAnalysisProps {
  backendUrl: string;
}

export function ROIAnalysis({ backendUrl }: ROIAnalysisProps) {
  const [data, setData] = useState<ROIData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchData() {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch(`${backendUrl}/api/v1/intelligence/roi-analysis`);
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
          <div className="h-48 bg-surface rounded"></div>
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

  return (
    <div className="card p-6">
      <h2 className="text-lg font-theme-data text-[var(--accent)] mb-4">ROI Analysis</h2>

      {/* ROI Headline */}
      <div className="bg-[var(--accent)]/10 rounded-lg p-4 border border-[var(--accent)]/30 mb-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-text-muted text-xs font-theme-data">Return on Investment</p>
            <p className="text-3xl font-theme-data text-[var(--accent)] font-bold">
              {data.roi_summary.roi_percent.toLocaleString()}%
            </p>
          </div>
          <div className="text-right">
            <p className="text-text-muted text-xs font-theme-data">Value per $1 spent</p>
            <p className="text-2xl font-theme-data text-[var(--accent)]">
              ${data.roi_summary.value_per_dollar_spent}
            </p>
          </div>
        </div>
        <div className="mt-3 text-xs font-theme-data text-text-muted">
          ${data.roi_summary.total_cost_usd} invested / $
          {data.roi_summary.total_value_generated_usd} value
        </div>
      </div>

      {/* Cost vs Value */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div className="bg-surface/50 rounded-lg p-3 border border-[var(--accent)]/20">
          <p className="text-text-muted text-xs font-theme-data mb-1">Total Cost</p>
          <p className="text-lg font-theme-data">${data.roi_summary.total_cost_usd}</p>
          <p className="text-xs text-text-muted">
            ${data.cost_efficiency.cost_per_debate_usd}/debate
          </p>
        </div>
        <div className="bg-surface/50 rounded-lg p-3 border border-[var(--accent)]/20">
          <p className="text-text-muted text-xs font-theme-data mb-1">Value Generated</p>
          <p className="text-lg font-theme-data text-[var(--accent)]">
            ${data.roi_summary.total_value_generated_usd}
          </p>
          <p className="text-xs text-text-muted">
            {data.time_savings.estimated_hours_saved} hours saved
          </p>
        </div>
      </div>

      {/* Time Savings */}
      <div className="bg-surface/30 rounded-lg p-4 border border-[var(--accent)]/10 mb-4">
        <h3 className="text-sm font-theme-data text-[var(--accent)] mb-2">Time Savings</h3>
        <div className="flex items-center gap-4">
          <div className="flex-1">
            <div className="flex justify-between text-xs font-theme-data mb-1">
              <span className="text-text-muted">Manual</span>
              <span>{data.time_savings.avg_time_per_manual_decision_hours}h/decision</span>
            </div>
            <div className="h-2 bg-red-400/30 rounded-full"></div>
          </div>
          <span className="text-[var(--accent)] font-theme-data">vs</span>
          <div className="flex-1">
            <div className="flex justify-between text-xs font-theme-data mb-1">
              <span className="text-text-muted">AI-Assisted</span>
              <span>{data.time_savings.avg_time_per_ai_decision_hours}h/decision</span>
            </div>
            <div className="h-2 bg-bg rounded-full overflow-hidden">
              <div
                className="h-full bg-[var(--accent)]"
                style={{
                  width: `${(data.time_savings.avg_time_per_ai_decision_hours / data.time_savings.avg_time_per_manual_decision_hours) * 100}%`,
                }}
              ></div>
            </div>
          </div>
        </div>
        <p className="text-xs font-theme-data text-center mt-2 text-[var(--accent)]">
          {data.time_savings.time_savings_percent}% faster
        </p>
      </div>

      {/* Industry Benchmark */}
      <div className="text-xs font-theme-data">
        <div className="flex justify-between text-text-muted">
          <span>Industry avg: ${data.benchmark.industry_avg_cost_per_decision}/decision</span>
          <span>Our cost: ${data.benchmark.our_cost_per_decision}/decision</span>
        </div>
        <p className="text-[var(--accent)] text-center mt-1">
          {data.benchmark.savings_vs_industry_percent}% below industry average
        </p>
      </div>
    </div>
  );
}
