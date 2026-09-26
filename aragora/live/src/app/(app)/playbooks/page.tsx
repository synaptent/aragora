'use client';

import { useState, useMemo, useCallback } from 'react';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { PlaybookCard, PlaybookDetailModal } from '@/components/PlaybookCard';
import { usePlaybooks, type Playbook } from '@/hooks/usePlaybooks';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ALL_CATEGORIES = [
  'all',
  'healthcare',
  'finance',
  'legal',
  'compliance',
  'engineering',
  'general',
] as const;
type CategoryFilter = (typeof ALL_CATEGORIES)[number];

const CATEGORY_LABELS: Record<CategoryFilter, string> = {
  all: 'ALL',
  healthcare: 'HEALTHCARE',
  finance: 'FINANCE',
  legal: 'LEGAL',
  compliance: 'COMPLIANCE',
  engineering: 'ENGINEERING',
  general: 'GENERAL',
};

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function PlaybooksPage() {
  const {
    playbooks,
    selectedPlaybook,
    setSelectedPlaybook,
    runPlaybook,
    launching,
    loading,
    error,
    launchError,
  } = usePlaybooks();

  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [launchSuccess, setLaunchSuccess] = useState<string | null>(null);

  // Filter playbooks by category and search query
  const filteredPlaybooks = useMemo(() => {
    let result = playbooks;

    if (categoryFilter !== 'all') {
      result = result.filter((p) => p.category === categoryFilter);
    }

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter(
        (p) =>
          p.name.toLowerCase().includes(q) ||
          p.description.toLowerCase().includes(q) ||
          p.tags.some((t) => t.toLowerCase().includes(q)),
      );
    }

    return result;
  }, [playbooks, categoryFilter, searchQuery]);

  // Count playbooks per category for badge display
  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = { all: playbooks.length };
    for (const p of playbooks) {
      counts[p.category] = (counts[p.category] || 0) + 1;
    }
    return counts;
  }, [playbooks]);

  const handleLaunch = useCallback(
    (playbook: Playbook) => {
      setSelectedPlaybook(playbook);
      setLaunchSuccess(null);
    },
    [setSelectedPlaybook],
  );

  const handleRun = useCallback(
    async (input: string) => {
      if (!selectedPlaybook) return;
      const result = await runPlaybook(selectedPlaybook.id, input);
      if (result) {
        setLaunchSuccess(result.run_id);
        // Close modal after a short delay to show success
        setTimeout(() => {
          setSelectedPlaybook(null);
          setLaunchSuccess(null);
        }, 2000);
      }
    },
    [selectedPlaybook, runPlaybook, setSelectedPlaybook],
  );

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-[var(--bg)] text-[var(--text)] relative z-10">
        {/* Hero */}
        <div className="border-b border-[var(--acid-green)]/20 bg-[var(--surface)]/30">
          <div className="container mx-auto px-4 py-12 text-center">
            <h1 className="text-3xl md:text-4xl font-theme-data text-[var(--acid-green)] mb-4">
              {'>'} DECISION PLAYBOOKS
            </h1>
            <p className="text-[var(--text-muted)] font-theme-data max-w-2xl mx-auto">
              Pre-built decision workflows combining debate templates, vertical scoring, compliance
              artifacts, and approval gates. Choose a playbook and launch it with your question.
            </p>
          </div>
        </div>

        <div className="container mx-auto px-4 py-6">
          {/* Filters bar */}
          <div className="mb-6">
            <div className="flex items-center justify-between flex-wrap gap-4">
              {/* Category filters */}
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs text-[var(--text-muted)] font-theme-data">Filter:</span>
                {ALL_CATEGORIES.map((cat) => (
                  <button
                    key={cat}
                    onClick={() => setCategoryFilter(cat)}
                    className={`px-2 py-1 text-xs font-theme-data border transition-colors ${
                      categoryFilter === cat
                        ? 'bg-[var(--acid-green)]/20 text-[var(--acid-green)] border-[var(--acid-green)]/40'
                        : 'bg-[var(--surface)] text-[var(--text-muted)] border-[var(--border)] hover:border-[var(--acid-green)]/40'
                    }`}
                  >
                    {CATEGORY_LABELS[cat]}
                    {(categoryCounts[cat] ?? 0) > 0 && (
                      <span className="ml-1 opacity-60">({categoryCounts[cat]})</span>
                    )}
                  </button>
                ))}
              </div>

              {/* Search */}
              <div className="relative">
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search playbooks..."
                  className="w-60 bg-[var(--surface)] border border-[var(--border)] px-3 py-1.5 text-xs font-theme-data text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--acid-green)]/50"
                />
                {searchQuery && (
                  <button
                    onClick={() => setSearchQuery('')}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-muted)] hover:text-[var(--text)] font-theme-data text-xs"
                  >
                    &times;
                  </button>
                )}
              </div>
            </div>

            <div className="mt-2 text-xs text-[var(--text-muted)] font-theme-data">
              Showing {filteredPlaybooks.length} of {playbooks.length} playbooks
            </div>
          </div>

          {/* Loading state */}
          {loading && (
            <div className="flex items-center justify-center py-20">
              <div className="text-[var(--acid-green)] font-theme-data animate-pulse">
                {'>'} LOADING PLAYBOOKS...
              </div>
            </div>
          )}

          {/* Error state */}
          {error && !loading && (
            <div className="bg-red-500/10 border border-red-500/30 p-4 mb-6">
              <p className="text-sm font-theme-data text-red-400">
                Failed to load playbooks: {error}
              </p>
            </div>
          )}

          {/* Empty state */}
          {!loading && !error && filteredPlaybooks.length === 0 && (
            <div className="flex flex-col items-center justify-center py-20">
              <div className="text-[var(--acid-green)] font-theme-data text-lg mb-2">
                {'>'} NO PLAYBOOKS FOUND
              </div>
              <p className="text-xs text-[var(--text-muted)] font-theme-data">
                {searchQuery
                  ? 'Try a different search term or clear the filter.'
                  : 'No playbooks match the selected category.'}
              </p>
              {(searchQuery || categoryFilter !== 'all') && (
                <button
                  onClick={() => {
                    setSearchQuery('');
                    setCategoryFilter('all');
                  }}
                  className="mt-4 px-4 py-2 text-xs font-theme-data bg-[var(--surface)] border border-[var(--acid-green)]/30 text-[var(--acid-green)] hover:bg-[var(--acid-green)]/10 transition-colors"
                >
                  CLEAR FILTERS
                </button>
              )}
            </div>
          )}

          {/* Playbook grid */}
          {!loading && filteredPlaybooks.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {filteredPlaybooks.map((playbook) => (
                <PlaybookCard key={playbook.id} playbook={playbook} onLaunch={handleLaunch} />
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--acid-green)]/20 mt-8">
          <div className="text-[var(--acid-green)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-[var(--text-muted)]">
            {'>'} ARAGORA DECISION PLAYBOOKS // {playbooks.length} AVAILABLE
          </p>
          <div className="text-[var(--acid-green)]/50 mt-4">{'='.repeat(40)}</div>
        </footer>
      </main>

      {/* Detail / launch modal */}
      {selectedPlaybook && (
        <PlaybookDetailModal
          playbook={selectedPlaybook}
          onClose={() => {
            setSelectedPlaybook(null);
            setLaunchSuccess(null);
          }}
          onRun={handleRun}
          launching={launching}
          launchError={launchSuccess ? null : launchError}
        />
      )}

      {/* Success toast */}
      {launchSuccess && (
        <div className="fixed bottom-6 right-6 z-50 bg-emerald-500/20 border border-emerald-500/40 px-4 py-3 text-sm font-theme-data text-emerald-400 animate-pulse">
          Playbook launched! Run ID: {launchSuccess}
        </div>
      )}
    </>
  );
}
