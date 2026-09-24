'use client';

import { useState, useEffect } from 'react';
import dynamic from 'next/dynamic';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { DebateThisButton } from '@/components/DebateThisButton';

const EvidenceVisualizerPanel = dynamic(
  () =>
    import('@/components/EvidenceVisualizerPanel').then((m) => ({
      default: m.EvidenceVisualizerPanel,
    })),
  {
    ssr: false,
    loading: () => (
      <div className="card p-4 animate-pulse">
        <div className="h-96 bg-surface rounded" />
      </div>
    ),
  },
);

interface EvidenceStats {
  total_evidence: number;
  by_source: Record<string, number>;
  average_reliability: number;
  debate_associations: number;
  unique_debates: number;
}

export default function EvidencePage() {
  const { config: backendConfig } = useBackend();
  const [stats, setStats] = useState<EvidenceStats | null>(null);

  // Fetch evidence statistics
  useEffect(() => {
    const fetchStats = async () => {
      try {
        const res = await fetch(`${backendConfig.api}/api/evidence/statistics`);
        if (res.ok) {
          const data = await res.json();
          setStats(data.statistics || data);
        }
      } catch {
        // Statistics endpoint may not exist
      }
    };

    fetchStats();
  }, [backendConfig.api]);

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        <div className="container mx-auto px-4 py-6">
          <div className="mb-6">
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">
                {'>'} EVIDENCE & DISSENT
              </h1>
              <DebateThisButton
                question="What dissenting evidence and contrarian perspectives deserve more attention?"
                source="evidence"
                context="Dissenting views, contrarian perspectives, risk warnings, and evidence trails from debates"
                variant="icon"
              />
            </div>
            <p className="text-text-muted font-theme-data text-sm">
              Explore dissenting views, contrarian perspectives, risk warnings, and evidence trails
              from debates.
            </p>
          </div>

          {/* Evidence Statistics */}
          {stats && (
            <div className="mb-6 p-4 border border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/5 rounded">
              <h3 className="text-sm font-theme-data text-[var(--acid-cyan)] mb-3">
                Evidence Statistics
              </h3>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div>
                  <div className="text-2xl font-theme-data text-[var(--accent)]">
                    {stats.total_evidence}
                  </div>
                  <div className="text-xs font-theme-data text-text-muted">Total Evidence</div>
                </div>
                <div>
                  <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">
                    {stats.unique_debates}
                  </div>
                  <div className="text-xs font-theme-data text-text-muted">Linked Debates</div>
                </div>
                <div>
                  <div className="text-2xl font-theme-data text-gold">
                    {stats.debate_associations}
                  </div>
                  <div className="text-xs font-theme-data text-text-muted">Associations</div>
                </div>
                <div>
                  <div className="text-2xl font-theme-data text-text">
                    {(stats.average_reliability * 100).toFixed(0)}%
                  </div>
                  <div className="text-xs font-theme-data text-text-muted">Avg Reliability</div>
                </div>
              </div>
              {stats.by_source && Object.keys(stats.by_source).length > 0 && (
                <div className="mt-4 pt-3 border-t border-[var(--acid-cyan)]/20">
                  <div className="text-xs font-theme-data text-text-muted mb-2">By Source</div>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(stats.by_source).map(([source, count]) => (
                      <span
                        key={source}
                        className="px-2 py-1 text-xs font-theme-data bg-surface rounded"
                      >
                        {source}: <span className="text-[var(--accent)]">{count}</span>
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          <PanelErrorBoundary panelName="Evidence Visualizer">
            <EvidenceVisualizerPanel
              backendConfig={{ apiUrl: backendConfig.api, wsUrl: backendConfig.ws }}
            />
          </PanelErrorBoundary>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // EVIDENCE & DISSENT EXPLORER</p>
        </footer>
      </main>
    </>
  );
}
