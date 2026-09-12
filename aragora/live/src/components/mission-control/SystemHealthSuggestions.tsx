'use client';

import { memo, useState } from 'react';

export interface HealthSuggestion {
  id: string;
  title: string;
  metricSource: string;
  currentValue: string;
  targetValue?: string;
  impactEstimate: 'high' | 'medium' | 'low';
  description: string;
}

export interface SystemHealthSuggestionsProps {
  suggestions: HealthSuggestion[];
  onAddToPipeline: (suggestion: HealthSuggestion) => Promise<void>;
  isLoading?: boolean;
}

const IMPACT_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  high: { bg: 'bg-red-500/20', text: 'text-red-400', label: 'High Impact' },
  medium: { bg: 'bg-amber-500/20', text: 'text-amber-400', label: 'Medium Impact' },
  low: { bg: 'bg-blue-500/20', text: 'text-blue-400', label: 'Low Impact' },
};

export const SystemHealthSuggestions = memo(function SystemHealthSuggestions({
  suggestions,
  onAddToPipeline,
  isLoading,
}: SystemHealthSuggestionsProps) {
  const [addingIds, setAddingIds] = useState<Set<string>>(new Set());

  const handleAdd = async (suggestion: HealthSuggestion) => {
    setAddingIds((prev) => new Set([...prev, suggestion.id]));
    try {
      await onAddToPipeline(suggestion);
    } finally {
      setAddingIds((prev) => {
        const next = new Set(prev);
        next.delete(suggestion.id);
        return next;
      });
    }
  };

  if (suggestions.length === 0 && !isLoading) return null;

  return (
    <div className="space-y-2" data-testid="system-health-suggestions">
      <div className="flex items-center gap-1.5">
        <span className="text-sm">💡</span>
        <span className="text-xs font-theme-data font-bold text-[var(--text)]">
          System Suggestions
        </span>
        {isLoading && (
          <span className="text-xs text-[var(--text-muted)] animate-pulse">analyzing...</span>
        )}
      </div>

      {suggestions.map((suggestion) => {
        const impact = IMPACT_STYLES[suggestion.impactEstimate] || IMPACT_STYLES.medium;
        const isAdding = addingIds.has(suggestion.id);

        return (
          <div
            key={suggestion.id}
            className="p-3 bg-[var(--surface)] border border-[var(--border)] rounded-lg space-y-2"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-theme-data font-bold text-[var(--text)]">
                    {suggestion.title}
                  </span>
                  <span
                    className={`px-1.5 py-0.5 text-[10px] font-theme-data rounded ${impact.bg} ${impact.text}`}
                  >
                    {impact.label}
                  </span>
                </div>
                <p className="text-xs text-[var(--text-muted)] mt-0.5">{suggestion.description}</p>
              </div>
            </div>

            <div className="flex items-center gap-3 text-xs font-theme-data">
              <span className="text-[var(--text-muted)]">
                metric: <span className="text-[var(--text)]">{suggestion.metricSource}</span>
              </span>
              <span className="text-[var(--text-muted)]">
                current: <span className="text-[var(--text)]">{suggestion.currentValue}</span>
              </span>
              {suggestion.targetValue && (
                <span className="text-[var(--text-muted)]">
                  target: <span className="text-emerald-400">{suggestion.targetValue}</span>
                </span>
              )}
            </div>

            <button
              className={`w-full px-3 py-1.5 text-xs font-theme-data rounded transition-colors
                ${
                  isAdding
                    ? 'bg-gray-500/20 text-gray-400 cursor-wait'
                    : 'bg-[var(--acid-green)]/10 text-[var(--acid-green)] hover:bg-[var(--acid-green)]/20'
                }
              `}
              onClick={() => handleAdd(suggestion)}
              disabled={isAdding}
            >
              {isAdding ? 'Adding...' : '+ Add to Pipeline'}
            </button>
          </div>
        );
      })}
    </div>
  );
});

export default SystemHealthSuggestions;
