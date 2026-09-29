import type { TokenUsage } from '../types';

interface TokenMetricsProps {
  usage: TokenUsage;
  maxTokens?: number;
}

export function TokenMetrics({ usage, maxTokens = 100000 }: TokenMetricsProps) {
  const percentage = Math.min((usage.totalTokens / maxTokens) * 100, 100);

  const formatNumber = (n: number) => {
    if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
    return n.toString();
  };

  const getBarColor = (pct: number) => {
    if (pct >= 90) return '#f44336';
    if (pct >= 70) return '#ff9800';
    return '#4caf50';
  };

  return (
    <div className="token-metrics">
      <div className="metrics-header">
        <span className="metrics-title">Token Usage</span>
        {usage.cost !== undefined && <span className="metrics-cost">${usage.cost.toFixed(4)}</span>}
      </div>

      <div className="metrics-bar">
        <div
          className="metrics-fill"
          style={{ width: `${percentage}%`, backgroundColor: getBarColor(percentage) }}
        />
      </div>

      <div className="metrics-details">
        <div className="metric">
          <span className="metric-label">Prompt</span>
          <span className="metric-value">{formatNumber(usage.promptTokens)}</span>
        </div>
        <div className="metric">
          <span className="metric-label">Completion</span>
          <span className="metric-value">{formatNumber(usage.completionTokens)}</span>
        </div>
        <div className="metric total">
          <span className="metric-label">Total</span>
          <span className="metric-value">{formatNumber(usage.totalTokens)}</span>
        </div>
      </div>
    </div>
  );
}
