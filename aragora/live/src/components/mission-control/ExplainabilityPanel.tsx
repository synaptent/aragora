'use client';

import { memo } from 'react';

export interface ExplainabilityFactor {
  name: string;
  weight: number;
  description: string;
  direction: 'for' | 'against' | 'neutral';
}

export interface Counterfactual {
  description: string;
  impact: string;
}

export interface ExplainabilityPanelProps {
  nodeId: string;
  nodeLabel: string;
  factors: ExplainabilityFactor[];
  counterfactuals?: Counterfactual[];
  evidenceChain?: { nodeId: string; label: string; stage: string }[];
  onClose: () => void;
}

const DIRECTION_STYLES: Record<string, { bg: string; text: string; icon: string }> = {
  for: { bg: 'bg-emerald-500/20', text: 'text-emerald-400', icon: '+' },
  against: { bg: 'bg-red-500/20', text: 'text-red-400', icon: '-' },
  neutral: { bg: 'bg-gray-500/20', text: 'text-gray-400', icon: '○' },
};

export const ExplainabilityPanel = memo(function ExplainabilityPanel({
  nodeLabel,
  factors,
  counterfactuals,
  evidenceChain,
  onClose,
}: ExplainabilityPanelProps) {
  const maxWeight = Math.max(...factors.map((f) => Math.abs(f.weight)), 0.01);

  return (
    <div
      className="flex flex-col w-80 border-l border-[var(--border)] bg-[var(--surface)]"
      data-testid="explainability-panel"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border)]">
        <div>
          <div className="text-xs font-theme-data text-[var(--text-muted)]">Explainability</div>
          <div className="text-sm font-theme-data text-[var(--text)] truncate max-w-[200px]">
            {nodeLabel}
          </div>
        </div>
        <button onClick={onClose} className="text-[var(--text-muted)] hover:text-[var(--text)]">
          ✕
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* Factor breakdown */}
        <div className="p-4 space-y-2">
          <div className="text-xs font-theme-data font-bold text-[var(--text-muted)]">
            Decision Factors
          </div>
          {factors.map((factor) => {
            const style = DIRECTION_STYLES[factor.direction] || DIRECTION_STYLES.neutral;
            const barPercent = Math.round((Math.abs(factor.weight) / maxWeight) * 100);
            return (
              <div key={factor.name} className="space-y-1">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <span className={`text-xs font-theme-data font-bold ${style.text}`}>
                      {style.icon}
                    </span>
                    <span className="text-xs font-theme-data text-[var(--text)]">
                      {factor.name}
                    </span>
                  </div>
                  <span className={`text-xs font-theme-data ${style.text}`}>
                    {factor.weight > 0 ? '+' : ''}
                    {factor.weight.toFixed(2)}
                  </span>
                </div>
                <div className="h-1 bg-[var(--border)] rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${style.bg.replace('/20', '')}`}
                    style={{ width: `${barPercent}%` }}
                  />
                </div>
                <p className="text-xs text-[var(--text-muted)]">{factor.description}</p>
              </div>
            );
          })}
        </div>

        {/* Evidence chain */}
        {evidenceChain && evidenceChain.length > 0 && (
          <div className="p-4 border-t border-[var(--border)] space-y-2">
            <div className="text-xs font-theme-data font-bold text-[var(--text-muted)]">
              Evidence Chain
            </div>
            {evidenceChain.map((node, i) => (
              <div key={node.nodeId} className="flex items-center gap-2">
                {i > 0 && <span className="text-xs text-[var(--text-muted)]">→</span>}
                <span className="text-xs font-theme-data text-[var(--text)]">{node.label}</span>
                <span className="px-1 py-0.5 text-[10px] font-theme-data bg-[var(--bg)] text-[var(--text-muted)] rounded">
                  {node.stage}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Counterfactuals */}
        {counterfactuals && counterfactuals.length > 0 && (
          <div className="p-4 border-t border-[var(--border)] space-y-2">
            <div className="text-xs font-theme-data font-bold text-[var(--text-muted)]">
              Counterfactuals
            </div>
            {counterfactuals.map((cf, i) => (
              <div key={i} className="p-2 bg-[var(--bg)] rounded border border-[var(--border)]">
                <p className="text-xs text-[var(--text)]">{cf.description}</p>
                <p className="text-xs text-[var(--text-muted)] mt-1">Impact: {cf.impact}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
});

export default ExplainabilityPanel;
