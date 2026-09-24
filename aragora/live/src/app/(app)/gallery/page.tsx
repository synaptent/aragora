'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { getClient, GalleryEntry } from '@/lib/aragora-client';
import { logger } from '@/utils/logger';

// Use GalleryEntry from SDK
type GalleryDebate = GalleryEntry;

export default function GalleryPage() {
  const [debates, setDebates] = useState<GalleryDebate[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<'all' | 'featured' | 'popular'>('featured');
  const [searchQuery, setSearchQuery] = useState('');
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(true);

  const loadDebates = useCallback(
    async (targetPage: number, reset = false) => {
      setLoading(true);
      try {
        const client = getClient();
        const params: Record<string, string | number> = {
          limit: 12,
          offset: reset ? 0 : targetPage * 12,
        };

        if (filter === 'featured') params.featured = 'true';
        if (filter === 'popular') params.sort = 'popular';
        if (searchQuery) params.search = searchQuery;

        const response = await client.gallery.list(params);
        const newDebates = response.entries || [];

        if (reset) {
          setDebates(newDebates);
          setPage(0);
        } else {
          setDebates((prev) => [...prev, ...newDebates]);
          setPage(targetPage);
        }
        setHasMore(newDebates.length === 12);
      } catch (err) {
        logger.error('Failed to load gallery:', err);
      } finally {
        setLoading(false);
      }
    },
    [filter, searchQuery],
  );

  useEffect(() => {
    loadDebates(0, true);
  }, [filter, searchQuery, loadDebates]);

  const handleLoadMore = () => {
    loadDebates(page + 1, false);
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  };

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        {/* Hero Section */}
        <div className="border-b border-[var(--accent)]/20 bg-surface/30">
          <div className="container mx-auto px-4 py-12 text-center">
            <h1 className="text-3xl md:text-4xl font-theme-data text-[var(--accent)] mb-4">
              {'>'} PUBLIC GALLERY
            </h1>
            <p className="text-text-muted font-theme-data max-w-2xl mx-auto">
              Notable debates showcasing multi-agent reasoning. Browse featured discussions,
              discover consensus patterns, and learn from AI adversarial analysis.
            </p>
          </div>
        </div>

        {/* Filters */}
        <div className="container mx-auto px-4 py-6">
          <div className="flex flex-col md:flex-row gap-4 items-start md:items-center justify-between mb-8">
            {/* Filter Tabs */}
            <div className="flex gap-2">
              {(['featured', 'popular', 'all'] as const).map((f) => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={`px-4 py-2 text-xs font-theme-data border transition-colors ${
                    filter === f
                      ? 'border-[var(--accent)] bg-[var(--accent)]/20 text-[var(--accent)]'
                      : 'border-[var(--accent)]/30 text-text-muted hover:border-[var(--accent)]/60'
                  }`}
                >
                  [{f.toUpperCase()}]
                </button>
              ))}
            </div>

            {/* Search */}
            <div className="relative w-full md:w-80">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search topics..."
                className="w-full px-4 py-2 text-sm font-theme-data bg-surface border border-[var(--accent)]/30
                         text-text placeholder-text-muted/50 focus:border-[var(--accent)] focus:outline-none"
              />
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted text-xs">
                [/]
              </span>
            </div>
          </div>

          {/* Debate Grid */}
          {loading && debates.length === 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {[...Array(6)].map((_, i) => (
                <div key={i} className="card p-6 animate-pulse">
                  <div className="h-4 bg-surface rounded w-3/4 mb-4" />
                  <div className="h-3 bg-surface rounded w-full mb-2" />
                  <div className="h-3 bg-surface rounded w-2/3" />
                </div>
              ))}
            </div>
          ) : debates.length === 0 ? (
            <div className="text-center py-12">
              <p className="text-text-muted font-theme-data">No debates found</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {debates.map((debate) => (
                <Link
                  key={debate.id}
                  href={`/debate/${debate.id}`}
                  className="card p-6 hover:border-[var(--accent)]/60 transition-colors group"
                >
                  {/* Featured Badge */}
                  {debate.featured && (
                    <div className="text-xs font-theme-data text-[var(--acid-cyan)] mb-2">
                      [FEATURED]
                    </div>
                  )}

                  {/* Topic */}
                  <h3 className="font-theme-data text-[var(--accent)] group-hover:text-[var(--acid-cyan)] transition-colors mb-3 line-clamp-2">
                    {debate.title}
                  </h3>

                  {/* Summary */}
                  {debate.summary && (
                    <p className="text-sm text-text-muted font-theme-data mb-4 line-clamp-3">
                      {debate.summary}
                    </p>
                  )}

                  {/* Agents */}
                  <div className="flex flex-wrap gap-2 mb-4">
                    {debate.agents.slice(0, 3).map((agent) => (
                      <span
                        key={agent}
                        className="px-2 py-1 text-xs font-theme-data bg-surface border border-[var(--accent)]/20 text-text-muted"
                      >
                        {agent}
                      </span>
                    ))}
                    {debate.agents.length > 3 && (
                      <span className="px-2 py-1 text-xs font-theme-data text-text-muted">
                        +{debate.agents.length - 3}
                      </span>
                    )}
                  </div>

                  {/* Consensus */}
                  {debate.consensus_reached && (
                    <div className="text-xs font-theme-data text-[var(--accent)]/80 mb-4 p-2 bg-[var(--accent)]/5 border-l-2 border-[var(--accent)]">
                      [CONSENSUS REACHED]
                    </div>
                  )}

                  {/* Meta */}
                  <div className="flex items-center justify-between text-xs font-theme-data text-text-muted">
                    <span>{formatDate(debate.created_at)}</span>
                    <span>{debate.views || 0} views</span>
                  </div>
                </Link>
              ))}
            </div>
          )}

          {/* Load More */}
          {hasMore && debates.length > 0 && (
            <div className="text-center mt-8">
              <button
                onClick={handleLoadMore}
                disabled={loading}
                className="px-6 py-3 text-sm font-theme-data border border-[var(--accent)]/30
                         text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors disabled:opacity-50"
              >
                {loading ? '[LOADING...]' : '[LOAD MORE]'}
              </button>
            </div>
          )}
        </div>
      </main>
    </>
  );
}
