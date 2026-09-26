'use client';

/**
 * AutoTransitionSuggestion - Animated suggestion overlay on stage boundaries.
 *
 * Displayed between stages when the backend suggests nodes are ready for
 * promotion. Click to approve the transition, dismiss to ignore.
 */

import { memo, useCallback } from 'react';
import { PIPELINE_STAGE_CONFIG, STAGE_COLOR_CLASSES, type PipelineStageType } from './types';

export interface TransitionSuggestion {
  node_id: string;
  node_label: string;
  from_stage: PipelineStageType;
  to_stage: PipelineStageType;
  confidence: number;
  reason: string;
}

interface AutoTransitionSuggestionProps {
  suggestions: TransitionSuggestion[];
  onApprove: (suggestion: TransitionSuggestion) => void;
  onDismiss: (suggestion: TransitionSuggestion) => void;
}

export const AutoTransitionSuggestion = memo(function AutoTransitionSuggestion({
  suggestions,
  onApprove,
  onDismiss,
}: AutoTransitionSuggestionProps) {
  if (suggestions.length === 0) return null;

  // Group by from_stage -> to_stage
  const groups = new Map<string, TransitionSuggestion[]>();
  for (const s of suggestions) {
    const key = `${s.from_stage}->${s.to_stage}`;
    const arr = groups.get(key) ?? [];
    arr.push(s);
    groups.set(key, arr);
  }

  return (
    <div className="space-y-2">
      {Array.from(groups.entries()).map(([key, group]) => {
        const from = group[0].from_stage;
        const to = group[0].to_stage;
        const fromColors = STAGE_COLOR_CLASSES[from];
        const toColors = STAGE_COLOR_CLASSES[to];
        const fromConfig = PIPELINE_STAGE_CONFIG[from];
        const toConfig = PIPELINE_STAGE_CONFIG[to];

        return (
          <div
            key={key}
            className="rounded-lg border border-border bg-surface/90 p-3 animate-in fade-in slide-in-from-bottom-1"
          >
            {/* Header */}
            <div className="flex items-center gap-2 mb-2 text-xs font-theme-data uppercase tracking-wide text-text-muted">
              <span className={fromColors.text}>{fromConfig.label}</span>
              <span className="text-text-muted">&rarr;</span>
              <span className={toColors.text}>{toConfig.label}</span>
              <span className="ml-auto px-1.5 py-0.5 rounded bg-[var(--accent)]/20 text-[var(--accent)] text-[10px]">
                {group.length} suggested
              </span>
            </div>

            {/* Suggestion list */}
            <div className="space-y-1.5">
              {group.slice(0, 5).map((suggestion) => (
                <SuggestionRow
                  key={suggestion.node_id}
                  suggestion={suggestion}
                  onApprove={onApprove}
                  onDismiss={onDismiss}
                />
              ))}
              {group.length > 5 && (
                <div className="text-xs text-text-muted pl-2">+ {group.length - 5} more</div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
});

// ---------------------------------------------------------------------------
// Single suggestion row
// ---------------------------------------------------------------------------

interface SuggestionRowProps {
  suggestion: TransitionSuggestion;
  onApprove: (s: TransitionSuggestion) => void;
  onDismiss: (s: TransitionSuggestion) => void;
}

const SuggestionRow = memo(function SuggestionRow({
  suggestion,
  onApprove,
  onDismiss,
}: SuggestionRowProps) {
  const handleApprove = useCallback(() => onApprove(suggestion), [onApprove, suggestion]);
  const handleDismiss = useCallback(() => onDismiss(suggestion), [onDismiss, suggestion]);

  const confidenceColor =
    suggestion.confidence >= 0.7
      ? 'text-green-400'
      : suggestion.confidence >= 0.5
        ? 'text-amber-400'
        : 'text-gray-400';

  return (
    <div className="flex items-center gap-2 px-2 py-1 rounded hover:bg-white/5 group">
      <span className={`font-theme-data text-xs ${confidenceColor}`}>
        {Math.round(suggestion.confidence * 100)}%
      </span>
      <span className="text-xs text-text truncate flex-1" title={suggestion.reason}>
        {suggestion.node_label}
      </span>
      <button
        onClick={handleApprove}
        className="opacity-0 group-hover:opacity-100 px-1.5 py-0.5 text-[10px] font-theme-data rounded bg-green-500/20 text-green-300 hover:bg-green-500/30 transition-opacity"
      >
        Promote
      </button>
      <button
        onClick={handleDismiss}
        className="opacity-0 group-hover:opacity-100 px-1.5 py-0.5 text-[10px] font-theme-data rounded bg-gray-500/20 text-gray-400 hover:bg-gray-500/30 transition-opacity"
      >
        Dismiss
      </button>
    </div>
  );
});

export default AutoTransitionSuggestion;
