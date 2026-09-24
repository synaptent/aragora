'use client';

import { useCallback } from 'react';

export interface PulseFiltersState {
  search: string;
  sources: string[];
  categories: string[];
  minScore: number;
  timeRange: 'hour' | 'day' | 'week' | 'all';
}

export interface PulseFiltersProps {
  filters: PulseFiltersState;
  onChange: (filters: PulseFiltersState) => void;
  availableSources?: string[];
  availableCategories?: string[];
}

const DEFAULT_SOURCES = ['hackernews', 'reddit', 'twitter', 'github', 'arxiv'];
const DEFAULT_CATEGORIES = ['tech', 'ai', 'science', 'programming', 'business', 'health'];

const SOURCE_LABELS: Record<string, string> = {
  hackernews: 'HackerNews',
  reddit: 'Reddit',
  twitter: 'Twitter/X',
  github: 'GitHub',
  arxiv: 'arXiv',
};

export function PulseFilters({
  filters,
  onChange,
  availableSources = DEFAULT_SOURCES,
  availableCategories = DEFAULT_CATEGORIES,
}: PulseFiltersProps) {
  const handleSearchChange = useCallback(
    (value: string) => {
      onChange({ ...filters, search: value });
    },
    [filters, onChange],
  );

  const toggleSource = useCallback(
    (source: string) => {
      const newSources = filters.sources.includes(source)
        ? filters.sources.filter((s) => s !== source)
        : [...filters.sources, source];
      onChange({ ...filters, sources: newSources });
    },
    [filters, onChange],
  );

  const toggleCategory = useCallback(
    (category: string) => {
      const newCategories = filters.categories.includes(category)
        ? filters.categories.filter((c) => c !== category)
        : [...filters.categories, category];
      onChange({ ...filters, categories: newCategories });
    },
    [filters, onChange],
  );

  const handleMinScoreChange = useCallback(
    (value: number) => {
      onChange({ ...filters, minScore: value });
    },
    [filters, onChange],
  );

  const handleTimeRangeChange = useCallback(
    (value: 'hour' | 'day' | 'week' | 'all') => {
      onChange({ ...filters, timeRange: value });
    },
    [filters, onChange],
  );

  const clearAllFilters = useCallback(() => {
    onChange({ search: '', sources: [], categories: [], minScore: 0, timeRange: 'all' });
  }, [onChange]);

  const selectAllSources = useCallback(() => {
    onChange({ ...filters, sources: [...availableSources] });
  }, [filters, onChange, availableSources]);

  const selectAllCategories = useCallback(() => {
    onChange({ ...filters, categories: [...availableCategories] });
  }, [filters, onChange, availableCategories]);

  const hasActiveFilters =
    filters.search ||
    filters.sources.length > 0 ||
    filters.categories.length > 0 ||
    filters.minScore > 0 ||
    filters.timeRange !== 'all';

  return (
    <div className="bg-surface border border-border rounded-lg p-4 space-y-4">
      {/* Search */}
      <div>
        <label className="block text-xs font-theme-data text-text-muted mb-2">SEARCH TOPICS</label>
        <input
          type="text"
          value={filters.search}
          onChange={(e) => handleSearchChange(e.target.value)}
          placeholder="Search trending topics..."
          className="w-full px-3 py-2 bg-bg border border-border rounded text-sm font-theme-data text-text placeholder:text-text-muted/50 focus:border-[var(--accent)] focus:outline-none"
        />
      </div>

      {/* Sources */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="text-xs font-theme-data text-text-muted">SOURCES</label>
          <button
            onClick={selectAllSources}
            className="text-xs font-theme-data text-[var(--accent)]/70 hover:text-[var(--accent)]"
          >
            Select All
          </button>
        </div>
        <div className="flex flex-wrap gap-2">
          {availableSources.map((source) => (
            <button
              key={source}
              onClick={() => toggleSource(source)}
              className={`
                px-2 py-1 text-xs font-theme-data rounded border transition-colors
                ${
                  filters.sources.includes(source)
                    ? 'bg-[var(--accent)]/20 border-[var(--accent)] text-[var(--accent)]'
                    : 'bg-bg border-border text-text-muted hover:border-text-muted'
                }
              `}
            >
              {SOURCE_LABELS[source] || source}
            </button>
          ))}
        </div>
      </div>

      {/* Categories */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="text-xs font-theme-data text-text-muted">CATEGORIES</label>
          <button
            onClick={selectAllCategories}
            className="text-xs font-theme-data text-[var(--accent)]/70 hover:text-[var(--accent)]"
          >
            Select All
          </button>
        </div>
        <div className="flex flex-wrap gap-2">
          {availableCategories.map((category) => (
            <button
              key={category}
              onClick={() => toggleCategory(category)}
              className={`
                px-2 py-1 text-xs font-theme-data rounded border capitalize transition-colors
                ${
                  filters.categories.includes(category)
                    ? 'bg-[var(--acid-cyan)]/20 border-[var(--acid-cyan)] text-[var(--acid-cyan)]'
                    : 'bg-bg border-border text-text-muted hover:border-text-muted'
                }
              `}
            >
              {category}
            </button>
          ))}
        </div>
      </div>

      {/* Min Score Slider */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="text-xs font-theme-data text-text-muted">MIN SCORE</label>
          <span className="text-xs font-theme-data text-[var(--accent)]">
            {filters.minScore > 0 ? `${Math.round(filters.minScore * 100)}%+` : 'Any'}
          </span>
        </div>
        <input
          type="range"
          min={0}
          max={100}
          value={filters.minScore * 100}
          onChange={(e) => handleMinScoreChange(parseInt(e.target.value) / 100)}
          className="w-full h-1 bg-border rounded appearance-none cursor-pointer accent-acid-green"
        />
        <div className="flex justify-between text-xs text-text-muted/50 mt-1">
          <span>0%</span>
          <span>50%</span>
          <span>100%</span>
        </div>
      </div>

      {/* Time Range */}
      <div>
        <label className="block text-xs font-theme-data text-text-muted mb-2">TIME RANGE</label>
        <div className="flex gap-2">
          {(['hour', 'day', 'week', 'all'] as const).map((range) => (
            <button
              key={range}
              onClick={() => handleTimeRangeChange(range)}
              className={`
                flex-1 px-2 py-1.5 text-xs font-theme-data rounded border transition-colors
                ${
                  filters.timeRange === range
                    ? 'bg-[var(--accent)]/20 border-[var(--accent)] text-[var(--accent)]'
                    : 'bg-bg border-border text-text-muted hover:border-text-muted'
                }
              `}
            >
              {range === 'hour' ? '1H' : range === 'day' ? '24H' : range === 'week' ? '7D' : 'ALL'}
            </button>
          ))}
        </div>
      </div>

      {/* Clear Filters */}
      {hasActiveFilters && (
        <button
          onClick={clearAllFilters}
          className="w-full py-2 text-xs font-theme-data text-warning border border-warning/30 rounded hover:bg-warning/10 transition-colors"
        >
          Clear All Filters
        </button>
      )}
    </div>
  );
}

export const defaultFilters: PulseFiltersState = {
  search: '',
  sources: [],
  categories: [],
  minScore: 0,
  timeRange: 'all',
};

export default PulseFilters;
