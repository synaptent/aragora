'use client';

import { useState, useCallback, useEffect } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useBackend } from '@/components/BackendSelector';
import { MomentsEmptyState } from '@/components/ui/EmptyState';
import { logger } from '@/utils/logger';

interface Moment {
  id: string;
  type: string;
  agent: string;
  description: string;
  significance: number;
  debate_id: string;
  other_agents: string[];
  metadata: Record<string, unknown>;
  created_at?: string;
}

interface MomentsSummary {
  total_moments: number;
  by_type: Record<string, number>;
  by_agent: Record<string, number>;
  most_significant?: Moment;
  recent: Moment[];
}

const MOMENT_TYPES = [
  {
    id: 'upset_victory',
    label: 'Upset Victory',
    color: 'text-warning',
    description: 'Underdog wins against favorite',
  },
  {
    id: 'position_reversal',
    label: 'Position Reversal',
    color: 'text-acid-purple',
    description: 'Agent changes stance significantly',
  },
  {
    id: 'calibration_vindication',
    label: 'Calibration Vindication',
    color: 'text-[var(--accent)]',
    description: "Agent's confidence proven accurate",
  },
  {
    id: 'alliance_shift',
    label: 'Alliance Shift',
    color: 'text-[var(--acid-cyan)]',
    description: 'Unexpected coalition change',
  },
  {
    id: 'consensus_breakthrough',
    label: 'Consensus Breakthrough',
    color: 'text-[var(--accent)]',
    description: 'Multiple agents reach agreement',
  },
  {
    id: 'streak_achievement',
    label: 'Streak Achievement',
    color: 'text-warning',
    description: 'Consecutive wins or performance',
  },
  {
    id: 'domain_mastery',
    label: 'Domain Mastery',
    color: 'text-[var(--acid-cyan)]',
    description: 'Excellence in specific topic area',
  },
];

function getMomentTypeConfig(type: string) {
  return (
    MOMENT_TYPES.find((t) => t.id === type) || {
      id: type,
      label: type,
      color: 'text-text',
      description: '',
    }
  );
}

function SignificanceBadge({ score }: { score: number }) {
  const color =
    score >= 0.8
      ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
      : score >= 0.6
        ? 'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)]'
        : score >= 0.4
          ? 'bg-warning/20 text-warning'
          : 'bg-text-muted/20 text-text-muted';
  return (
    <span className={`px-2 py-0.5 text-xs font-theme-data rounded ${color}`}>
      {(score * 100).toFixed(0)}%
    </span>
  );
}

export default function MomentsPage() {
  const { config: backendConfig } = useBackend();
  const [activeTab, setActiveTab] = useState<'timeline' | 'trending' | 'summary' | 'types'>(
    'timeline',
  );

  // Summary state
  const [summary, setSummary] = useState<MomentsSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);

  // Timeline state
  const [moments, setMoments] = useState<Moment[]>([]);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [timelinePage, setTimelinePage] = useState(0);
  const [timelineTotal, setTimelineTotal] = useState(0);

  // Trending state
  const [trending, setTrending] = useState<Moment[]>([]);
  const [trendingLoading, setTrendingLoading] = useState(false);

  // Type filter state
  const [selectedType, setSelectedType] = useState<string>('');
  const [typeMoments, setTypeMoments] = useState<Moment[]>([]);
  const [typeLoading, setTypeLoading] = useState(false);

  // Fetch summary
  const fetchSummary = useCallback(async () => {
    setSummaryLoading(true);
    try {
      const res = await fetch(`${backendConfig.api}/api/moments/summary`);
      if (res.ok) {
        const data = await res.json();
        setSummary(data);
      }
    } catch (err) {
      logger.error('Failed to fetch summary:', err);
    } finally {
      setSummaryLoading(false);
    }
  }, [backendConfig.api]);

  // Fetch timeline
  const fetchTimeline = useCallback(async () => {
    setTimelineLoading(true);
    try {
      const res = await fetch(
        `${backendConfig.api}/api/moments/timeline?limit=20&offset=${timelinePage * 20}`,
      );
      if (res.ok) {
        const data = await res.json();
        setMoments(data.moments || []);
        setTimelineTotal(data.total || 0);
      }
    } catch (err) {
      logger.error('Failed to fetch timeline:', err);
    } finally {
      setTimelineLoading(false);
    }
  }, [backendConfig.api, timelinePage]);

  // Fetch trending
  const fetchTrending = useCallback(async () => {
    setTrendingLoading(true);
    try {
      const res = await fetch(`${backendConfig.api}/api/moments/trending?limit=10`);
      if (res.ok) {
        const data = await res.json();
        setTrending(data.trending || []);
      }
    } catch (err) {
      logger.error('Failed to fetch trending:', err);
    } finally {
      setTrendingLoading(false);
    }
  }, [backendConfig.api]);

  // Fetch by type
  const fetchByType = useCallback(
    async (type: string) => {
      if (!type) return;
      setTypeLoading(true);
      try {
        const res = await fetch(`${backendConfig.api}/api/moments/by-type/${type}?limit=50`);
        if (res.ok) {
          const data = await res.json();
          setTypeMoments(data.moments || []);
        }
      } catch (err) {
        logger.error('Failed to fetch by type:', err);
      } finally {
        setTypeLoading(false);
      }
    },
    [backendConfig.api],
  );

  // Load data when tab changes
  useEffect(() => {
    if (activeTab === 'summary') {
      fetchSummary();
    } else if (activeTab === 'timeline') {
      fetchTimeline();
    } else if (activeTab === 'trending') {
      fetchTrending();
    }
  }, [activeTab, fetchSummary, fetchTimeline, fetchTrending]);

  // Load type data when selected
  useEffect(() => {
    if (selectedType && activeTab === 'types') {
      fetchByType(selectedType);
    }
  }, [selectedType, activeTab, fetchByType]);

  const renderMomentCard = (moment: Moment) => {
    const typeConfig = getMomentTypeConfig(moment.type);
    return (
      <div
        key={moment.id}
        className="p-4 border border-[var(--accent)]/20 rounded bg-surface/30 hover:border-[var(--accent)]/40 transition-colors"
      >
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-2">
              <span
                className={`text-xs font-theme-data px-2 py-0.5 rounded bg-surface ${typeConfig.color}`}
              >
                {typeConfig.label}
              </span>
              <SignificanceBadge score={moment.significance} />
            </div>
            <p className="font-theme-data text-sm text-text mb-2">{moment.description}</p>
            <div className="flex items-center gap-3 text-xs font-theme-data text-text-muted">
              <span>Agent: {moment.agent}</span>
              {moment.other_agents?.length > 0 && (
                <>
                  <span>|</span>
                  <span>With: {moment.other_agents.join(', ')}</span>
                </>
              )}
              {moment.created_at && (
                <>
                  <span>|</span>
                  <span>{new Date(moment.created_at).toLocaleString()}</span>
                </>
              )}
            </div>
          </div>
          {moment.debate_id && (
            <Link
              href={`/debate/${moment.debate_id}`}
              className="px-3 py-1 text-xs font-theme-data border border-[var(--accent)]/30 text-text-muted hover:text-[var(--accent)] transition-colors flex-shrink-0"
            >
              [VIEW]
            </Link>
          )}
        </div>
      </div>
    );
  };

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        <div className="container mx-auto px-4 py-6">
          {/* Title */}
          <div className="mb-6">
            <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">{'>'} MOMENTS</h1>
            <p className="text-text-muted font-theme-data text-sm">
              Significant events and achievements across all debates and agents.
            </p>
          </div>

          {/* Tab Navigation */}
          <div className="flex gap-2 mb-6">
            <button
              onClick={() => setActiveTab('timeline')}
              className={`px-4 py-2 font-theme-data text-sm border transition-colors ${
                activeTab === 'timeline'
                  ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]'
                  : 'border-[var(--accent)]/30 text-text-muted hover:text-text'
              }`}
            >
              [TIMELINE]
            </button>
            <button
              onClick={() => setActiveTab('trending')}
              className={`px-4 py-2 font-theme-data text-sm border transition-colors ${
                activeTab === 'trending'
                  ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]'
                  : 'border-[var(--accent)]/30 text-text-muted hover:text-text'
              }`}
            >
              [TRENDING]
            </button>
            <button
              onClick={() => setActiveTab('summary')}
              className={`px-4 py-2 font-theme-data text-sm border transition-colors ${
                activeTab === 'summary'
                  ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]'
                  : 'border-[var(--accent)]/30 text-text-muted hover:text-text'
              }`}
            >
              [SUMMARY]
            </button>
            <button
              onClick={() => setActiveTab('types')}
              className={`px-4 py-2 font-theme-data text-sm border transition-colors ${
                activeTab === 'types'
                  ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]'
                  : 'border-[var(--accent)]/30 text-text-muted hover:text-text'
              }`}
            >
              [BY TYPE]
            </button>
          </div>

          {/* Timeline Tab */}
          {activeTab === 'timeline' && (
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <h2 className="font-theme-data text-text">Moment Timeline</h2>
                <button
                  onClick={fetchTimeline}
                  disabled={timelineLoading}
                  className="px-3 py-1 text-xs font-theme-data border border-[var(--accent)]/30 text-text-muted hover:text-[var(--accent)] transition-colors disabled:opacity-50"
                >
                  {timelineLoading ? '[LOADING...]' : '[REFRESH]'}
                </button>
              </div>

              {/* Timeline visualization */}
              <div className="relative">
                <div className="absolute left-4 top-0 bottom-0 w-px bg-[var(--accent)]/30" />

                {timelineLoading ? (
                  <div className="text-center py-8 text-[var(--accent)] font-theme-data animate-pulse ml-8">
                    Loading timeline...
                  </div>
                ) : moments.length === 0 ? (
                  <div className="ml-8">
                    <MomentsEmptyState onViewDebates={() => (window.location.href = '/debates')} />
                  </div>
                ) : (
                  <div className="space-y-4 ml-8">
                    {moments.map((moment, index) => (
                      <div key={moment.id} className="relative">
                        {/* Timeline dot */}
                        <div className="absolute -left-8 top-4 w-2 h-2 rounded-full bg-[var(--accent)]" />
                        {/* Date marker */}
                        {(index === 0 ||
                          (moment.created_at &&
                            moments[index - 1]?.created_at &&
                            new Date(moment.created_at).toDateString() !==
                              new Date(moments[index - 1].created_at!).toDateString())) && (
                          <div className="text-xs font-theme-data text-[var(--acid-cyan)] mb-2 -ml-4">
                            {moment.created_at
                              ? new Date(moment.created_at).toLocaleDateString()
                              : 'Unknown date'}
                          </div>
                        )}
                        {renderMomentCard(moment)}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Pagination */}
              {timelineTotal > 20 && (
                <div className="flex items-center justify-between pt-4 border-t border-[var(--accent)]/20">
                  <div className="text-xs font-theme-data text-text-muted">
                    Showing {timelinePage * 20 + 1} -{' '}
                    {Math.min((timelinePage + 1) * 20, timelineTotal)} of {timelineTotal}
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setTimelinePage(Math.max(0, timelinePage - 1))}
                      disabled={timelinePage === 0}
                      className="px-3 py-1 text-xs font-theme-data border border-[var(--accent)]/30 rounded hover:border-[var(--accent)]/50 disabled:opacity-50"
                    >
                      [PREV]
                    </button>
                    <button
                      onClick={() => setTimelinePage(timelinePage + 1)}
                      disabled={(timelinePage + 1) * 20 >= timelineTotal}
                      className="px-3 py-1 text-xs font-theme-data border border-[var(--accent)]/30 rounded hover:border-[var(--accent)]/50 disabled:opacity-50"
                    >
                      [NEXT]
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Trending Tab */}
          {activeTab === 'trending' && (
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <h2 className="font-theme-data text-text">Trending Moments</h2>
                <button
                  onClick={fetchTrending}
                  disabled={trendingLoading}
                  className="px-3 py-1 text-xs font-theme-data border border-[var(--accent)]/30 text-text-muted hover:text-[var(--accent)] transition-colors disabled:opacity-50"
                >
                  {trendingLoading ? '[LOADING...]' : '[REFRESH]'}
                </button>
              </div>

              <p className="text-text-muted font-theme-data text-xs">
                Most significant moments ranked by importance score.
              </p>

              {trendingLoading ? (
                <div className="text-center py-8 text-[var(--accent)] font-theme-data animate-pulse">
                  Loading trending...
                </div>
              ) : trending.length === 0 ? (
                <div className="p-8 border border-[var(--accent)]/20 rounded text-center">
                  <p className="font-theme-data text-text-muted">No trending moments yet.</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {trending.map((moment, index) => (
                    <div key={moment.id} className="flex items-start gap-4">
                      <div className="w-8 h-8 flex items-center justify-center bg-surface rounded font-theme-data text-lg text-[var(--accent)] border border-[var(--accent)]/30">
                        {index + 1}
                      </div>
                      <div className="flex-1">{renderMomentCard(moment)}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Summary Tab */}
          {activeTab === 'summary' && (
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <h2 className="font-theme-data text-text">Moments Summary</h2>
                <button
                  onClick={fetchSummary}
                  disabled={summaryLoading}
                  className="px-3 py-1 text-xs font-theme-data border border-[var(--accent)]/30 text-text-muted hover:text-[var(--accent)] transition-colors disabled:opacity-50"
                >
                  {summaryLoading ? '[LOADING...]' : '[REFRESH]'}
                </button>
              </div>

              {summaryLoading ? (
                <div className="text-center py-8 text-[var(--accent)] font-theme-data animate-pulse">
                  Loading summary...
                </div>
              ) : !summary ? (
                <div className="p-8 border border-[var(--accent)]/20 rounded text-center">
                  <p className="font-theme-data text-text-muted">No summary data available.</p>
                </div>
              ) : (
                <>
                  {/* Stats cards */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="p-4 border border-[var(--accent)]/30 rounded bg-surface/30 text-center">
                      <div className="text-2xl font-theme-data text-[var(--accent)]">
                        {summary.total_moments}
                      </div>
                      <div className="text-xs font-theme-data text-text-muted">Total Moments</div>
                    </div>
                    <div className="p-4 border border-[var(--accent)]/30 rounded bg-surface/30 text-center">
                      <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">
                        {Object.keys(summary.by_type).length}
                      </div>
                      <div className="text-xs font-theme-data text-text-muted">Moment Types</div>
                    </div>
                    <div className="p-4 border border-[var(--accent)]/30 rounded bg-surface/30 text-center">
                      <div className="text-2xl font-theme-data text-text">
                        {Object.keys(summary.by_agent).length}
                      </div>
                      <div className="text-xs font-theme-data text-text-muted">Agents</div>
                    </div>
                    <div className="p-4 border border-[var(--accent)]/30 rounded bg-surface/30 text-center">
                      <div className="text-2xl font-theme-data text-warning">
                        {summary.most_significant
                          ? `${(summary.most_significant.significance * 100).toFixed(0)}%`
                          : 'N/A'}
                      </div>
                      <div className="text-xs font-theme-data text-text-muted">
                        Top Significance
                      </div>
                    </div>
                  </div>

                  {/* By Type */}
                  <div className="p-4 border border-[var(--accent)]/20 rounded bg-surface/30">
                    <h3 className="font-theme-data text-[var(--acid-cyan)] text-sm mb-3">
                      By Type
                    </h3>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                      {Object.entries(summary.by_type).map(([type, count]) => {
                        const typeConfig = getMomentTypeConfig(type);
                        return (
                          <div
                            key={type}
                            className="flex items-center justify-between p-2 bg-bg/50 rounded"
                          >
                            <span className={`text-xs font-theme-data ${typeConfig.color}`}>
                              {typeConfig.label}
                            </span>
                            <span className="text-xs font-theme-data text-text">{count}</span>
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  {/* By Agent */}
                  <div className="p-4 border border-[var(--accent)]/20 rounded bg-surface/30">
                    <h3 className="font-theme-data text-[var(--acid-cyan)] text-sm mb-3">
                      By Agent
                    </h3>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                      {Object.entries(summary.by_agent)
                        .sort(([, a], [, b]) => b - a)
                        .map(([agent, count]) => (
                          <div
                            key={agent}
                            className="flex items-center justify-between p-2 bg-bg/50 rounded"
                          >
                            <span className="text-xs font-theme-data text-text">{agent}</span>
                            <span className="text-xs font-theme-data text-[var(--accent)]">
                              {count}
                            </span>
                          </div>
                        ))}
                    </div>
                  </div>

                  {/* Most Significant */}
                  {summary.most_significant && (
                    <div className="p-4 border border-[var(--accent)]/20 rounded bg-surface/30">
                      <h3 className="font-theme-data text-[var(--acid-cyan)] text-sm mb-3">
                        Most Significant Moment
                      </h3>
                      {renderMomentCard(summary.most_significant)}
                    </div>
                  )}

                  {/* Recent */}
                  {summary.recent.length > 0 && (
                    <div className="p-4 border border-[var(--accent)]/20 rounded bg-surface/30">
                      <h3 className="font-theme-data text-[var(--acid-cyan)] text-sm mb-3">
                        Recent Moments
                      </h3>
                      <div className="space-y-2">
                        {summary.recent.map((moment) => renderMomentCard(moment))}
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {/* By Type Tab */}
          {activeTab === 'types' && (
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <h2 className="font-theme-data text-text">Filter by Type</h2>
                {selectedType && (
                  <button
                    onClick={() => fetchByType(selectedType)}
                    disabled={typeLoading}
                    className="px-3 py-1 text-xs font-theme-data border border-[var(--accent)]/30 text-text-muted hover:text-[var(--accent)] transition-colors disabled:opacity-50"
                  >
                    {typeLoading ? '[LOADING...]' : '[REFRESH]'}
                  </button>
                )}
              </div>

              {/* Type selector */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                {MOMENT_TYPES.map((type) => (
                  <button
                    key={type.id}
                    onClick={() => setSelectedType(type.id)}
                    className={`p-3 border rounded text-left transition-colors ${
                      selectedType === type.id
                        ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                        : 'border-[var(--accent)]/20 hover:border-[var(--accent)]/40'
                    }`}
                  >
                    <div className={`font-theme-data text-sm ${type.color}`}>{type.label}</div>
                    <div className="font-theme-data text-xs text-text-muted mt-1">
                      {type.description}
                    </div>
                  </button>
                ))}
              </div>

              {/* Results */}
              {selectedType && (
                <>
                  {typeLoading ? (
                    <div className="text-center py-8 text-[var(--accent)] font-theme-data animate-pulse">
                      Loading {getMomentTypeConfig(selectedType).label} moments...
                    </div>
                  ) : typeMoments.length === 0 ? (
                    <div className="p-8 border border-[var(--accent)]/20 rounded text-center">
                      <p className="font-theme-data text-text-muted">
                        No {getMomentTypeConfig(selectedType).label} moments found.
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {typeMoments.map((moment) => renderMomentCard(moment))}
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </main>
    </>
  );
}
