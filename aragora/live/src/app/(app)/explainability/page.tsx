'use client';

import { useState } from 'react';
import Link from 'next/link';
import dynamic from 'next/dynamic';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { useSWRFetch } from '@/hooks/useSWRFetch';

const ExplainabilityPanel = dynamic(
  () =>
    import('@/components/ExplainabilityPanel').then((m) => ({ default: m.ExplainabilityPanel })),
  {
    ssr: false,
    loading: () => (
      <div className="card p-4 animate-pulse">
        <div className="h-[400px] bg-surface rounded" />
      </div>
    ),
  },
);

const BatchExplainabilityPanel = dynamic(
  () =>
    import('@/components/BatchExplainabilityPanel').then((m) => ({
      default: m.BatchExplainabilityPanel,
    })),
  {
    ssr: false,
    loading: () => (
      <div className="card p-4 animate-pulse">
        <div className="h-[300px] bg-surface rounded" />
      </div>
    ),
  },
);

interface RecentDebate {
  id: string;
  task: string;
  consensus_reached: boolean;
  created_at: string;
}

interface RecentDebatesResponse {
  debates?: RecentDebate[];
  data?: RecentDebate[];
}

export default function ExplainabilityPage() {
  const { config } = useBackend();
  const [selectedDebateId, setSelectedDebateId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'single' | 'batch'>('single');

  const { data: recentData, isLoading } = useSWRFetch<RecentDebatesResponse>(
    '/api/v1/debates?limit=20&sort=created_at:desc',
    { refreshInterval: 30000, baseUrl: config.api },
  );

  const debates = recentData?.debates || recentData?.data || [];

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
                href="/"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [DASHBOARD]
              </Link>
              <Link
                href="/receipts"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [RECEIPTS]
              </Link>
              <BackendSelector compact />
              <ThemeToggle />
            </div>
          </div>
        </header>

        <div className="container mx-auto px-4 py-6">
          <div className="mb-6">
            <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">
              {'>'} DECISION EXPLAINABILITY
            </h1>
            <p className="text-text-muted font-theme-data text-sm">
              Understand why decisions were made. View factor decomposition, evidence chains,
              counterfactual analysis, and vote influence for any debate.
            </p>
          </div>

          {/* Tab Switcher */}
          <div className="flex gap-2 mb-6">
            {(['single', 'batch'] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-4 py-2 text-sm font-theme-data rounded border transition-colors ${
                  activeTab === tab
                    ? 'bg-[var(--accent)]/20 border-[var(--accent)] text-[var(--accent)]'
                    : 'border-border text-text-muted hover:border-[var(--accent)]/50'
                }`}
              >
                {tab === 'single' ? 'Single Debate' : 'Batch Analysis'}
              </button>
            ))}
          </div>

          {activeTab === 'single' && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Debate Selector */}
              <div className="lg:col-span-1">
                <div className="p-4 bg-surface border border-border rounded-lg">
                  <h3 className="text-sm font-theme-data font-bold text-text-muted uppercase mb-3">
                    Select Debate
                  </h3>
                  {isLoading ? (
                    <div className="text-[var(--accent)] font-theme-data animate-pulse text-sm">
                      Loading...
                    </div>
                  ) : debates.length === 0 ? (
                    <p className="text-text-muted text-sm">No debates found. Run a debate first.</p>
                  ) : (
                    <div className="space-y-2 max-h-[500px] overflow-y-auto">
                      {debates.map((debate) => (
                        <button
                          key={debate.id}
                          onClick={() => setSelectedDebateId(debate.id)}
                          className={`w-full p-3 text-left rounded border transition-all text-sm ${
                            selectedDebateId === debate.id
                              ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                              : 'border-border hover:border-[var(--accent)]/50'
                          }`}
                        >
                          <div className="font-theme-data text-xs text-text-muted mb-1">
                            {debate.id.substring(0, 12)}...
                          </div>
                          <div className="text-text line-clamp-2">{debate.task}</div>
                          <div className="flex items-center gap-2 mt-1">
                            <span
                              className={`text-xs px-1.5 py-0.5 rounded ${
                                debate.consensus_reached
                                  ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
                                  : 'bg-yellow-500/20 text-yellow-400'
                              }`}
                            >
                              {debate.consensus_reached ? 'Consensus' : 'No Consensus'}
                            </span>
                          </div>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {/* Explanation Panel */}
              <div className="lg:col-span-2">
                {selectedDebateId ? (
                  <PanelErrorBoundary panelName="Explainability">
                    <ExplainabilityPanel debateId={selectedDebateId} />
                  </PanelErrorBoundary>
                ) : (
                  <div className="p-8 bg-surface border border-border rounded-lg text-center">
                    <div className="text-4xl mb-4">?!</div>
                    <p className="text-text-muted font-theme-data">
                      Select a debate to view its decision explanation
                    </p>
                    <p className="text-text-muted font-theme-data text-xs mt-2">
                      Factor decomposition, evidence chains, counterfactuals, and vote influence
                    </p>
                  </div>
                )}
              </div>
            </div>
          )}

          {activeTab === 'batch' && (
            <PanelErrorBoundary panelName="Batch Explainability">
              <BatchExplainabilityPanel />
            </PanelErrorBoundary>
          )}
        </div>

        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // DECISION EXPLAINABILITY</p>
        </footer>
      </main>
    </>
  );
}
