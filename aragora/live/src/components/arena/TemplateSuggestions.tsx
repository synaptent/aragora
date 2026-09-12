'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { API_BASE_URL } from '@/config';

interface TemplateSuggestion {
  name: string;
  category: string;
  description: string;
  relevance: number;
}

interface TemplateSuggestionsProps {
  question: string;
}

export function TemplateSuggestions({ question }: TemplateSuggestionsProps) {
  const router = useRouter();
  const [suggestions, setSuggestions] = useState<TemplateSuggestion[]>([]);
  const [dismissed, setDismissed] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchSuggestions = useCallback(async (q: string) => {
    if (!q.trim() || q.length < 15) {
      setSuggestions([]);
      return;
    }
    try {
      const response = await fetch(
        `${API_BASE_URL}/api/v1/templates/recommend?question=${encodeURIComponent(q)}`,
      );
      if (response.ok) {
        const data = await response.json();
        const items = Array.isArray(data) ? data : (data.templates ?? []);
        setSuggestions(items.slice(0, 3));
        setDismissed(false);
      }
    } catch {
      // Non-critical
    }
  }, []);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => fetchSuggestions(question), 500);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [question, fetchSuggestions]);

  if (dismissed || suggestions.length === 0) return null;

  return (
    <div className="mt-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-theme-data text-[var(--text-muted)]">
          SUGGESTED TEMPLATES
        </span>
        <button
          onClick={() => setDismissed(true)}
          className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
        >
          [X]
        </button>
      </div>
      <div className="flex flex-wrap gap-2">
        {suggestions.map((s) => (
          <button
            key={s.name}
            onClick={() => router.push(`/arena?template=${encodeURIComponent(s.name)}`)}
            className="flex items-center gap-2 px-3 py-1.5 text-xs font-theme-data border border-[var(--acid-cyan)]/30
                     text-[var(--text)] hover:bg-[var(--acid-cyan)]/10 transition-colors"
          >
            <span className="text-[var(--acid-cyan)]">{s.name}</span>
            <span className="px-1.5 py-0.5 text-[10px] bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/20">
              {Math.round((s.relevance ?? 0) * 100)}%
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
