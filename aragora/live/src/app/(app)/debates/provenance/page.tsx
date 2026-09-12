'use client';

import { useState, useEffect, Suspense } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { fetchRecentDebates, type DebateArtifact } from '@/utils/supabase';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { ProvenanceGraph } from '@/components/provenance/ProvenanceGraph';
import { useRightSidebar } from '@/context/RightSidebarContext';
import { logger } from '@/utils/logger';

function ProvenancePageContent() {
  const searchParams = useSearchParams();
  const debateIdParam = searchParams.get('debate');

  const [debates, setDebates] = useState<DebateArtifact[]>([]);
  const [selectedDebateId, setSelectedDebateId] = useState<string | null>(debateIdParam);
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState<'graph' | 'timeline'>('graph');

  const { setContext, clearContext } = useRightSidebar();

  // Load recent debates for selector
  useEffect(() => {
    async function loadDebates() {
      try {
        setLoading(true);
        const data = await fetchRecentDebates(20);
        setDebates(data);

        // Auto-select first debate if none selected
        if (!selectedDebateId && data.length > 0) {
          setSelectedDebateId(data[0].id);
        }
      } catch (e) {
        logger.error('Failed to load debates:', e);
      } finally {
        setLoading(false);
      }
    }

    loadDebates();
  }, [selectedDebateId]);

  // Set up right sidebar
  useEffect(() => {
    const selectedDebate = debates.find((d) => d.id === selectedDebateId);

    setContext({
      title: 'Decision Provenance',
      subtitle: selectedDebate ? 'Tracing audit trail' : 'Select a debate',
      statsContent: selectedDebate ? (
        <div className="space-y-3">
          <div className="flex justify-between items-center">
            <span className="text-xs text-[var(--text-muted)]">Debate</span>
            <span className="text-sm font-theme-data text-[var(--acid-green)] truncate max-w-[120px]">
              {selectedDebate.task.slice(0, 30)}...
            </span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-xs text-[var(--text-muted)]">Agents</span>
            <span className="text-sm font-theme-data text-[var(--text)]">
              {selectedDebate.agents.length}
            </span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-xs text-[var(--text-muted)]">Consensus</span>
            <span
              className={`text-sm font-theme-data ${
                selectedDebate.consensus_reached ? 'text-green-400' : 'text-yellow-400'
              }`}
            >
              {selectedDebate.consensus_reached ? 'YES' : 'NO'}
            </span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-xs text-[var(--text-muted)]">Confidence</span>
            <span className="text-sm font-theme-data text-[var(--acid-cyan)]">
              {Math.round(selectedDebate.confidence * 100)}%
            </span>
          </div>
        </div>
      ) : null,
      actionsContent: (
        <div className="space-y-2">
          <Link
            href="/debates"
            className="block w-full px-3 py-2 text-xs font-theme-data text-center bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
          >
            ARCHIVE VIEW
          </Link>
          <Link
            href="/debates/graph"
            className="block w-full px-3 py-2 text-xs font-theme-data text-center bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
          >
            GRAPH VIEW
          </Link>
          <Link
            href="/audit"
            className="block w-full px-3 py-2 text-xs font-theme-data text-center bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/30 hover:bg-[var(--acid-green)]/20 transition-colors"
          >
            FULL AUDIT LOG
          </Link>
        </div>
      ),
    });

    return () => clearContext();
  }, [debates, selectedDebateId, setContext, clearContext]);

  const selectedDebate = debates.find((d) => d.id === selectedDebateId);

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-[var(--bg)] text-[var(--text)] relative z-10">
        <div className="container mx-auto px-4 py-6">
          {/* Header */}
          <div className="mb-6">
            <div className="flex items-center justify-between flex-wrap gap-4">
              <div>
                <h1 className="text-xl font-theme-data text-[var(--acid-green)] mb-2">
                  {'>'} DECISION PROVENANCE
                </h1>
                <p className="text-xs text-[var(--text-muted)] font-theme-data">
                  Trace the full audit trail of how decisions were reached
                </p>
              </div>

              {/* View mode toggle */}
              <div className="flex items-center gap-2">
                <span className="text-xs text-[var(--text-muted)] font-theme-data">View:</span>
                {(['graph', 'timeline'] as const).map((mode) => (
                  <button
                    key={mode}
                    onClick={() => setViewMode(mode)}
                    className={`px-3 py-1 text-xs font-theme-data border transition-colors uppercase ${
                      viewMode === mode
                        ? 'bg-[var(--acid-green)]/20 text-[var(--acid-green)] border-[var(--acid-green)]/40'
                        : 'bg-[var(--surface)] text-[var(--text-muted)] border-[var(--border)] hover:border-[var(--acid-green)]/40'
                    }`}
                  >
                    {mode}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Debate Selector */}
          <div className="mb-6 bg-[var(--surface)] border border-[var(--border)] p-4">
            <label className="block text-xs font-theme-data text-[var(--text-muted)] mb-2">
              SELECT DEBATE
            </label>
            <select
              value={selectedDebateId || ''}
              onChange={(e) => setSelectedDebateId(e.target.value || null)}
              className="w-full bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] font-theme-data text-sm p-2 focus:border-[var(--acid-green)] focus:outline-none"
              disabled={loading}
            >
              <option value="">{loading ? 'Loading debates...' : '-- Select a debate --'}</option>
              {debates.map((debate) => (
                <option key={debate.id} value={debate.id}>
                  {debate.task.slice(0, 60)}
                  {debate.task.length > 60 ? '...' : ''} [{' '}
                  {debate.consensus_reached ? 'CONSENSUS' : 'NO CONSENSUS'} |{' '}
                  {Math.round(debate.confidence * 100)}% ]
                </option>
              ))}
            </select>
          </div>

          {/* Provenance Graph */}
          {selectedDebateId ? (
            <div className="relative">
              <ProvenanceGraph
                debateId={selectedDebateId}
                viewMode={viewMode}
                width={1200}
                height={600}
              />

              {/* Quick info panel */}
              {selectedDebate && (
                <div className="mt-4 bg-[var(--surface)] border border-[var(--border)] p-4">
                  <h3 className="text-sm font-theme-data text-[var(--acid-green)] mb-3">
                    {'>'} DEBATE CONTEXT
                  </h3>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs font-theme-data">
                    <div>
                      <span className="text-[var(--text-muted)]">Task:</span>
                      <p className="text-[var(--text)] mt-1">{selectedDebate.task}</p>
                    </div>
                    <div>
                      <span className="text-[var(--text-muted)]">Agents:</span>
                      <div className="flex flex-wrap gap-1 mt-1">
                        {selectedDebate.agents.map((agent, i) => (
                          <span
                            key={i}
                            className="px-1.5 py-0.5 bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/30"
                          >
                            {agent.split('-')[0].toUpperCase()}
                          </span>
                        ))}
                      </div>
                    </div>
                    <div>
                      <span className="text-[var(--text-muted)]">Result:</span>
                      <p className="mt-1">
                        <span
                          className={
                            selectedDebate.consensus_reached ? 'text-green-400' : 'text-yellow-400'
                          }
                        >
                          {selectedDebate.consensus_reached ? 'Consensus Reached' : 'No Consensus'}
                        </span>
                        <span className="text-[var(--text-muted)] ml-2">
                          ({Math.round(selectedDebate.confidence * 100)}% confidence)
                        </span>
                      </p>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="bg-[var(--surface)] border border-[var(--border)] p-12 text-center">
              <div className="text-6xl mb-4"></div>
              <h3 className="text-lg font-theme-data text-[var(--text)] mb-2">
                No Debate Selected
              </h3>
              <p className="text-sm text-[var(--text-muted)] font-theme-data mb-4">
                Select a debate from the dropdown above to view its decision provenance
              </p>
              <Link
                href="/arena"
                className="inline-block px-4 py-2 text-sm font-theme-data bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/30 hover:bg-[var(--acid-green)]/20 transition-colors"
              >
                START NEW DEBATE
              </Link>
            </div>
          )}

          {/* Help section */}
          <div className="mt-6 bg-[var(--surface)]/50 border border-[var(--border)] p-4">
            <h3 className="text-sm font-theme-data text-[var(--acid-cyan)] mb-3">
              {'>'} UNDERSTANDING PROVENANCE
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 text-xs font-theme-data">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className="w-3 h-3 rounded-full bg-amber-400" />
                  <span className="text-[var(--text)]">Question</span>
                </div>
                <p className="text-[var(--text-muted)]">
                  The original task or question being debated
                </p>
              </div>
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className="w-3 h-3 rounded-full bg-purple-500" />
                  <span className="text-[var(--text)]">Agent</span>
                </div>
                <p className="text-[var(--text-muted)]">AI agents participating in the debate</p>
              </div>
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className="w-3 h-3 rounded-full bg-green-500" />
                  <span className="text-[var(--text)]">Evidence</span>
                </div>
                <p className="text-[var(--text-muted)]">Verified evidence supporting arguments</p>
              </div>
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className="w-3 h-3 rounded-full bg-[#00ff00]" />
                  <span className="text-[var(--text)]">Consensus</span>
                </div>
                <p className="text-[var(--text-muted)]">Final decision reached by agents</p>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--acid-green)]/20 mt-8">
          <div className="text-[var(--acid-green)]/50 mb-2">{'═'.repeat(40)}</div>
          <p className="text-[var(--text-muted)]">
            {'>'} DECISION PROVENANCE // AUDIT TRAIL FOR DEFENSIBLE DECISIONS
          </p>
          <div className="text-[var(--acid-green)]/50 mt-4">{'═'.repeat(40)}</div>
        </footer>
      </main>
    </>
  );
}

export default function ProvenancePage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-[var(--bg)] flex items-center justify-center">
          <div className="text-[var(--acid-green)] font-theme-data animate-pulse">
            Loading provenance data...
          </div>
        </div>
      }
    >
      <ProvenancePageContent />
    </Suspense>
  );
}
