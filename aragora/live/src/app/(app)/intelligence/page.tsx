'use client';

import { useState, useCallback } from 'react';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { useAsyncData } from '@/hooks/useAsyncData';
import { MemoryTierViz } from '@/components/intelligence/MemoryTierViz';
import { PressureGauge } from '@/components/intelligence/PressureGauge';
import { KnowledgeDashboard } from '@/components/intelligence/KnowledgeDashboard';
import { FactsBrowser } from '@/components/intelligence/FactsBrowser';

type TabType = 'memory' | 'knowledge' | 'search';

interface TierStats {
  name: string;
  count: number;
  avg_importance: number;
  size_bytes: number;
}

interface PressureData {
  pressure: number;
  by_tier?: Record<string, number>;
  recommendation?: string;
}

interface KnowledgeStats {
  coverage: number;
  quality: number;
  total_nodes: number;
  contradictions: number;
  top_queries?: string[];
  recommendations?: string[];
}

interface FactEntry {
  id: string;
  content: string;
  confidence: number;
  verified: boolean;
  source?: string;
  created_at: string;
}

interface FactsResponse {
  facts: FactEntry[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

interface SearchResult {
  id: string;
  content: string;
  tier: string;
  importance: number;
  created_at: string;
}

export default function IntelligencePage() {
  const { config: backendConfig } = useBackend();
  const [activeTab, setActiveTab] = useState<TabType>('memory');
  const [factsPage, setFactsPage] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchInput, setSearchInput] = useState('');

  // --- MEMORY TAB fetchers ---

  const tierStatsFetcher = useCallback(async (): Promise<TierStats[]> => {
    try {
      const res = await fetch(`${backendConfig.api}/api/v1/memory/tier-stats`);
      if (!res.ok) return [];
      const data = await res.json();
      return data.tiers ?? data.data?.tiers ?? data ?? [];
    } catch {
      return [];
    }
  }, [backendConfig.api]);

  const pressureFetcher = useCallback(async (): Promise<PressureData | null> => {
    try {
      const res = await fetch(`${backendConfig.api}/api/v1/memory/pressure`);
      if (!res.ok) return null;
      const data = await res.json();
      return data.data ?? data;
    } catch {
      return null;
    }
  }, [backendConfig.api]);

  // --- KNOWLEDGE TAB fetchers ---

  const knowledgeStatsFetcher = useCallback(async (): Promise<KnowledgeStats | null> => {
    try {
      const [coverageRes, qualityRes, statsRes] = await Promise.all([
        fetch(`${backendConfig.api}/api/v1/knowledge/mound/analytics/coverage`),
        fetch(`${backendConfig.api}/api/v1/knowledge/mound/analytics/quality/trend`),
        fetch(`${backendConfig.api}/api/v1/knowledge/mound/analytics/stats`),
      ]);

      const coverage = coverageRes.ok ? await coverageRes.json() : {};
      const quality = qualityRes.ok ? await qualityRes.json() : {};
      const stats = statsRes.ok ? await statsRes.json() : {};

      return {
        coverage: coverage.data?.coverage ?? coverage.coverage ?? 0,
        quality: quality.data?.quality ?? quality.quality ?? 0,
        total_nodes: stats.data?.total_nodes ?? stats.total_nodes ?? 0,
        contradictions: stats.data?.contradictions ?? stats.contradictions ?? 0,
        top_queries: stats.data?.top_queries ?? stats.top_queries,
        recommendations: quality.data?.recommendations ?? quality.recommendations,
      };
    } catch {
      return null;
    }
  }, [backendConfig.api]);

  const factsFetcher = useCallback(async (): Promise<FactsResponse | null> => {
    try {
      const res = await fetch(
        `${backendConfig.api}/api/v1/knowledge/facts?page=${factsPage}&per_page=20`,
      );
      if (!res.ok) return null;
      const data = await res.json();
      return data.data ?? data;
    } catch {
      return null;
    }
  }, [backendConfig.api, factsPage]);

  // --- SEARCH TAB fetcher ---

  const searchFetcher = useCallback(async (): Promise<SearchResult[]> => {
    if (!searchQuery) return [];
    try {
      const res = await fetch(
        `${backendConfig.api}/api/v1/memory/search?q=${encodeURIComponent(searchQuery)}&tier=fast,medium,slow,glacial&limit=20`,
      );
      if (!res.ok) return [];
      const data = await res.json();
      return data.data?.results ?? data.results ?? data ?? [];
    } catch {
      return [];
    }
  }, [backendConfig.api, searchQuery]);

  // --- Hook up data ---

  const { data: tierStats, loading: tierLoading } = useAsyncData(tierStatsFetcher, {
    immediate: true,
  });

  const { data: pressure, loading: pressureLoading } = useAsyncData(pressureFetcher, {
    immediate: true,
  });

  const { data: knowledgeStats, loading: knowledgeLoading } = useAsyncData(knowledgeStatsFetcher, {
    immediate: true,
  });

  const { data: factsData, loading: factsLoading } = useAsyncData(factsFetcher, {
    immediate: true,
    deps: [factsPage],
  });

  const { data: searchResults, loading: searchLoading } = useAsyncData(searchFetcher, {
    immediate: false,
    deps: [searchQuery],
  });

  const handleSearch = () => {
    if (searchInput.trim()) {
      setSearchQuery(searchInput.trim());
    }
  };

  const handleSearchKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSearch();
  };

  const tabs: { id: TabType; label: string }[] = [
    { id: 'memory', label: 'MEMORY' },
    { id: 'knowledge', label: 'KNOWLEDGE' },
    { id: 'search', label: 'SEARCH' },
  ];

  const TIER_TEXT: Record<string, string> = {
    fast: 'text-[var(--accent)]',
    medium: 'text-[var(--acid-cyan)]',
    slow: 'text-[var(--acid-yellow)]',
    glacial: 'text-text-muted',
  };

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        <div className="container mx-auto px-4 py-6">
          {/* Header */}
          <div className="mb-6">
            <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">
              {'>'} INTELLIGENCE HUB
            </h1>
            <p className="text-text-muted font-theme-data text-sm">
              Memory tiers, knowledge graph, and unified search across all intelligence systems.
            </p>
          </div>

          {/* Tab Navigation */}
          <div className="flex flex-wrap gap-1 border-b border-[var(--accent)]/20 pb-2 mb-6">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-4 py-2 text-xs font-theme-data transition-colors ${
                  activeTab === tab.id
                    ? 'bg-[var(--accent)] text-bg'
                    : 'text-text-muted hover:text-[var(--accent)]'
                }`}
              >
                [{tab.label}]
              </button>
            ))}
          </div>

          {/* Tab Content */}
          <div className="space-y-6">
            {/* Memory Tab */}
            {activeTab === 'memory' && (
              <PanelErrorBoundary panelName="Memory">
                <div className="space-y-6">
                  <section>
                    <h2 className="text-lg font-theme-data text-[var(--accent)] mb-4">
                      {'>'} TIER DISTRIBUTION
                    </h2>
                    <MemoryTierViz tiers={tierStats ?? []} loading={tierLoading} />
                  </section>

                  <section>
                    <h2 className="text-lg font-theme-data text-[var(--accent)] mb-4">
                      {'>'} PRESSURE MONITOR
                    </h2>
                    <PressureGauge
                      pressure={pressure?.pressure ?? 0}
                      byTier={pressure?.by_tier}
                      recommendation={pressure?.recommendation}
                      loading={pressureLoading}
                    />
                  </section>
                </div>
              </PanelErrorBoundary>
            )}

            {/* Knowledge Tab */}
            {activeTab === 'knowledge' && (
              <PanelErrorBoundary panelName="Knowledge">
                <div className="space-y-6">
                  <section>
                    <h2 className="text-lg font-theme-data text-[var(--accent)] mb-4">
                      {'>'} KNOWLEDGE MOUND
                    </h2>
                    <KnowledgeDashboard
                      stats={
                        knowledgeStats ?? {
                          coverage: 0,
                          quality: 0,
                          total_nodes: 0,
                          contradictions: 0,
                        }
                      }
                      loading={knowledgeLoading}
                    />
                  </section>

                  <section>
                    <h2 className="text-lg font-theme-data text-[var(--accent)] mb-4">
                      {'>'} FACTS BROWSER
                    </h2>
                    <FactsBrowser
                      facts={factsData?.facts ?? []}
                      onPageChange={setFactsPage}
                      totalPages={factsData?.total_pages ?? 1}
                      currentPage={factsPage}
                      loading={factsLoading}
                    />
                  </section>
                </div>
              </PanelErrorBoundary>
            )}

            {/* Search Tab */}
            {activeTab === 'search' && (
              <PanelErrorBoundary panelName="Search">
                <div className="space-y-6">
                  <section>
                    <h2 className="text-lg font-theme-data text-[var(--accent)] mb-4">
                      {'>'} UNIFIED SEARCH
                    </h2>

                    {/* Search input */}
                    <div className="flex gap-2 mb-4">
                      <input
                        type="text"
                        value={searchInput}
                        onChange={(e) => setSearchInput(e.target.value)}
                        onKeyDown={handleSearchKeyDown}
                        placeholder="Search across all memory tiers..."
                        className="flex-1 bg-surface border border-[var(--accent)]/20 rounded px-4 py-2 font-theme-data text-sm text-text placeholder:text-text-muted/50 focus:outline-none focus:border-[var(--accent)]/50"
                      />
                      <button
                        onClick={handleSearch}
                        disabled={!searchInput.trim()}
                        className="px-4 py-2 bg-[var(--accent)]/10 border border-[var(--accent)]/30 rounded font-theme-data text-sm text-[var(--accent)] hover:bg-[var(--accent)]/20 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                      >
                        SEARCH
                      </button>
                    </div>

                    {/* Search results */}
                    {searchLoading ? (
                      <div className="animate-pulse space-y-3">
                        {[1, 2, 3].map((i) => (
                          <div key={i} className="h-16 bg-surface rounded" />
                        ))}
                      </div>
                    ) : searchQuery && searchResults && searchResults.length > 0 ? (
                      <div className="space-y-2">
                        {searchResults.map((result) => (
                          <div
                            key={result.id}
                            className="border border-[var(--accent)]/10 rounded p-3 hover:bg-[var(--accent)]/5 transition-colors"
                          >
                            <div className="flex items-start justify-between gap-3">
                              <p className="text-text font-theme-data text-sm flex-1 leading-relaxed">
                                {result.content}
                              </p>
                              <div className="flex items-center gap-2 shrink-0">
                                {/* Tier badge */}
                                <span
                                  className={`text-xs font-theme-data px-1.5 py-0.5 rounded border border-current/30 ${TIER_TEXT[result.tier] ?? 'text-text-muted'}`}
                                >
                                  {result.tier.toUpperCase()}
                                </span>
                                {/* Importance */}
                                <span className="text-text-muted text-xs font-theme-data">
                                  imp: {result.importance.toFixed(2)}
                                </span>
                              </div>
                            </div>
                            <div className="mt-2">
                              <span className="text-text-muted text-xs font-theme-data">
                                {new Date(result.created_at).toLocaleDateString()}
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : searchQuery ? (
                      <p className="text-text-muted text-sm font-theme-data text-center py-8">
                        No results found for &quot;{searchQuery}&quot;
                      </p>
                    ) : (
                      <p className="text-text-muted text-sm font-theme-data text-center py-8">
                        Enter a query to search across all memory tiers.
                      </p>
                    )}
                  </section>
                </div>
              </PanelErrorBoundary>
            )}
          </div>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // INTELLIGENCE HUB</p>
        </footer>
      </main>
    </>
  );
}
