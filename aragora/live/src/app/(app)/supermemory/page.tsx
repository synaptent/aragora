'use client';

import { useState, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { useSWRFetch } from '@/hooks/useSWRFetch';

interface SupermemoryStats {
  total_memories: number;
  sessions: number;
  avg_surprise: number;
  retention_rate: number;
}

interface SupermemoryEntry {
  id: string;
  content: string;
  session_id: string;
  surprise_score: number;
  importance: number;
  created_at: string;
  tags: string[];
}

interface SupermemoryResponse {
  stats: SupermemoryStats;
  recent: SupermemoryEntry[];
}

interface SearchResult {
  id: string;
  content: string;
  score: number;
  session_id: string;
  surprise_score: number;
}

export default function SupermemoryPage() {
  const { config } = useBackend();
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);

  const { data, isLoading } = useSWRFetch<{ data: SupermemoryResponse }>(
    '/api/v1/memory/supermemory/stats',
    { refreshInterval: 30000, baseUrl: config.api },
  );

  const stats = data?.data?.stats;
  const recent = data?.data?.recent || [];

  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    try {
      const response = await fetch(`${config.api}/api/v1/memory/supermemory/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: searchQuery, limit: 20 }),
        signal: AbortSignal.timeout(10000),
      });
      if (response.ok) {
        const result = await response.json();
        setSearchResults(result.data?.results || result.results || []);
      }
    } catch {
      // Search failed silently
    } finally {
      setSearching(false);
    }
  }, [searchQuery, config.api]);

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        <header className="border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="container mx-auto px-4 py-3 flex items-center justify-between">
            <Link href="/">
              <AsciiBannerCompact connected={true} />
            </Link>
            <div className="flex items-center gap-3">
              <Link
                href="/memory"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [MEMORY]
              </Link>
              <Link
                href="/memory-gateway"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [GATEWAY]
              </Link>
              <BackendSelector compact />
              <ThemeToggle />
            </div>
          </div>
        </header>

        <div className="container mx-auto px-4 py-6">
          <div className="mb-6">
            <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">
              {'>'} SUPERMEMORY EXPLORER
            </h1>
            <p className="text-text-muted font-theme-data text-sm">
              Cross-session external memory. Browse, search, and inspect long-term memories
              persisted across debate sessions via{' '}
              <code className="text-[var(--accent)]">enable_supermemory</code>.
            </p>
          </div>

          <PanelErrorBoundary panelName="Supermemory">
            {/* Stats */}
            {isLoading ? (
              <div className="text-[var(--accent)] font-theme-data animate-pulse text-center py-6">
                Loading...
              </div>
            ) : stats ? (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                <div className="p-4 bg-surface border border-border rounded-lg text-center">
                  <div className="text-3xl font-theme-data font-bold text-[var(--accent)]">
                    {stats.total_memories}
                  </div>
                  <div className="text-xs text-text-muted uppercase">Total Memories</div>
                </div>
                <div className="p-4 bg-surface border border-border rounded-lg text-center">
                  <div className="text-3xl font-theme-data font-bold text-blue-400">
                    {stats.sessions}
                  </div>
                  <div className="text-xs text-text-muted uppercase">Sessions</div>
                </div>
                <div className="p-4 bg-surface border border-border rounded-lg text-center">
                  <div className="text-3xl font-theme-data font-bold text-purple-400">
                    {stats.avg_surprise.toFixed(2)}
                  </div>
                  <div className="text-xs text-text-muted uppercase">Avg Surprise</div>
                </div>
                <div className="p-4 bg-surface border border-border rounded-lg text-center">
                  <div className="text-3xl font-theme-data font-bold text-gold">
                    {(stats.retention_rate * 100).toFixed(0)}%
                  </div>
                  <div className="text-xs text-text-muted uppercase">Retention Rate</div>
                </div>
              </div>
            ) : (
              <div className="p-4 bg-surface border border-border rounded-lg text-center mb-6">
                <p className="text-text-muted font-theme-data text-sm">
                  No supermemory data. Enable{' '}
                  <code className="text-[var(--accent)]">enable_supermemory</code> in ArenaConfig.
                </p>
              </div>
            )}

            {/* Search */}
            <div className="mb-6">
              <div className="flex gap-2">
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                  placeholder="Search supermemory..."
                  className="flex-1 px-4 py-2 bg-surface border border-border rounded font-theme-data text-sm text-text placeholder-text-muted focus:border-[var(--accent)] focus:outline-none"
                />
                <button
                  onClick={handleSearch}
                  disabled={searching || !searchQuery.trim()}
                  className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 disabled:opacity-50"
                >
                  {searching ? 'Searching...' : 'Search'}
                </button>
              </div>
            </div>

            {/* Search Results */}
            {searchResults.length > 0 && (
              <div className="mb-6 p-4 bg-surface border border-border rounded-lg">
                <h3 className="text-sm font-theme-data font-bold text-text-muted uppercase mb-3">
                  Search Results ({searchResults.length})
                </h3>
                <div className="space-y-2 max-h-[400px] overflow-y-auto">
                  {searchResults.map((result) => (
                    <div key={result.id} className="p-3 bg-bg rounded">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-xs font-theme-data text-text-muted">
                          {result.id.substring(0, 12)}
                        </span>
                        <span className="px-1.5 py-0.5 text-xs bg-[var(--accent)]/20 text-[var(--accent)] rounded font-theme-data">
                          {(result.score * 100).toFixed(0)}% match
                        </span>
                        <span className="text-xs text-text-muted">
                          surprise: {result.surprise_score.toFixed(2)}
                        </span>
                      </div>
                      <p className="text-sm text-text">{result.content}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Recent Memories */}
            <div className="p-4 bg-surface border border-border rounded-lg">
              <h3 className="text-sm font-theme-data font-bold text-text-muted uppercase mb-3">
                Recent Memories
              </h3>
              {recent.length === 0 ? (
                <p className="text-text-muted text-sm">No recent memories stored.</p>
              ) : (
                <div className="space-y-2 max-h-[500px] overflow-y-auto">
                  {recent.map((entry) => (
                    <div key={entry.id} className="p-3 bg-bg rounded">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-xs font-theme-data text-text-muted">
                          {entry.id.substring(0, 10)}
                        </span>
                        <span className="text-xs text-text-muted">
                          session: {entry.session_id.substring(0, 8)}
                        </span>
                        <span
                          className={`text-xs font-theme-data ${
                            entry.surprise_score > 0.5 ? 'text-yellow-400' : 'text-text-muted'
                          }`}
                        >
                          surprise: {entry.surprise_score.toFixed(2)}
                        </span>
                        <span className="text-xs text-text-muted">
                          imp: {entry.importance.toFixed(2)}
                        </span>
                      </div>
                      <p className="text-sm text-text line-clamp-2">{entry.content}</p>
                      {entry.tags.length > 0 && (
                        <div className="flex gap-1 mt-1">
                          {entry.tags.map((tag) => (
                            <span
                              key={tag}
                              className="px-1 py-0.5 text-xs bg-surface rounded text-text-muted"
                            >
                              {tag}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </PanelErrorBoundary>
        </div>

        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // SUPERMEMORY EXPLORER</p>
        </footer>
      </main>
    </>
  );
}
