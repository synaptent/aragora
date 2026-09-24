'use client';

import Link from 'next/link';
import { useState, useEffect, useCallback } from 'react';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { useBackend } from '@/components/BackendSelector';

interface ForkNode {
  id: string;
  parent_id: string | null;
  debate_id: string;
  branch_point: number;
  modified_context?: string;
  messages_inherited: number;
  created_at: string;
  status: string;
  task?: string;
  agents?: string[];
  children_count?: number;
}

interface ForkFamily {
  root_id: string;
  root_task: string;
  root_agents: string[];
  total_forks: number;
  latest_fork_at: string;
  forks: ForkNode[];
}

export default function ForksPage() {
  const [families, setFamilies] = useState<ForkFamily[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedFamily, setExpandedFamily] = useState<string | null>(null);
  const { config: backendConfig } = useBackend();

  const fetchForkFamilies = useCallback(async () => {
    setLoading(true);
    try {
      // Fetch debates that have forks
      const res = await fetch(`${backendConfig.api}/api/debates?has_forks=true&limit=50`);
      if (!res.ok) {
        if (res.status === 503) {
          setError('Backend not available');
        } else {
          setError('Failed to load fork data');
        }
        return;
      }
      const data = await res.json();
      const debates = data.debates || [];

      // Group by root debate and fetch fork trees
      const familyMap = new Map<string, ForkFamily>();

      for (const debate of debates) {
        // Fetch fork tree for this debate
        try {
          const treeRes = await fetch(`${backendConfig.api}/api/debates/${debate.id}/fork-tree`);
          if (treeRes.ok) {
            const treeData = await treeRes.json();
            const forks = treeData.forks || treeData.nodes || [];

            if (forks.length > 0) {
              familyMap.set(debate.id, {
                root_id: debate.id,
                root_task: debate.task || 'Untitled debate',
                root_agents: debate.agents || [],
                total_forks: forks.length,
                latest_fork_at: forks[forks.length - 1]?.created_at || debate.created_at,
                forks,
              });
            }
          }
        } catch {
          // Skip debates where fork tree fetch fails
        }
      }

      setFamilies(Array.from(familyMap.values()));
      setError(null);
    } catch {
      setError('Network error loading forks');
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api]);

  useEffect(() => {
    fetchForkFamilies();
  }, [fetchForkFamilies]);

  const formatDate = (iso: string) => {
    try {
      return new Date(iso).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return iso;
    }
  };

  const toggleFamily = (rootId: string) => {
    setExpandedFamily(expandedFamily === rootId ? null : rootId);
  };

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />
      <main className="min-h-screen bg-bg text-text relative z-10">
        {/* Header */}
        <header className="border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="container mx-auto px-4 py-3 flex items-center justify-between">
            <Link href="/">
              <AsciiBannerCompact connected={true} />
            </Link>
            <div className="flex items-center gap-4">
              <Link
                href="/"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [DASHBOARD]
              </Link>
              <ThemeToggle />
            </div>
          </div>
        </header>

        {/* Content */}
        <div className="container mx-auto px-4 py-8">
          {/* Page Title */}
          <div className="mb-6">
            <h1 className="text-xl font-theme-data text-[var(--accent)] mb-2">
              {'>'} FORK EXPLORER
            </h1>
            <p className="text-sm font-theme-data text-text-muted">
              Browse counterfactual debate branches. Forks explore &quot;what if&quot; scenarios by
              branching from existing debates with modified context.
            </p>
          </div>

          {/* Error Message */}
          {error && (
            <div className="mb-6 p-4 border border-warning/30 bg-warning/10">
              <p className="text-xs font-theme-data text-warning">
                {'>'} {error}
              </p>
            </div>
          )}

          {/* Fork Families */}
          <div className="space-y-4">
            {loading ? (
              <div className="p-8 text-center border border-[var(--accent)]/30 bg-surface/50">
                <div className="w-6 h-6 border-2 border-[var(--accent)]/40 border-t-acid-green rounded-full animate-spin mx-auto" />
                <p className="mt-2 text-xs font-theme-data text-text-muted">
                  Loading fork trees...
                </p>
              </div>
            ) : families.length === 0 ? (
              <div className="p-8 text-center border border-[var(--accent)]/30 bg-surface/50">
                <p className="text-xs font-theme-data text-text-muted mb-4">
                  No forked debates found. Create your first fork from any completed debate.
                </p>
                <Link
                  href="/debates"
                  className="inline-block px-4 py-2 text-xs font-theme-data border border-[var(--accent)]/40 hover:bg-[var(--accent)]/10 transition-colors"
                >
                  [BROWSE DEBATES]
                </Link>
              </div>
            ) : (
              families.map((family) => (
                <div
                  key={family.root_id}
                  className="border border-[var(--accent)]/30 bg-surface/50"
                >
                  {/* Family Header */}
                  <button
                    onClick={() => toggleFamily(family.root_id)}
                    className="w-full px-4 py-3 text-left hover:bg-[var(--accent)]/5 transition-colors"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-theme-data text-[var(--accent)]">
                            {expandedFamily === family.root_id ? '▼' : '▶'}
                          </span>
                          <span className="text-sm font-theme-data text-text truncate">
                            {family.root_task}
                          </span>
                        </div>
                        <div className="mt-1 ml-4 flex items-center gap-3 text-xs font-theme-data text-text-muted">
                          <span>
                            {family.total_forks} fork{family.total_forks !== 1 ? 's' : ''}
                          </span>
                          <span>Latest: {formatDate(family.latest_fork_at)}</span>
                        </div>
                        {family.root_agents.length > 0 && (
                          <div className="mt-1 ml-4 text-xs font-theme-data text-[var(--acid-cyan)]">
                            {family.root_agents.slice(0, 3).join(' vs ')}
                          </div>
                        )}
                      </div>
                      <Link
                        href={`/debate/${family.root_id}`}
                        onClick={(e) => e.stopPropagation()}
                        className="px-2 py-1 text-xs font-theme-data border border-[var(--accent)]/40 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors"
                      >
                        [VIEW ROOT]
                      </Link>
                    </div>
                  </button>

                  {/* Expanded Fork Tree */}
                  {expandedFamily === family.root_id && (
                    <div className="border-t border-[var(--accent)]/20 p-4">
                      <div className="space-y-2">
                        {/* Root node */}
                        <div className="flex items-center gap-2 text-xs font-theme-data">
                          <span className="text-[var(--accent)]">●</span>
                          <span className="text-text">
                            ROOT: {family.root_task.substring(0, 50)}...
                          </span>
                          <Link
                            href={`/debate/${family.root_id}`}
                            className="ml-auto text-[var(--acid-cyan)] hover:underline"
                          >
                            [open]
                          </Link>
                        </div>

                        {/* Fork nodes */}
                        {family.forks.map((fork) => (
                          <div
                            key={fork.id}
                            className="ml-4 flex items-start gap-2 text-xs font-theme-data border-l border-[var(--accent)]/30 pl-4"
                          >
                            <span className="text-[var(--acid-cyan)] mt-0.5">├─</span>
                            <div className="flex-1">
                              <div className="flex items-center gap-2">
                                <span className="text-text-muted">
                                  Branch @ round {fork.branch_point}
                                </span>
                                <span
                                  className={`px-1 py-0.5 text-[10px] border ${
                                    fork.status === 'completed'
                                      ? 'border-[var(--accent)]/50 text-[var(--accent)]'
                                      : fork.status === 'running'
                                        ? 'border-[var(--acid-cyan)]/50 text-[var(--acid-cyan)]'
                                        : 'border-text-muted/50 text-text-muted'
                                  }`}
                                >
                                  {fork.status}
                                </span>
                              </div>
                              {fork.modified_context && (
                                <div className="mt-1 text-text-muted italic">
                                  &quot;{fork.modified_context.substring(0, 60)}...&quot;
                                </div>
                              )}
                              <div className="mt-1 text-text-muted">
                                {fork.messages_inherited} messages inherited •{' '}
                                {formatDate(fork.created_at)}
                              </div>
                            </div>
                            <Link
                              href={`/debate/${fork.debate_id}`}
                              className="text-[var(--acid-cyan)] hover:underline whitespace-nowrap"
                            >
                              [open fork]
                            </Link>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>

          {/* Help Section */}
          <div className="mt-8">
            <details className="group">
              <summary className="text-xs font-theme-data text-text-muted cursor-pointer hover:text-[var(--accent)]">
                [?] FORK EXPLORER GUIDE
              </summary>
              <div className="mt-4 p-4 bg-surface/50 border border-[var(--accent)]/20 text-xs font-theme-data text-text-muted space-y-4">
                <div>
                  <div className="text-[var(--accent)] mb-1">WHAT ARE FORKS?</div>
                  <p>
                    Forks are counterfactual branches of debates. They let you explore &quot;what
                    if&quot; scenarios by taking a debate at a specific point and continuing with
                    modified context or different assumptions.
                  </p>
                </div>
                <div>
                  <div className="text-[var(--accent)] mb-1">BRANCH POINTS</div>
                  <p>
                    Each fork has a branch point - the round number where it diverges from the
                    original debate. All messages before the branch point are inherited.
                  </p>
                </div>
                <div>
                  <div className="text-[var(--accent)] mb-1">MODIFIED CONTEXT</div>
                  <p>
                    When creating a fork, you can provide modified context that changes the premise
                    or constraints. This lets agents explore alternative scenarios.
                  </p>
                </div>
                <div>
                  <div className="text-[var(--accent)] mb-1">USE CASES</div>
                  <ul className="list-disc list-inside space-y-1">
                    <li>Test different assumptions in a debate</li>
                    <li>Explore what happens with different constraints</li>
                    <li>Compare outcomes with modified initial conditions</li>
                    <li>Deep-dive into specific crux points</li>
                  </ul>
                </div>
              </div>
            </details>
          </div>
        </div>
      </main>
    </>
  );
}
