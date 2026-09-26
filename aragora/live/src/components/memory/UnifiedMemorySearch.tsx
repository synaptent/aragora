'use client';

import { useUnifiedMemoryQuery, useMemorySources } from '@/hooks/useUnifiedMemory';
import { useState } from 'react';

const SOURCE_COLORS: Record<string, string> = {
  continuum: 'text-emerald-400 border-emerald-400/40 bg-emerald-400/10',
  km: 'text-blue-400 border-blue-400/40 bg-blue-400/10',
  supermemory: 'text-purple-400 border-purple-400/40 bg-purple-400/10',
  claude_mem: 'text-orange-400 border-orange-400/40 bg-orange-400/10',
};

export function UnifiedMemorySearch() {
  const { search, results, perSystem, loading, error } = useUnifiedMemoryQuery();
  const { sources } = useMemorySources();
  const [query, setQuery] = useState('');
  const [selectedSystems, setSelectedSystems] = useState<string[]>([
    'continuum',
    'km',
    'supermemory',
    'claude_mem',
  ]);

  const toggleSystem = (sys: string) => {
    setSelectedSystems((prev) =>
      prev.includes(sys) ? prev.filter((s) => s !== sys) : [...prev, sys],
    );
  };

  const handleSearch = () => {
    if (query.trim()) search(query.trim(), selectedSystems);
  };

  return (
    <div className="space-y-4">
      {/* Sources summary */}
      <div className="flex gap-3">
        {sources.map((s) => (
          <div
            key={s.name}
            className={`card p-2 flex-1 cursor-pointer border ${selectedSystems.includes(s.name) ? 'border-[var(--acid-green)]' : 'border-transparent opacity-50'}`}
            onClick={() => toggleSystem(s.name)}
          >
            <span
              className={`block text-[10px] font-theme-data ${SOURCE_COLORS[s.name]?.split(' ')[0] || 'text-[var(--text)]'}`}
            >
              {s.name}
            </span>
            <span className="block text-xs font-theme-data text-[var(--text-muted)]">
              {s.entry_count} entries
            </span>
            <span
              className={`block text-[9px] font-theme-data ${s.status === 'active' ? 'text-emerald-400' : 'text-red-400'}`}
            >
              {s.status}
            </span>
          </div>
        ))}
      </div>

      {/* Search input */}
      <div className="flex gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          placeholder="Search across all memory systems..."
          className="flex-1 bg-[var(--bg)] border border-[var(--text-muted)]/30 rounded px-3 py-2 font-theme-data text-sm text-[var(--text)] placeholder:text-[var(--text-muted)]/50 focus:border-[var(--acid-green)] focus:outline-none"
        />
        <button
          onClick={handleSearch}
          disabled={loading}
          className="px-4 py-2 bg-[var(--acid-green)]/20 border border-[var(--acid-green)]/40 text-[var(--acid-green)] font-theme-data text-sm rounded hover:bg-[var(--acid-green)]/30 disabled:opacity-50"
        >
          {loading ? 'Searching...' : 'Search'}
        </button>
      </div>

      {/* Per-system counts */}
      {Object.keys(perSystem).length > 0 && (
        <div className="flex gap-3 font-theme-data text-xs">
          {Object.entries(perSystem).map(([sys, count]) => (
            <span key={sys} className={SOURCE_COLORS[sys]?.split(' ')[0] || ''}>
              {sys}: {count}
            </span>
          ))}
        </div>
      )}

      {/* Results */}
      {error && (
        <div className="text-red-400 font-theme-data text-sm">Search failed: {error.message}</div>
      )}
      <div className="space-y-2">
        {results.map((r, i) => (
          <div key={i} className="card p-3 space-y-1">
            <div className="flex items-center justify-between">
              <span
                className={`text-[10px] font-theme-data px-2 py-0.5 border rounded ${SOURCE_COLORS[r.source] || ''}`}
              >
                {r.source}
              </span>
              <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                {(r.relevance * 100).toFixed(0)}% relevant
              </span>
            </div>
            <p className="font-theme-data text-xs text-[var(--text)]">{r.content}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
