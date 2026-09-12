'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { fetchRecentDebates, type DebateArtifact } from '@/utils/supabase';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { getAgentColors } from '@/utils/agentColors';
import { logger } from '@/utils/logger';
import { DebatesEmptyState } from '@/components/ui/EmptyState';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { useRightSidebar } from '@/context/RightSidebarContext';
import { useBackend } from '@/components/BackendSelector';
import { DebateInput } from '@/components/DebateInput';

const PAGE_SIZE = 20;

// Backend API response shape for debates list
interface BackendDebatesResponse {
  debates?: Array<{
    id: string;
    debate_id?: string;
    task?: string;
    question?: string;
    agents: string[];
    consensus_reached: boolean;
    confidence: number;
    winning_proposal?: string | null;
    vote_tally?: Record<string, number> | null;
    created_at: string;
    loop_id?: string;
    cycle_number?: number;
    phase?: string;
  }>;
  results?: Array<{
    id: string;
    debate_id?: string;
    task?: string;
    question?: string;
    agents: string[];
    consensus_reached: boolean;
    confidence: number;
    winning_proposal?: string | null;
    vote_tally?: Record<string, number> | null;
    created_at: string;
    loop_id?: string;
    cycle_number?: number;
    phase?: string;
  }>;
  total?: number;
  has_more?: boolean;
}

// Normalize backend debate data to DebateArtifact shape
function normalizeBackendDebate(
  d: NonNullable<BackendDebatesResponse['debates']>[number],
): DebateArtifact {
  return {
    id: d.debate_id || d.id,
    loop_id: d.loop_id || '',
    cycle_number: d.cycle_number || 0,
    phase: d.phase || 'completed',
    task: d.task || d.question || 'Untitled debate',
    agents: d.agents || [],
    transcript: [],
    consensus_reached: d.consensus_reached ?? false,
    confidence: d.confidence ?? 0,
    winning_proposal: d.winning_proposal ?? null,
    vote_tally: d.vote_tally ?? null,
    created_at: d.created_at || new Date().toISOString(),
  };
}

export default function DebatesPage() {
  const router = useRouter();
  const { config: backendConfig } = useBackend();
  const [debates, setDebates] = useState<DebateArtifact[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [filter, setFilter] = useState<'all' | 'consensus' | 'no-consensus'>('all');
  const [dataSource, setDataSource] = useState<'backend' | 'supabase' | 'none'>('none');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [selectedForCompare, setSelectedForCompare] = useState<string[]>([]);

  const { setContext, clearContext } = useRightSidebar();

  // Set up right sidebar content
  useEffect(() => {
    const consensusCount = debates.filter((d) => d.consensus_reached).length;
    const consensusRate =
      debates.length > 0 ? Math.round((consensusCount / debates.length) * 100) : 0;
    const avgConfidence =
      debates.length > 0
        ? Math.round(
            (debates.reduce((sum, d) => sum + (d.confidence || 0), 0) / debates.length) * 100,
          )
        : 0;

    setContext({
      title: 'Debate Archive',
      subtitle: `${debates.length} debates`,
      statsContent: (
        <div className="space-y-3">
          <div className="flex justify-between items-center">
            <span className="text-xs text-[var(--text-muted)]">Total</span>
            <span className="text-sm font-theme-data text-[var(--acid-green)]">
              {debates.length}
            </span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-xs text-[var(--text-muted)]">Consensus Rate</span>
            <span className="text-sm font-theme-data text-[var(--acid-green)]">
              {consensusRate}%
            </span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-xs text-[var(--text-muted)]">Avg Confidence</span>
            <span className="text-sm font-theme-data text-[var(--acid-cyan)]">
              {avgConfidence}%
            </span>
          </div>
        </div>
      ),
      actionsContent: (
        <div className="space-y-2">
          <Link
            href="/arena"
            className="block w-full px-3 py-2 text-xs font-theme-data text-center bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/30 hover:bg-[var(--acid-green)]/20 transition-colors"
          >
            + NEW DEBATE
          </Link>
          <button
            onClick={() => setShowCreateModal(true)}
            className="block w-full px-3 py-2 text-xs font-theme-data text-center bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/30 hover:bg-[var(--acid-cyan)]/20 transition-colors"
          >
            LIVE CREATE
          </button>
          <Link
            href="/debates/graph"
            className="block w-full px-3 py-2 text-xs font-theme-data text-center bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
          >
            GRAPH VIEW
          </Link>
          <Link
            href="/debates/matrix"
            className="block w-full px-3 py-2 text-xs font-theme-data text-center bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
          >
            MATRIX VIEW
          </Link>
          <Link
            href="/debates/provenance"
            className="block w-full px-3 py-2 text-xs font-theme-data text-center bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/30 hover:bg-[var(--acid-cyan)]/20 transition-colors"
          >
            PROVENANCE
          </Link>
        </div>
      ),
    });

    return () => clearContext();
  }, [debates, setContext, clearContext]);

  // Fetch debates from backend API, falling back to Supabase
  const fetchDebatesFromBackend = useCallback(
    async (
      limit: number,
      offset: number,
    ): Promise<{
      debates: DebateArtifact[];
      hasMore: boolean;
      source: 'backend' | 'supabase';
    } | null> => {
      try {
        const response = await fetch(
          `${backendConfig.api}/api/v1/debates?limit=${limit}&offset=${offset}&sort=created_at:desc`,
          { headers: { 'Content-Type': 'application/json' }, signal: AbortSignal.timeout(10000) },
        );
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data: BackendDebatesResponse = await response.json();
        const debateList = data.debates || data.results || [];
        const normalized = debateList.map(normalizeBackendDebate);
        const moreAvailable = data.has_more ?? normalized.length === limit;
        return { debates: normalized, hasMore: moreAvailable, source: 'backend' };
      } catch (err) {
        logger.warn('Backend debates fetch failed, trying Supabase:', err);
        return null;
      }
    },
    [backendConfig.api],
  );

  const fetchDebatesFromSupabase = useCallback(
    async (
      limit: number,
    ): Promise<{ debates: DebateArtifact[]; hasMore: boolean; source: 'supabase' }> => {
      const data = await fetchRecentDebates(limit);
      return { debates: data, hasMore: data.length === limit, source: 'supabase' };
    },
    [],
  );

  useEffect(() => {
    async function loadDebates() {
      try {
        setLoading(true);

        // Try backend first
        const backendResult = await fetchDebatesFromBackend(PAGE_SIZE, 0);
        if (backendResult && backendResult.debates.length > 0) {
          setDebates(backendResult.debates);
          setHasMore(backendResult.hasMore);
          setDataSource('backend');
          return;
        }

        // Fall back to Supabase
        const supabaseResult = await fetchDebatesFromSupabase(PAGE_SIZE);
        setDebates(supabaseResult.debates);
        setHasMore(supabaseResult.hasMore);
        setDataSource(supabaseResult.debates.length > 0 ? 'supabase' : 'none');
      } catch (e) {
        logger.error('Failed to load debates:', e);
      } finally {
        setLoading(false);
      }
    }

    loadDebates();
  }, [fetchDebatesFromBackend, fetchDebatesFromSupabase]);

  const loadMore = async () => {
    if (loadingMore || !hasMore) return;

    try {
      setLoadingMore(true);
      const nextPage = page + 1;
      const offset = page * PAGE_SIZE;

      if (dataSource === 'backend') {
        // Fetch next page from backend API with offset
        const result = await fetchDebatesFromBackend(PAGE_SIZE, offset);
        if (result) {
          if (result.debates.length < PAGE_SIZE) {
            setHasMore(false);
          }
          setDebates((prev) => [...prev, ...result.debates]);
          setPage(nextPage);
          return;
        }
      }

      // Supabase fallback for pagination
      const data = await fetchRecentDebates(PAGE_SIZE * (nextPage + 1));
      const newDebates = data.slice(offset, offset + PAGE_SIZE);

      if (newDebates.length < PAGE_SIZE) {
        setHasMore(false);
      }

      setDebates((prev) => [...prev, ...newDebates]);
      setPage(nextPage);
    } catch (e) {
      logger.error('Failed to load more debates:', e);
    } finally {
      setLoadingMore(false);
    }
  };

  // Filter debates
  const filteredDebates = debates.filter((debate) => {
    if (filter === 'consensus') return debate.consensus_reached;
    if (filter === 'no-consensus') return !debate.consensus_reached;
    return true;
  });

  const handleCopyLink = async (debateId: string) => {
    const url = `${window.location.origin}/debates/${debateId}`;
    try {
      await navigator.clipboard.writeText(url);
      setCopiedId(debateId);
      setTimeout(() => setCopiedId(null), 2000);
    } catch (err) {
      logger.error('Failed to copy link:', err);
    }
  };

  const toggleCompareSelection = (debateId: string) => {
    setSelectedForCompare((current) => {
      if (current.includes(debateId)) {
        return current.filter((id) => id !== debateId);
      }
      if (current.length === 2) {
        return [current[1], debateId];
      }
      return [...current, debateId];
    });
  };

  const launchComparison = () => {
    if (selectedForCompare.length < 2) return;

    const params = new URLSearchParams({
      left: selectedForCompare[0],
      right: selectedForCompare[1],
    });
    router.push(`/debates/compare?${params.toString()}`);
  };

  const formatDate = (timestamp: string) => {
    return new Date(timestamp).toLocaleString();
  };

  // Group filtered debates by date
  const groupedDebates = filteredDebates.reduce(
    (acc, debate) => {
      const date = new Date(debate.created_at).toLocaleDateString();
      if (!acc[date]) acc[date] = [];
      acc[date].push(debate);
      return acc;
    },
    {} as Record<string, DebateArtifact[]>,
  );

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-[var(--bg)] text-[var(--text)] relative z-10">
        <div className="container mx-auto px-4 py-6">
          {/* Page Title & Filters */}
          <div className="mb-6">
            <div className="flex items-center justify-between flex-wrap gap-4">
              <div>
                <h1 className="text-xl font-theme-data text-[var(--acid-green)] mb-2">
                  {'>'} DEBATE ARCHIVE
                </h1>
                <p className="text-xs text-[var(--text-muted)] font-theme-data">
                  Browse, share, and compare past debates side by side
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-[var(--text-muted)] font-theme-data">Filter:</span>
                {(['all', 'consensus', 'no-consensus'] as const).map((f) => (
                  <button
                    key={f}
                    onClick={() => setFilter(f)}
                    className={`px-2 py-1 text-xs font-theme-data border transition-colors ${
                      filter === f
                        ? 'bg-[var(--acid-green)]/20 text-[var(--acid-green)] border-[var(--acid-green)]/40'
                        : 'bg-[var(--surface)] text-[var(--text-muted)] border-[var(--border)] hover:border-[var(--acid-green)]/40'
                    }`}
                  >
                    {f === 'all' ? 'ALL' : f === 'consensus' ? 'CONSENSUS' : 'NO CONSENSUS'}
                  </button>
                ))}
              </div>
            </div>
            <div className="mt-2 text-xs text-[var(--text-muted)] font-theme-data flex items-center gap-2">
              <span>
                Showing {filteredDebates.length} of {debates.length} debates
              </span>
              {dataSource !== 'none' && (
                <span
                  className="text-[10px] text-[var(--text-muted)]"
                  title={dataSource === 'backend' ? 'Fetched from API' : 'Fetched from Supabase'}
                >
                  [{dataSource === 'backend' ? 'API' : 'DB'}]
                </span>
              )}
            </div>
          </div>

          <PanelErrorBoundary panelName="Debate Archive">
            {loading && (
              <div className="flex items-center justify-center py-20">
                <div className="text-[var(--accent)] font-theme-data animate-pulse">
                  {'>'} LOADING DEBATES...
                </div>
              </div>
            )}

            {!loading && debates.length === 0 && (
              <div className="space-y-4">
                <div className="bg-surface border border-[var(--accent)]/30">
                  <DebatesEmptyState onStart={() => setShowCreateModal(true)} />
                </div>
                <button
                  onClick={() => setShowCreateModal(true)}
                  className="w-full px-4 py-3 font-theme-data text-sm bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/30 hover:bg-[var(--acid-cyan)]/20 transition-colors"
                >
                  OPEN THE LIVE DEBATE CREATOR
                </button>
              </div>
            )}

            {/* Debates by Date */}
            <div className="space-y-6">
              {selectedForCompare.length > 0 && (
                <div className="border border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/5 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <div className="text-xs font-theme-data text-[var(--acid-cyan)] mb-2">
                        {'>'} SIDE-BY-SIDE COMPARE QUEUE
                      </div>
                      <div className="flex flex-wrap items-center gap-2 text-xs font-theme-data">
                        {selectedForCompare.map((debateId, index) => (
                          <span
                            key={debateId}
                            className="border border-[var(--acid-cyan)]/30 bg-[var(--bg)] px-2 py-1 text-[var(--text)]"
                          >
                            {index === 0 ? 'A' : 'B'} {debateId.slice(0, 12)}
                          </span>
                        ))}
                        {selectedForCompare.length === 1 && (
                          <span className="text-[var(--text-muted)]">
                            Select one more debate to unlock the comparison view.
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        onClick={launchComparison}
                        disabled={selectedForCompare.length < 2}
                        className="px-3 py-2 text-xs font-theme-data bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/30 hover:bg-[var(--acid-cyan)]/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        COMPARE SELECTED
                      </button>
                      <button
                        onClick={() => setSelectedForCompare([])}
                        className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-cyan)]/40 transition-colors"
                      >
                        CLEAR
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {Object.entries(groupedDebates).map(([date, dateDebates]) => (
                <div key={date}>
                  <div className="text-xs font-theme-data text-text-muted mb-2 flex items-center gap-2">
                    <span className="text-[var(--accent)]">{'>'}</span>
                    {date}
                    <span className="text-text-muted/50">({dateDebates.length} debates)</span>
                  </div>

                  <div className="space-y-2">
                    {dateDebates.map((debate) => (
                      <div
                        key={debate.id}
                        className={`bg-surface p-4 transition-colors ${
                          selectedForCompare.includes(debate.id)
                            ? 'border-[var(--acid-cyan)]/50 border'
                            : 'border border-[var(--accent)]/30 hover:border-[var(--accent)]/50'
                        }`}
                      >
                        <div className="flex items-start justify-between gap-4">
                          <div className="flex-1 min-w-0">
                            <Link
                              href={`/debates/${debate.id}`}
                              className="text-sm font-theme-data text-[var(--accent)] hover:text-[var(--acid-cyan)] transition-colors block mb-2"
                            >
                              {debate.task}
                            </Link>

                            <div className="flex flex-wrap items-center gap-3 text-xs">
                              {/* Agents */}
                              <div className="flex items-center gap-1">
                                {debate.agents.map((agent, i) => {
                                  const colors = getAgentColors(agent);
                                  return (
                                    <span
                                      key={i}
                                      className={`px-1.5 py-0.5 ${colors.bg} ${colors.text} font-theme-data`}
                                      title={agent}
                                    >
                                      {agent.split('-')[0].toUpperCase()}
                                    </span>
                                  );
                                })}
                              </div>

                              {/* Status Badge */}
                              <span
                                className={`px-1.5 py-0.5 text-[10px] font-theme-data border ${
                                  debate.winning_proposal
                                    ? 'bg-[var(--accent)]/10 text-[var(--accent)] border-[var(--accent)]/30'
                                    : debate.consensus_reached
                                      ? 'bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)] border-[var(--acid-cyan)]/30'
                                      : 'bg-yellow-500/10 text-yellow-400 border-yellow-500/30'
                                }`}
                              >
                                {debate.winning_proposal
                                  ? 'COMPLETED'
                                  : debate.consensus_reached
                                    ? 'CONSENSUS'
                                    : 'NO CONSENSUS'}
                              </span>

                              {/* Confidence */}
                              <span className="text-text-muted">
                                {Math.round(debate.confidence * 100)}% conf
                              </span>

                              {/* Receipt indicator */}
                              {debate.vote_tally && (
                                <span
                                  className="text-[10px] font-theme-data text-[var(--accent)]"
                                  title="Has receipt"
                                >
                                  [RCV]
                                </span>
                              )}

                              {/* Phase and Cycle */}
                              <div className="text-text-muted">
                                C{debate.cycle_number} / {debate.phase}
                              </div>
                            </div>
                          </div>

                          {/* Actions */}
                          <div className="flex flex-col items-end gap-2 flex-shrink-0">
                            <button
                              onClick={() => toggleCompareSelection(debate.id)}
                              className={`px-2 py-1 text-xs font-theme-data border transition-colors ${
                                selectedForCompare.includes(debate.id)
                                  ? 'bg-[var(--acid-cyan)]/15 text-[var(--acid-cyan)] border-[var(--acid-cyan)]/40'
                                  : 'bg-[var(--surface)] text-[var(--acid-cyan)] border-[var(--acid-cyan)]/30 hover:bg-[var(--acid-cyan)]/10'
                              }`}
                            >
                              {selectedForCompare.includes(debate.id)
                                ? `REMOVE ${selectedForCompare.indexOf(debate.id) === 0 ? 'A' : 'B'}`
                                : selectedForCompare.length === 0
                                  ? 'COMPARE A'
                                  : selectedForCompare.length === 1
                                    ? 'COMPARE B'
                                    : 'REPLACE B'}
                            </button>
                            <button
                              onClick={() => handleCopyLink(debate.id)}
                              className="px-2 py-1 text-xs font-theme-data bg-[var(--accent)]/10 text-[var(--accent)] border border-[var(--accent)]/30 hover:bg-[var(--accent)] hover:text-bg transition-colors"
                            >
                              {copiedId === debate.id ? 'COPIED!' : 'SHARE'}
                            </button>
                            <span className="text-[10px] text-text-muted font-theme-data">
                              {formatDate(debate.created_at).split(',')[1]}
                            </span>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}

              {/* Load More Button */}
              {hasMore && !loading && (
                <div className="text-center py-6">
                  <button
                    onClick={loadMore}
                    disabled={loadingMore}
                    className="px-6 py-3 font-theme-data text-sm bg-surface border border-[var(--accent)]/30 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {loadingMore ? (
                      <span className="animate-pulse">LOADING MORE...</span>
                    ) : (
                      <span>LOAD MORE DEBATES</span>
                    )}
                  </button>
                  <p className="text-xs text-text-muted mt-2">
                    Page {page} • {PAGE_SIZE} debates per page
                  </p>
                </div>
              )}

              {!hasMore && debates.length > 0 && (
                <div className="text-center py-6 text-xs text-text-muted font-theme-data">
                  {'>'} END OF ARCHIVE • {debates.length} total debates
                </div>
              )}
            </div>
          </PanelErrorBoundary>
        </div>

        {/* Live Create Modal */}
        {showCreateModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
            <div className="w-full max-w-4xl max-h-[85vh] overflow-y-auto mx-4 border border-[var(--acid-green)]/30 bg-[var(--bg)] shadow-2xl">
              <div className="flex items-start justify-between gap-4 border-b border-[var(--acid-green)]/20 px-6 py-4">
                <div>
                  <h2 className="text-lg font-theme-data text-[var(--acid-green)]">
                    {'>'} LIVE DEBATE CREATOR
                  </h2>
                  <p className="mt-1 text-xs font-theme-data text-[var(--text-muted)]">
                    Start a real backend debate with auto-selected agents, a light protocol, and a
                    default $5 budget cap.
                  </p>
                </div>
                <button
                  onClick={() => setShowCreateModal(false)}
                  className="px-3 py-1.5 text-xs font-theme-data text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/40 hover:text-[var(--text)] transition-colors"
                >
                  CLOSE
                </button>
              </div>
              <div className="px-6 py-6">
                <DebateInput
                  apiBase={backendConfig.api}
                  onDebateStarted={(debateId) => {
                    setShowCreateModal(false);
                    router.push(`/debates/${debateId}`);
                  }}
                  defaultFormat="light"
                  defaultAgents=""
                  defaultRounds={4}
                  defaultBudgetLimit="5"
                  initialShowAdvanced
                  allowPlaygroundFallback={false}
                />
              </div>
            </div>
          </div>
        )}

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'═'.repeat(40)}</div>
          <p className="text-text-muted">
            {'>'} AGORA DEBATE ARCHIVE // {debates.length} DEBATES
          </p>
          <p className="text-[var(--acid-cyan)] mt-2">
            <Link href="/" className="hover:text-[var(--accent)] transition-colors">
              [ RETURN TO LIVE ]
            </Link>
          </p>
          <div className="text-[var(--accent)]/50 mt-4">{'═'.repeat(40)}</div>
        </footer>
      </main>
    </>
  );
}
