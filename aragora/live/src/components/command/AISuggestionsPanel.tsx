'use client';

interface Suggestion {
  id: string;
  title: string;
  priority: 'high' | 'medium' | 'low';
  estimatedDuration: string;
}

interface AISuggestionsPanelProps {
  suggestions: Suggestion[];
  onAddToDAG: (id: string) => void;
  onRefresh: () => void;
  loading: boolean;
}

const PRIORITY_COLORS: Record<string, string> = {
  high: 'bg-red-500/10 text-red-400 border-red-500/30',
  medium: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
  low: 'bg-blue-500/10 text-blue-400 border-blue-500/30',
};

export function AISuggestionsPanel({
  suggestions,
  onAddToDAG,
  onRefresh,
  loading,
}: AISuggestionsPanelProps) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span>{'\u2728'}</span>
          <h4 className="text-xs font-theme-data text-text-muted uppercase tracking-wider">
            AI Suggestions
          </h4>
        </div>
        <button
          onClick={onRefresh}
          disabled={loading}
          className="text-[10px] font-theme-data text-[var(--accent)] hover:underline disabled:opacity-50"
        >
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </div>

      {suggestions.length === 0 ? (
        <div className="text-xs font-theme-data text-text-muted/50 bg-bg p-3 rounded border border-border text-center">
          {loading ? 'Generating suggestions...' : 'No suggestions available'}
        </div>
      ) : (
        <div className="space-y-1.5">
          {suggestions.map((s) => (
            <div key={s.id} className="px-2.5 py-2 bg-bg rounded border border-border">
              <div className="flex items-center gap-2 mb-1">
                <span
                  className={`px-1.5 py-0.5 text-[9px] font-theme-data rounded border ${PRIORITY_COLORS[s.priority]}`}
                >
                  {s.priority.toUpperCase()}
                </span>
                <span className="text-xs font-theme-data text-text truncate flex-1">{s.title}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-theme-data text-text-muted">
                  ~{s.estimatedDuration}
                </span>
                <button
                  onClick={() => onAddToDAG(s.id)}
                  className="text-[10px] font-theme-data text-[var(--accent)] hover:underline"
                >
                  + Add to DAG
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
