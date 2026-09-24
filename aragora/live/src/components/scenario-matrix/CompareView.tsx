'use client';

import type { ScenarioResult } from './types';

export interface CompareViewProps {
  left: ScenarioResult;
  right: ScenarioResult;
  onClose: () => void;
}

export function CompareView({ left, right, onClose }: CompareViewProps) {
  const renderDiff = (label: string, leftVal: string | number, rightVal: string | number) => {
    const isDifferent = leftVal !== rightVal;
    return (
      <div className="grid grid-cols-3 gap-2 py-2 border-b border-border">
        <div className={`text-right ${isDifferent ? 'text-text' : 'text-text-muted'}`}>
          {typeof leftVal === 'number' ? leftVal.toFixed(0) : leftVal}
        </div>
        <div className="text-center text-xs font-theme-data text-text-muted">{label}</div>
        <div className={`text-left ${isDifferent ? 'text-text' : 'text-text-muted'}`}>
          {typeof rightVal === 'number' ? rightVal.toFixed(0) : rightVal}
        </div>
      </div>
    );
  };

  return (
    <div className="bg-surface border border-purple/40">
      <div className="px-4 py-3 border-b border-purple/20 bg-bg/50 flex items-center justify-between">
        <span className="text-xs font-theme-data text-purple uppercase tracking-wider">
          SCENARIO COMPARISON
        </span>
        <button
          onClick={onClose}
          className="text-xs font-theme-data text-text-muted hover:text-purple"
        >
          [CLOSE]
        </button>
      </div>

      <div className="p-4">
        {/* Headers - stack on mobile, side-by-side on desktop */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
          <div
            className={`p-3 text-center ${left.is_baseline ? 'bg-gold/10 border-gold/30' : 'bg-[var(--acid-cyan)]/10 border-[var(--acid-cyan)]/30'} border`}
          >
            <div
              className={`text-sm font-theme-data ${left.is_baseline ? 'text-gold' : 'text-[var(--acid-cyan)]'}`}
            >
              {left.scenario_name}
            </div>
            {left.is_baseline && <div className="text-xs text-gold/70">[BASELINE]</div>}
          </div>
          <div
            className={`p-3 text-center ${right.is_baseline ? 'bg-gold/10 border-gold/30' : 'bg-[var(--acid-cyan)]/10 border-[var(--acid-cyan)]/30'} border`}
          >
            <div
              className={`text-sm font-theme-data ${right.is_baseline ? 'text-gold' : 'text-[var(--acid-cyan)]'}`}
            >
              {right.scenario_name}
            </div>
            {right.is_baseline && <div className="text-xs text-gold/70">[BASELINE]</div>}
          </div>
        </div>

        {/* Comparison metrics */}
        <div className="bg-bg/50 border border-border p-4 text-xs font-theme-data">
          {renderDiff(
            'Consensus',
            left.consensus_reached ? 'YES' : 'NO',
            right.consensus_reached ? 'YES' : 'NO',
          )}
          {renderDiff(
            'Confidence',
            `${(left.confidence * 100).toFixed(0)}%`,
            `${(right.confidence * 100).toFixed(0)}%`,
          )}
          {renderDiff('Rounds', left.rounds_used, right.rounds_used)}
          {renderDiff('Winner', left.winner || '-', right.winner || '-')}
        </div>

        {/* Conclusions - stack on mobile, side-by-side on desktop */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-4">
          <div>
            <div className="text-xs font-theme-data text-text-muted mb-2">
              CONCLUSION <span className="sm:hidden text-purple">({left.scenario_name})</span>
            </div>
            <div className="text-xs font-theme-data text-text bg-bg/50 p-3 border border-border max-h-40 overflow-y-auto">
              {left.final_answer || 'No conclusion'}
            </div>
          </div>
          <div>
            <div className="text-xs font-theme-data text-text-muted mb-2">
              CONCLUSION <span className="sm:hidden text-purple">({right.scenario_name})</span>
            </div>
            <div className="text-xs font-theme-data text-text bg-bg/50 p-3 border border-border max-h-40 overflow-y-auto">
              {right.final_answer || 'No conclusion'}
            </div>
          </div>
        </div>

        {/* Parameters comparison - stack on mobile, side-by-side on desktop */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-4">
          <div>
            <div className="text-xs font-theme-data text-text-muted mb-2">
              PARAMETERS <span className="sm:hidden text-purple">({left.scenario_name})</span>
            </div>
            <div className="flex flex-wrap gap-1">
              {Object.entries(left.parameters).map(([key, value]) => (
                <span
                  key={key}
                  className="px-1 py-0.5 bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)] text-[10px] font-theme-data"
                >
                  {key}={String(value)}
                </span>
              ))}
              {Object.keys(left.parameters).length === 0 && (
                <span className="text-text-muted text-[10px]">None</span>
              )}
            </div>
          </div>
          <div>
            <div className="text-xs font-theme-data text-text-muted mb-2">
              PARAMETERS <span className="sm:hidden text-purple">({right.scenario_name})</span>
            </div>
            <div className="flex flex-wrap gap-1">
              {Object.entries(right.parameters).map(([key, value]) => (
                <span
                  key={key}
                  className="px-1 py-0.5 bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)] text-[10px] font-theme-data"
                >
                  {key}={String(value)}
                </span>
              ))}
              {Object.keys(right.parameters).length === 0 && (
                <span className="text-text-muted text-[10px]">None</span>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default CompareView;
