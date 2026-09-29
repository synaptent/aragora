'use client';

import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { useSWRFetch } from '@/hooks/useSWRFetch';

interface CrossDebateInjection {
  debate_id: string;
  task: string;
  injected_items: number;
  sources: string[];
  timestamp: string;
}

interface LearningPattern {
  pattern: string;
  frequency: number;
  source_debates: number;
  confidence: number;
  first_seen: string;
  last_seen: string;
}

interface CrossDebateStats {
  total_injections: number;
  unique_patterns: number;
  debates_enriched: number;
  avg_items_per_debate: number;
}

interface CrossDebateResponse {
  stats: CrossDebateStats;
  recent_injections: CrossDebateInjection[];
  top_patterns: LearningPattern[];
}

export default function CrossDebatePage() {
  const { config } = useBackend();

  const { data, isLoading } = useSWRFetch<{ data: CrossDebateResponse }>(
    '/api/v1/system-intelligence/institutional-memory',
    { refreshInterval: 30000, baseUrl: config.api },
  );

  const crossDebate = data?.data;

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
                href="/knowledge-flow"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [KNOWLEDGE FLOW]
              </Link>
              <Link
                href="/system-intelligence"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [SYSTEM INTEL]
              </Link>
              <BackendSelector compact />
              <ThemeToggle />
            </div>
          </div>
        </header>

        <div className="container mx-auto px-4 py-6">
          <div className="mb-6">
            <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">
              {'>'} CROSS-DEBATE LEARNING
            </h1>
            <p className="text-text-muted font-theme-data text-sm">
              Track how institutional knowledge flows between debates. See learned patterns,
              cross-debate memory injections, and how the system builds cumulative expertise.
            </p>
          </div>

          <PanelErrorBoundary panelName="Cross-Debate Learning">
            {isLoading ? (
              <div className="text-[var(--accent)] font-theme-data animate-pulse text-center py-12">
                Loading cross-debate data...
              </div>
            ) : !crossDebate ? (
              <div className="p-8 bg-surface border border-border rounded-lg text-center">
                <p className="text-text-muted font-theme-data">
                  No cross-debate learning data available. Enable{' '}
                  <code className="text-[var(--accent)]">enable_cross_debate_memory</code> in
                  ArenaConfig.
                </p>
              </div>
            ) : (
              <div className="space-y-6">
                {/* Stats */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div className="p-4 bg-surface border border-border rounded-lg text-center">
                    <div className="text-3xl font-theme-data font-bold text-[var(--accent)]">
                      {crossDebate.stats.total_injections}
                    </div>
                    <div className="text-xs text-text-muted uppercase">Total Injections</div>
                  </div>
                  <div className="p-4 bg-surface border border-border rounded-lg text-center">
                    <div className="text-3xl font-theme-data font-bold text-blue-400">
                      {crossDebate.stats.unique_patterns}
                    </div>
                    <div className="text-xs text-text-muted uppercase">Unique Patterns</div>
                  </div>
                  <div className="p-4 bg-surface border border-border rounded-lg text-center">
                    <div className="text-3xl font-theme-data font-bold text-purple-400">
                      {crossDebate.stats.debates_enriched}
                    </div>
                    <div className="text-xs text-text-muted uppercase">Debates Enriched</div>
                  </div>
                  <div className="p-4 bg-surface border border-border rounded-lg text-center">
                    <div className="text-3xl font-theme-data font-bold text-gold">
                      {crossDebate.stats.avg_items_per_debate.toFixed(1)}
                    </div>
                    <div className="text-xs text-text-muted uppercase">Avg Items/Debate</div>
                  </div>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  {/* Learned Patterns */}
                  <div className="p-4 bg-surface border border-border rounded-lg">
                    <h2 className="text-sm font-theme-data font-bold text-text-muted uppercase mb-3">
                      Learned Patterns
                    </h2>
                    {crossDebate.top_patterns.length > 0 ? (
                      <div className="space-y-2 max-h-[400px] overflow-y-auto">
                        {crossDebate.top_patterns.map((pattern, i) => (
                          <div key={i} className="p-3 bg-bg rounded">
                            <div className="text-sm text-text mb-1">{pattern.pattern}</div>
                            <div className="flex gap-3 text-xs text-text-muted">
                              <span>Seen {pattern.frequency}x</span>
                              <span>From {pattern.source_debates} debates</span>
                              <span
                                className={`font-theme-data ${
                                  pattern.confidence >= 0.7
                                    ? 'text-[var(--accent)]'
                                    : 'text-yellow-400'
                                }`}
                              >
                                {(pattern.confidence * 100).toFixed(0)}% conf
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-text-muted text-sm">No patterns learned yet.</p>
                    )}
                  </div>

                  {/* Recent Injections */}
                  <div className="p-4 bg-surface border border-border rounded-lg">
                    <h2 className="text-sm font-theme-data font-bold text-text-muted uppercase mb-3">
                      Recent Injections
                    </h2>
                    {crossDebate.recent_injections.length > 0 ? (
                      <div className="space-y-2 max-h-[400px] overflow-y-auto">
                        {crossDebate.recent_injections.map((injection, i) => (
                          <div key={i} className="p-3 bg-bg rounded">
                            <div className="flex items-center gap-2 mb-1">
                              <span className="text-xs font-theme-data text-text-muted">
                                {injection.debate_id.substring(0, 12)}...
                              </span>
                              <span className="px-1.5 py-0.5 text-xs font-theme-data bg-[var(--accent)]/20 text-[var(--accent)] rounded">
                                +{injection.injected_items} items
                              </span>
                            </div>
                            <div className="text-sm text-text line-clamp-1">{injection.task}</div>
                            <div className="flex gap-2 mt-1">
                              {injection.sources.map((src) => (
                                <span
                                  key={src}
                                  className="text-xs px-1 py-0.5 bg-surface rounded text-text-muted"
                                >
                                  {src}
                                </span>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-text-muted text-sm">No recent injections.</p>
                    )}
                  </div>
                </div>
              </div>
            )}
          </PanelErrorBoundary>
        </div>

        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // CROSS-DEBATE LEARNING</p>
        </footer>
      </main>
    </>
  );
}
