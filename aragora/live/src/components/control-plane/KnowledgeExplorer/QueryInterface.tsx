'use client';

import { useState, useCallback, useRef, useEffect } from 'react';

export interface QueryInterfaceProps {
  /** Current query text */
  value: string;
  /** Callback when query text changes */
  onChange: (text: string) => void;
  /** Callback when search is submitted */
  onSearch: (text: string) => void;
  /** Whether search is in progress */
  loading?: boolean;
  /** Placeholder text */
  placeholder?: string;
  /** Recent queries for suggestions */
  recentQueries?: string[];
  /** Callback when a suggestion is clicked */
  onSuggestionClick?: (query: string) => void;
}

/**
 * Search interface for querying the Knowledge Mound.
 * Provides NL query input with suggestions and loading state.
 */
export function QueryInterface({
  value,
  onChange,
  onSearch,
  loading = false,
  placeholder = 'Search knowledge base...',
  recentQueries = [],
  onSuggestionClick,
}: QueryInterfaceProps) {
  const [showSuggestions, setShowSuggestions] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const suggestionsRef = useRef<HTMLDivElement>(null);

  // Handle input change
  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      onChange(e.target.value);
      setShowSuggestions(e.target.value.length === 0 && recentQueries.length > 0);
    },
    [onChange, recentQueries.length],
  );

  // Handle form submit
  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (value.trim()) {
        onSearch(value.trim());
        setShowSuggestions(false);
      }
    },
    [value, onSearch],
  );

  // Handle suggestion click
  const handleSuggestionClick = useCallback(
    (query: string) => {
      onChange(query);
      onSuggestionClick?.(query);
      onSearch(query);
      setShowSuggestions(false);
    },
    [onChange, onSuggestionClick, onSearch],
  );

  // Handle keyboard navigation
  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      setShowSuggestions(false);
    }
  }, []);

  // Close suggestions when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (
        suggestionsRef.current &&
        !suggestionsRef.current.contains(e.target as Node) &&
        inputRef.current &&
        !inputRef.current.contains(e.target as Node)
      ) {
        setShowSuggestions(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <div className="relative">
      <form onSubmit={handleSubmit}>
        <div className="relative">
          {/* Search icon */}
          <div className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted">
            {loading ? <span className="animate-spin">⟳</span> : <span>🔍</span>}
          </div>

          {/* Input */}
          <input
            ref={inputRef}
            type="text"
            value={value}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            onFocus={() => setShowSuggestions(value.length === 0 && recentQueries.length > 0)}
            placeholder={placeholder}
            disabled={loading}
            className={`
              w-full pl-10 pr-20 py-3
              bg-surface border border-border rounded-lg
              text-text placeholder:text-text-muted
              focus:border-[var(--accent)] focus:outline-none focus:ring-1 focus:ring-acid-green/30
              disabled:opacity-50
              transition-colors
            `}
          />

          {/* Search button */}
          <button
            type="submit"
            disabled={loading || !value.trim()}
            className={`
              absolute right-2 top-1/2 -translate-y-1/2
              px-3 py-1.5 text-sm font-theme-data rounded
              transition-colors
              ${
                loading || !value.trim()
                  ? 'bg-surface text-text-muted cursor-not-allowed'
                  : 'bg-[var(--accent)] text-bg hover:bg-[var(--accent)]/90'
              }
            `}
          >
            {loading ? '...' : 'Search'}
          </button>
        </div>
      </form>

      {/* Suggestions dropdown */}
      {showSuggestions && recentQueries.length > 0 && (
        <div
          ref={suggestionsRef}
          className="absolute top-full left-0 right-0 mt-1 bg-surface border border-border rounded-lg shadow-lg z-10 overflow-hidden"
        >
          <div className="px-3 py-2 text-xs text-text-muted border-b border-border">
            Recent searches
          </div>
          <div className="max-h-48 overflow-y-auto">
            {recentQueries.map((query, index) => (
              <button
                key={index}
                onClick={() => handleSuggestionClick(query)}
                className="w-full text-left px-3 py-2 text-sm text-text hover:bg-[var(--accent)]/10 transition-colors"
              >
                <span className="text-text-muted mr-2">↻</span>
                {query}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Helper text */}
      <div className="mt-2 flex items-center justify-between text-xs text-text-muted">
        <span>Use natural language to search the knowledge base</span>
        <span className="flex items-center gap-2">
          <kbd className="px-1.5 py-0.5 bg-surface border border-border rounded text-xs">Enter</kbd>
          <span>to search</span>
        </span>
      </div>
    </div>
  );
}

export default QueryInterface;
