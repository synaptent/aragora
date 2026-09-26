'use client';

import { getAgentColors } from '@/utils/agentColors';
import type { ScenarioResult } from './types';

export interface ScenarioCardProps {
  result: ScenarioResult;
  isExpanded: boolean;
  onToggle: () => void;
  index?: number;
}

export function ScenarioCard({ result, isExpanded, onToggle, index }: ScenarioCardProps) {
  const winnerColors = result.winner ? getAgentColors(result.winner) : null;
  const cardId = `scenario-card-${index ?? result.scenario_name.replace(/\s+/g, '-')}`;

  return (
    <div
      className={`bg-surface border transition-colors ${
        result.is_baseline
          ? 'border-gold/40'
          : result.consensus_reached
            ? 'border-[var(--accent)]/40'
            : 'border-[var(--crimson)]/40'
      }`}
      role="article"
      aria-labelledby={`${cardId}-title`}
    >
      <div
        className="px-4 py-3 cursor-pointer hover:bg-bg/50 transition-colors focus:outline-none focus:ring-2 focus:ring-acid-green/50 focus:bg-bg/50"
        onClick={onToggle}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onToggle();
          }
        }}
        tabIndex={0}
        role="button"
        aria-expanded={isExpanded}
        aria-controls={`${cardId}-content`}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span
              className={`text-xs font-theme-data ${
                result.is_baseline ? 'text-gold' : 'text-[var(--acid-cyan)]'
              }`}
              aria-hidden="true"
            >
              {result.is_baseline ? '[BASELINE]' : '[SCENARIO]'}
            </span>
            <span id={`${cardId}-title`} className="text-sm font-theme-data text-text">
              {result.scenario_name}
              <span className="sr-only">
                {result.is_baseline ? ' (baseline)' : ''} -
                {result.consensus_reached ? 'consensus reached' : 'no consensus'},
                {(result.confidence * 100).toFixed(0)}% confidence
              </span>
            </span>
          </div>

          <div className="flex items-center gap-3">
            {result.winner && winnerColors && (
              <span
                className={`px-2 py-0.5 ${winnerColors.bg} ${winnerColors.text} text-xs font-theme-data`}
              >
                {result.winner}
              </span>
            )}
            <span
              className={`w-2 h-2 rounded-full ${
                result.consensus_reached ? 'bg-[var(--accent)]' : 'bg-[var(--crimson)]'
              }`}
            />
            <span className="text-xs font-theme-data text-text-muted">
              {(result.confidence * 100).toFixed(0)}%
            </span>
            <span className="text-xs font-theme-data text-text-muted">
              {isExpanded ? '[-]' : '[+]'}
            </span>
          </div>
        </div>

        {/* Parameters preview */}
        {Object.keys(result.parameters).length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2">
            {Object.entries(result.parameters).map(([key, value]) => (
              <span
                key={key}
                className="px-2 py-0.5 bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)] text-[10px] font-theme-data"
              >
                {key}={String(value)}
              </span>
            ))}
          </div>
        )}
      </div>

      {isExpanded && (
        <div id={`${cardId}-content`} className="px-4 pb-4 border-t border-border space-y-3 pt-3">
          {/* Final answer */}
          <div>
            <div className="text-xs font-theme-data text-text-muted mb-1">CONCLUSION</div>
            <div className="text-sm font-theme-data text-text bg-bg/50 p-3 border border-border">
              {result.final_answer || 'No conclusion reached'}
            </div>
          </div>

          {/* Constraints */}
          {result.constraints.length > 0 && (
            <div>
              <div className="text-xs font-theme-data text-text-muted mb-1">CONSTRAINTS</div>
              <ul className="space-y-1">
                {result.constraints.map((c, i) => (
                  <li
                    key={i}
                    className="text-xs font-theme-data text-text-muted pl-2 border-l border-gold/30"
                  >
                    {c}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Stats */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 pt-2 border-t border-border">
            <div className="text-xs font-theme-data">
              <span className="text-text-muted">Rounds: </span>
              <span className="text-text">{result.rounds_used}</span>
            </div>
            <div className="text-xs font-theme-data">
              <span className="text-text-muted">Consensus: </span>
              <span
                className={
                  result.consensus_reached ? 'text-[var(--accent)]' : 'text-[var(--crimson)]'
                }
              >
                {result.consensus_reached ? 'YES' : 'NO'}
              </span>
            </div>
            <div className="text-xs font-theme-data">
              <span className="text-text-muted">Confidence: </span>
              <span className="text-[var(--acid-cyan)]">
                {(result.confidence * 100).toFixed(0)}%
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default ScenarioCard;
