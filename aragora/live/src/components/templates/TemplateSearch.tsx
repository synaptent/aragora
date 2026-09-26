'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { API_BASE_URL } from '@/config';

interface RecommendedTemplate {
  name: string;
  category: string;
  description: string;
  relevance: number;
}

interface TemplateSearchProps {
  onSelect: (templateName: string) => void;
}

export function TemplateSearch({ onSelect }: TemplateSearchProps) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<RecommendedTemplate[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const search = useCallback(async (q: string) => {
    if (!q.trim() || q.length < 3) {
      setResults([]);
      return;
    }
    setIsSearching(true);
    try {
      const response = await fetch(
        `${API_BASE_URL}/api/v1/templates/recommend?question=${encodeURIComponent(q)}`,
      );
      if (response.ok) {
        const data = await response.json();
        const items = Array.isArray(data) ? data : (data.templates ?? []);
        setResults(items.slice(0, 3));
      } else {
        setResults([]);
      }
    } catch {
      setResults([]);
    } finally {
      setIsSearching(false);
    }
  }, []);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => search(query), 500);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, search]);

  return (
    <div className="relative">
      <div className="flex items-center gap-2">
        <span className="text-xs font-theme-data text-[var(--accent)]">SEARCH:</span>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Describe your decision to find matching templates..."
          className="flex-1 px-4 py-2 text-sm font-theme-data bg-surface border border-[var(--accent)]/30
                   text-text placeholder-text-muted/50 focus:border-[var(--accent)] focus:outline-none"
        />
        {isSearching && (
          <div className="w-4 h-4 border-2 border-[var(--accent)]/30 border-t-acid-green rounded-full animate-spin" />
        )}
      </div>

      {results.length > 0 && (
        <div className="absolute left-0 right-0 top-full mt-1 z-20 border border-[var(--accent)]/30 bg-surface">
          {results.map((result) => (
            <button
              key={result.name}
              onClick={() => {
                onSelect(result.name);
                setQuery('');
                setResults([]);
              }}
              className="w-full px-4 py-3 text-left hover:bg-[var(--accent)]/10 transition-colors border-b border-[var(--accent)]/10 last:border-b-0"
            >
              <div className="flex items-center justify-between mb-1">
                <span className="text-sm font-theme-data text-[var(--accent)]">{result.name}</span>
                <span className="px-2 py-0.5 text-xs font-theme-data bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/20">
                  {Math.round((result.relevance ?? 0) * 100)}% match
                </span>
              </div>
              <p className="text-xs font-theme-data text-text-muted line-clamp-1">
                {result.description}
              </p>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
