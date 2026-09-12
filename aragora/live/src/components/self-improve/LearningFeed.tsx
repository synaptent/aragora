'use client';

import { useLearningInsights } from '@/hooks/useSelfImproveDetails';

const INSIGHT_COLORS: Record<string, string> = {
  high_roi: 'text-emerald-400 border-emerald-400/30 bg-emerald-400/5',
  recurring_failure: 'text-red-400 border-red-400/30 bg-red-400/5',
  calibration: 'text-blue-400 border-blue-400/30 bg-blue-400/5',
};

export function LearningFeed() {
  const { insights, highRoiPatterns, recurringFailures, loading } = useLearningInsights();

  if (loading)
    return (
      <div className="animate-pulse p-4 text-[var(--text-muted)] font-theme-data">
        Loading learning insights...
      </div>
    );

  return (
    <div className="space-y-4">
      {/* High ROI Patterns */}
      {highRoiPatterns.length > 0 && (
        <div className="card p-4 space-y-2">
          <h4 className="font-theme-data text-xs text-emerald-400 uppercase tracking-wider">
            High-ROI Patterns
          </h4>
          {highRoiPatterns.map((p, i) => (
            <div key={i} className="flex items-center justify-between text-xs font-theme-data">
              <span className="text-[var(--text)]">{p.pattern}</span>
              <span className="text-emerald-400">{(p.roi_score * 100).toFixed(0)}% ROI</span>
            </div>
          ))}
        </div>
      )}

      {/* Recurring Failures */}
      {recurringFailures.length > 0 && (
        <div className="card p-4 space-y-2">
          <h4 className="font-theme-data text-xs text-red-400 uppercase tracking-wider">
            Recurring Failures (Avoided)
          </h4>
          {recurringFailures.map((f, i) => (
            <div key={i} className="flex items-center justify-between text-xs font-theme-data">
              <span className="text-[var(--text-muted)]">{f.description}</span>
              <span className="text-red-400">{f.occurrences}x</span>
            </div>
          ))}
        </div>
      )}

      {/* Insight Feed */}
      <div className="space-y-2">
        <h4 className="font-theme-data text-xs text-[var(--text-muted)] uppercase tracking-wider">
          Insight Feed
        </h4>
        {insights.length === 0 ? (
          <p className="text-[var(--text-muted)] font-theme-data text-sm p-2">
            No insights yet. Complete self-improvement cycles to generate learning data.
          </p>
        ) : (
          insights.map((insight, i) => (
            <div
              key={insight.cycle_id || i}
              className={`card p-3 border ${INSIGHT_COLORS[insight.insight_type] || ''}`}
            >
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] font-theme-data uppercase">
                  {insight.insight_type.replace('_', ' ')}
                </span>
                <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                  {insight.timestamp}
                </span>
              </div>
              <p className="text-xs font-theme-data">{insight.description}</p>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
