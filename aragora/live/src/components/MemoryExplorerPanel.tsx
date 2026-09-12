'use client';

import { useState, useEffect, useCallback } from 'react';
import { ErrorWithRetry } from './RetryButton';
import { withErrorBoundary } from './PanelErrorBoundary';
import { fetchWithRetry } from '@/utils/retry';
import { API_BASE_URL } from '@/config';
import { logger } from '@/utils/logger';

interface TierStats {
  count: number;
  avg_importance: number;
  ttl_hours?: number;
  max_entries?: number;
}

interface MemoryEntry {
  id: string;
  content: string;
  tier: string;
  importance: number;
  created_at?: string;
  metadata?: Record<string, unknown>;
}

interface TierTransition {
  from_tier: string;
  to_tier: string;
  count: number;
  timestamp?: string;
}

interface CritiqueEntry {
  id?: string;
  debate_id?: string;
  agent?: string;
  target_agent?: string;
  critique_type?: string;
  content: string;
  severity?: string;
  created_at?: string;
}

interface ArchiveStats {
  total_archived: number;
  by_tier: Record<string, number>;
  oldest_entry?: string;
  newest_entry?: string;
}

interface MemoryStats {
  tiers: Record<string, TierStats>;
  total_memories: number;
  transitions: TierTransition[];
}

interface MemoryPressure {
  fast: { usage: number; limit: number };
  medium: { usage: number; limit: number };
  slow: { usage: number; limit: number };
  glacial: { usage: number; limit: number };
  overall_pressure: number;
}

interface BackendConfig {
  apiUrl: string;
  wsUrl: string;
}

interface MemoryExplorerPanelProps {
  backendConfig?: BackendConfig;
}

const DEFAULT_API_BASE = API_BASE_URL;

const TIER_COLORS: Record<string, string> = {
  fast: 'text-acid-red',
  medium: 'text-[var(--acid-yellow)]',
  slow: 'text-[var(--acid-cyan)]',
  glacial: 'text-acid-blue',
};

const TIER_BG_COLORS: Record<string, string> = {
  fast: 'bg-acid-red/20 border-acid-red/40',
  medium: 'bg-acid-yellow/20 border-acid-yellow/40',
  slow: 'bg-[var(--acid-cyan)]/20 border-[var(--acid-cyan)]/40',
  glacial: 'bg-acid-blue/20 border-acid-blue/40',
};

const TIER_DESCRIPTIONS: Record<string, string> = {
  fast: 'Immediate context (TTL: ~1 min)',
  medium: 'Session memory (TTL: ~1 hour)',
  slow: 'Cross-session (TTL: ~1 day)',
  glacial: 'Long-term patterns (TTL: ~1 week)',
};

function MemoryExplorerPanelComponent({ backendConfig }: MemoryExplorerPanelProps) {
  const apiBase = backendConfig?.apiUrl || DEFAULT_API_BASE;

  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [pressure, setPressure] = useState<MemoryPressure | null>(null);
  const [memories, setMemories] = useState<MemoryEntry[]>([]);
  const [critiques, setCritiques] = useState<CritiqueEntry[]>([]);
  const [archiveStats, setArchiveStats] = useState<ArchiveStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [usingDemoData, setUsingDemoData] = useState(false);
  const [activeTab, setActiveTab] = useState<'overview' | 'search' | 'critiques' | 'transitions'>(
    'overview',
  );
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedTiers, setSelectedTiers] = useState<string[]>([
    'fast',
    'medium',
    'slow',
    'glacial',
  ]);
  const [minImportance, setMinImportance] = useState(0);
  const [critiqueFilter, setCritiqueFilter] = useState({ agent: '', debateId: '' });
  const [searchError, setSearchError] = useState<string | null>(null);
  const [critiqueError, setCritiqueError] = useState<string | null>(null);

  const fetchStats = useCallback(async () => {
    try {
      setLoading(true);
      const [statsRes, pressureRes, archiveRes] = await Promise.allSettled([
        fetchWithRetry(`${apiBase}/api/memory/tier-stats`, undefined, { maxRetries: 2 }),
        fetchWithRetry(`${apiBase}/api/memory/pressure`, undefined, { maxRetries: 2 }),
        fetchWithRetry(`${apiBase}/api/memory/archive-stats`, undefined, { maxRetries: 2 }),
      ]);

      if (statsRes.status === 'fulfilled' && statsRes.value.ok) {
        const data = await statsRes.value.json();
        // Normalize tier keys to lowercase for frontend consistency
        // Backend may return FAST, MEDIUM, SLOW, GLACIAL
        if (data.tiers) {
          const normalizedTiers: Record<string, TierStats> = {};
          for (const [key, value] of Object.entries(data.tiers)) {
            normalizedTiers[key.toLowerCase()] = value as TierStats;
          }
          data.tiers = normalizedTiers;
        }
        setStats(data);
        setUsingDemoData(false);
      } else {
        // Demo data when API unavailable
        setUsingDemoData(true);
        setStats({
          tiers: {
            fast: { count: 0, avg_importance: 0, ttl_hours: 0.017, max_entries: 100 },
            medium: { count: 0, avg_importance: 0, ttl_hours: 1, max_entries: 500 },
            slow: { count: 0, avg_importance: 0, ttl_hours: 24, max_entries: 1000 },
            glacial: { count: 0, avg_importance: 0, ttl_hours: 168, max_entries: 5000 },
          },
          total_memories: 0,
          transitions: [],
        });
      }

      if (pressureRes.status === 'fulfilled' && pressureRes.value.ok) {
        const data = await pressureRes.value.json();
        // Normalize backend response to frontend interface
        // Backend returns: { pressure, status, tier_utilization: { FAST: { count, limit, utilization } } }
        // Frontend expects: { fast: { usage, limit }, overall_pressure }
        if (data.tier_utilization) {
          const normalized: MemoryPressure = {
            fast: {
              usage: data.tier_utilization.FAST?.count || 0,
              limit: data.tier_utilization.FAST?.limit || 100,
            },
            medium: {
              usage: data.tier_utilization.MEDIUM?.count || 0,
              limit: data.tier_utilization.MEDIUM?.limit || 500,
            },
            slow: {
              usage: data.tier_utilization.SLOW?.count || 0,
              limit: data.tier_utilization.SLOW?.limit || 1000,
            },
            glacial: {
              usage: data.tier_utilization.GLACIAL?.count || 0,
              limit: data.tier_utilization.GLACIAL?.limit || 5000,
            },
            overall_pressure: data.pressure || 0,
          };
          setPressure(normalized);
        } else {
          // Fallback if already in expected format
          setPressure(data);
        }
      }

      if (archiveRes.status === 'fulfilled' && archiveRes.value.ok) {
        const data = await archiveRes.value.json();
        setArchiveStats(data);
      }

      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch memory stats');
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  const searchMemories = useCallback(async () => {
    if (!searchQuery.trim()) {
      setMemories([]);
      setSearchError(null);
      return;
    }

    try {
      setSearchError(null);
      const tiersParam = selectedTiers.join(',');
      // Use the newer /api/memory/search endpoint
      const response = await fetchWithRetry(
        `${apiBase}/api/memory/search?q=${encodeURIComponent(searchQuery)}&tier=${tiersParam}&limit=20&min_importance=${minImportance}`,
        undefined,
        { maxRetries: 2 },
      );

      if (response.ok) {
        const data = await response.json();
        setMemories(data.memories || []);
      } else {
        setSearchError('Search failed. Please try again.');
      }
    } catch (err) {
      logger.error('Search failed:', err);
      setSearchError('Unable to search memories. Please check your connection.');
    }
  }, [apiBase, searchQuery, selectedTiers, minImportance]);

  const fetchCritiques = useCallback(async () => {
    try {
      setCritiqueError(null);
      const params = new URLSearchParams({ limit: '30' });
      if (critiqueFilter.agent) params.append('agent', critiqueFilter.agent);
      if (critiqueFilter.debateId) params.append('debate_id', critiqueFilter.debateId);

      const response = await fetchWithRetry(
        `${apiBase}/api/memory/critiques?${params.toString()}`,
        undefined,
        { maxRetries: 2 },
      );

      if (response.ok) {
        const data = await response.json();
        setCritiques(data.critiques || []);
      } else {
        setCritiques([]);
        setCritiqueError('Failed to load critiques. Please try again.');
      }
    } catch (err) {
      logger.error('Fetching critiques failed:', err);
      setCritiques([]);
      setCritiqueError('Unable to load critiques. Please check your connection.');
    }
  }, [apiBase, critiqueFilter]);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  useEffect(() => {
    const debounce = setTimeout(() => {
      if (activeTab === 'search') {
        searchMemories();
      }
    }, 300);
    return () => clearTimeout(debounce);
  }, [searchQuery, selectedTiers, minImportance, activeTab, searchMemories]);

  useEffect(() => {
    if (activeTab === 'critiques') {
      const debounce = setTimeout(fetchCritiques, 300);
      return () => clearTimeout(debounce);
    }
  }, [activeTab, critiqueFilter, fetchCritiques]);

  if (loading && !stats) {
    return (
      <div className="card p-6">
        <div className="flex items-center gap-3">
          <div className="animate-spin w-5 h-5 border-2 border-[var(--accent)] border-t-transparent rounded-full" />
          <span className="font-theme-data text-text-muted">Loading memory stats...</span>
        </div>
      </div>
    );
  }

  if (error && !stats) {
    return (
      <ErrorWithRetry error={error || 'Failed to load memory statistics'} onRetry={fetchStats} />
    );
  }

  const tiers = ['fast', 'medium', 'slow', 'glacial'];

  return (
    <div className="space-y-6">
      {/* Demo Mode Indicator */}
      {usingDemoData && (
        <div className="bg-warning/10 border border-warning/30 rounded px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-warning">⚠</span>
            <span className="font-theme-data text-sm text-warning">
              Demo Mode - Memory API unavailable
            </span>
          </div>
          <button
            onClick={fetchStats}
            className="font-theme-data text-xs text-warning hover:text-warning/80 transition-colors"
          >
            [RETRY]
          </button>
        </div>
      )}

      {/* Tab Navigation */}
      <div className="flex gap-2 border-b border-[var(--accent)]/20 pb-2">
        {(['overview', 'search', 'critiques', 'transitions'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 font-theme-data text-sm transition-colors ${
              activeTab === tab
                ? 'text-[var(--accent)] border-b-2 border-[var(--accent)]'
                : 'text-text-muted hover:text-text'
            }`}
          >
            {tab.toUpperCase()}
          </button>
        ))}
      </div>

      {/* Overview Tab */}
      {activeTab === 'overview' && stats && (
        <div className="space-y-6">
          {/* Summary Stats */}
          <div className="card p-4">
            <h3 className="font-theme-data text-[var(--accent)] mb-4">Memory System Status</h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="text-center">
                <div className="text-3xl font-theme-data text-[var(--accent)]">
                  {stats.total_memories}
                </div>
                <div className="text-xs font-theme-data text-text-muted">Total Memories</div>
              </div>
              <div className="text-center">
                <div className="text-3xl font-theme-data text-[var(--acid-cyan)]">
                  {tiers.length}
                </div>
                <div className="text-xs font-theme-data text-text-muted">Active Tiers</div>
              </div>
              <div className="text-center">
                <div className="text-3xl font-theme-data text-[var(--acid-yellow)]">
                  {stats.transitions?.length || 0}
                </div>
                <div className="text-xs font-theme-data text-text-muted">Transitions</div>
              </div>
              <div className="text-center">
                <div className="text-3xl font-theme-data text-acid-red">
                  {pressure ? `${Math.round(pressure.overall_pressure * 100)}%` : 'N/A'}
                </div>
                <div className="text-xs font-theme-data text-text-muted">Pressure</div>
              </div>
            </div>
          </div>

          {/* Tier Cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {tiers.map((tier) => {
              const tierStats = stats.tiers?.[tier] || { count: 0, avg_importance: 0 };
              const tierPressure = pressure?.[tier as keyof MemoryPressure];
              const usagePercent =
                tierPressure && typeof tierPressure === 'object'
                  ? Math.round((tierPressure.usage / tierPressure.limit) * 100)
                  : 0;

              return (
                <div key={tier} className={`card p-4 border ${TIER_BG_COLORS[tier]}`}>
                  <div className="flex items-center justify-between mb-3">
                    <h4 className={`font-theme-data font-bold uppercase ${TIER_COLORS[tier]}`}>
                      {tier}
                    </h4>
                    <span className="text-xs font-theme-data text-text-muted">
                      {tierStats.count} entries
                    </span>
                  </div>

                  <p className="text-xs font-theme-data text-text-muted mb-3">
                    {TIER_DESCRIPTIONS[tier]}
                  </p>

                  {/* Progress Bar */}
                  <div className="mb-2">
                    <div className="h-2 bg-surface rounded-full overflow-hidden">
                      <div
                        className={`h-full ${TIER_COLORS[tier].replace('text-', 'bg-')} transition-all`}
                        style={{ width: `${Math.min(usagePercent, 100)}%` }}
                      />
                    </div>
                    <div className="flex justify-between text-xs font-theme-data text-text-muted mt-1">
                      <span>{usagePercent}% used</span>
                      <span>
                        {tierPressure && typeof tierPressure === 'object'
                          ? `${tierPressure.usage}/${tierPressure.limit}`
                          : 'N/A'}
                      </span>
                    </div>
                  </div>

                  <div className="text-xs font-theme-data text-text-muted">
                    Avg importance: {(tierStats.avg_importance || 0).toFixed(2)}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Archive Stats */}
          {archiveStats && archiveStats.total_archived > 0 && (
            <div className="card p-4">
              <h3 className="font-theme-data text-[var(--acid-cyan)] mb-4">Archive Statistics</h3>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="text-center">
                  <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">
                    {archiveStats.total_archived}
                  </div>
                  <div className="text-xs font-theme-data text-text-muted">Archived</div>
                </div>
                {Object.entries(archiveStats.by_tier || {}).map(([tier, count]) => (
                  <div key={tier} className="text-center">
                    <div
                      className={`text-2xl font-theme-data ${TIER_COLORS[tier.toLowerCase()] || 'text-text'}`}
                    >
                      {count}
                    </div>
                    <div className="text-xs font-theme-data text-text-muted capitalize">{tier}</div>
                  </div>
                ))}
              </div>
              {(archiveStats.oldest_entry || archiveStats.newest_entry) && (
                <div className="mt-4 pt-4 border-t border-[var(--acid-cyan)]/20 flex justify-between text-xs font-theme-data text-text-muted">
                  {archiveStats.oldest_entry && (
                    <span>Oldest: {new Date(archiveStats.oldest_entry).toLocaleDateString()}</span>
                  )}
                  {archiveStats.newest_entry && (
                    <span>Newest: {new Date(archiveStats.newest_entry).toLocaleDateString()}</span>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Search Tab */}
      {activeTab === 'search' && (
        <div className="space-y-4">
          {/* Search Controls */}
          <div className="card p-4 space-y-4">
            <div>
              <label className="block font-theme-data text-xs text-text-muted mb-2">
                Search Query
              </label>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search memories..."
                className="w-full bg-surface border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </div>

            <div className="flex flex-wrap gap-4">
              <div>
                <label className="block font-theme-data text-xs text-text-muted mb-2">Tiers</label>
                <div className="flex gap-2">
                  {tiers.map((tier) => (
                    <button
                      key={tier}
                      onClick={() => {
                        setSelectedTiers((prev) =>
                          prev.includes(tier) ? prev.filter((t) => t !== tier) : [...prev, tier],
                        );
                      }}
                      className={`px-3 py-1 font-theme-data text-xs rounded border transition-colors ${
                        selectedTiers.includes(tier)
                          ? `${TIER_BG_COLORS[tier]} ${TIER_COLORS[tier]}`
                          : 'border-text-muted/30 text-text-muted'
                      }`}
                    >
                      {tier}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="block font-theme-data text-xs text-text-muted mb-2">
                  Min Importance: {minImportance.toFixed(1)}
                </label>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.1"
                  value={minImportance}
                  onChange={(e) => setMinImportance(parseFloat(e.target.value))}
                  className="w-32"
                />
              </div>
            </div>
          </div>

          {/* Search Results */}
          <div className="card p-4">
            <h3 className="font-theme-data text-[var(--accent)] mb-4">
              Results ({memories.length})
            </h3>
            {searchError && (
              <div className="mb-4 p-3 bg-warning/10 border border-warning/30 rounded text-warning font-theme-data text-sm">
                {searchError}
              </div>
            )}
            {!searchError && memories.length === 0 ? (
              <p className="text-text-muted font-theme-data text-sm">
                {searchQuery ? 'No memories found.' : 'Enter a search query to find memories.'}
              </p>
            ) : (
              <div className="space-y-3">
                {memories.map((memory) => (
                  <div
                    key={memory.id}
                    className={`p-3 rounded border ${TIER_BG_COLORS[memory.tier] || 'border-text-muted/30'}`}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span
                        className={`font-theme-data text-xs uppercase ${TIER_COLORS[memory.tier]}`}
                      >
                        {memory.tier}
                      </span>
                      <span className="font-theme-data text-xs text-text-muted">
                        importance: {memory.importance.toFixed(2)}
                      </span>
                    </div>
                    <p className="font-theme-data text-sm text-text line-clamp-3">
                      {memory.content}
                    </p>
                    {memory.created_at && (
                      <p className="font-theme-data text-xs text-text-muted mt-2">
                        Created: {new Date(memory.created_at).toLocaleString()}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Critiques Tab */}
      {activeTab === 'critiques' && (
        <div className="space-y-4">
          {/* Critique Filters */}
          <div className="card p-4 space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block font-theme-data text-xs text-text-muted mb-2">
                  Filter by Agent
                </label>
                <input
                  type="text"
                  value={critiqueFilter.agent}
                  onChange={(e) =>
                    setCritiqueFilter((prev) => ({ ...prev, agent: e.target.value }))
                  }
                  placeholder="Agent name..."
                  className="w-full bg-surface border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
                />
              </div>
              <div>
                <label className="block font-theme-data text-xs text-text-muted mb-2">
                  Filter by Debate ID
                </label>
                <input
                  type="text"
                  value={critiqueFilter.debateId}
                  onChange={(e) =>
                    setCritiqueFilter((prev) => ({ ...prev, debateId: e.target.value }))
                  }
                  placeholder="Debate ID..."
                  className="w-full bg-surface border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
                />
              </div>
            </div>
          </div>

          {/* Critiques List */}
          <div className="card p-4">
            <h3 className="font-theme-data text-[var(--accent)] mb-4">
              Agent Critiques ({critiques.length})
            </h3>
            {critiqueError && (
              <div className="mb-4 p-3 bg-warning/10 border border-warning/30 rounded text-warning font-theme-data text-sm">
                {critiqueError}
              </div>
            )}
            {!critiqueError && critiques.length === 0 ? (
              <p className="text-text-muted font-theme-data text-sm">
                No critiques found. Critiques are recorded when agents analyze and critique each
                other&apos;s arguments during debates.
              </p>
            ) : (
              <div className="space-y-3">
                {critiques.map((critique, idx) => (
                  <div
                    key={critique.id || idx}
                    className={`p-4 bg-surface rounded border ${
                      critique.severity === 'high'
                        ? 'border-acid-red/40'
                        : critique.severity === 'medium'
                          ? 'border-acid-yellow/40'
                          : 'border-[var(--accent)]/30'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-3">
                        <span className="font-theme-data text-xs text-[var(--acid-cyan)]">
                          {critique.agent || 'Unknown'}
                        </span>
                        {critique.target_agent && (
                          <>
                            <span className="text-text-muted">→</span>
                            <span className="font-theme-data text-xs text-[var(--acid-yellow)]">
                              {critique.target_agent}
                            </span>
                          </>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        {critique.critique_type && (
                          <span className="px-2 py-0.5 bg-surface rounded text-xs font-theme-data text-text-muted">
                            {critique.critique_type}
                          </span>
                        )}
                        {critique.severity && (
                          <span
                            className={`px-2 py-0.5 rounded text-xs font-theme-data ${
                              critique.severity === 'high'
                                ? 'bg-acid-red/20 text-acid-red'
                                : critique.severity === 'medium'
                                  ? 'bg-acid-yellow/20 text-[var(--acid-yellow)]'
                                  : 'bg-[var(--accent)]/20 text-[var(--accent)]'
                            }`}
                          >
                            {critique.severity}
                          </span>
                        )}
                      </div>
                    </div>
                    <p className="font-theme-data text-sm text-text line-clamp-3">
                      {critique.content}
                    </p>
                    {critique.debate_id && (
                      <p className="font-theme-data text-xs text-text-muted mt-2">
                        Debate: {critique.debate_id}
                      </p>
                    )}
                    {critique.created_at && (
                      <p className="font-theme-data text-xs text-text-muted mt-1">
                        {new Date(critique.created_at).toLocaleString()}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Transitions Tab */}
      {activeTab === 'transitions' && stats && (
        <div className="card p-4">
          <h3 className="font-theme-data text-[var(--accent)] mb-4">Tier Transitions</h3>
          {!stats.transitions || stats.transitions.length === 0 ? (
            <p className="text-text-muted font-theme-data text-sm">
              No tier transitions recorded yet. Transitions occur when memories are promoted or
              demoted based on importance and access patterns.
            </p>
          ) : (
            <div className="space-y-2">
              {stats.transitions.map((transition, idx) => (
                <div
                  key={idx}
                  className="flex items-center gap-3 p-2 bg-surface rounded font-theme-data text-sm"
                >
                  <span className={TIER_COLORS[transition.from_tier]}>{transition.from_tier}</span>
                  <span className="text-text-muted">→</span>
                  <span className={TIER_COLORS[transition.to_tier]}>{transition.to_tier}</span>
                  <span className="text-text-muted ml-auto">{transition.count} entries</span>
                </div>
              ))}
            </div>
          )}

          {/* Transition Legend */}
          <div className="mt-6 p-3 bg-surface/50 rounded">
            <h4 className="font-theme-data text-xs text-[var(--acid-cyan)] mb-2">
              How Transitions Work
            </h4>
            <ul className="font-theme-data text-xs text-text-muted space-y-1">
              <li>
                • <span className="text-acid-red">Fast</span> →{' '}
                <span className="text-[var(--acid-yellow)]">Medium</span>: Frequently accessed
                memories promote up
              </li>
              <li>
                • <span className="text-[var(--acid-yellow)]">Medium</span> →{' '}
                <span className="text-[var(--acid-cyan)]">Slow</span>: Important patterns persist
                longer
              </li>
              <li>
                • <span className="text-[var(--acid-cyan)]">Slow</span> →{' '}
                <span className="text-acid-blue">Glacial</span>: Critical insights archive long-term
              </li>
              <li>• Reverse transitions occur when TTL expires or limits exceed</li>
            </ul>
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-4">
        <button
          onClick={fetchStats}
          disabled={loading}
          className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
        >
          {loading ? 'Refreshing...' : 'Refresh Stats'}
        </button>
      </div>
    </div>
  );
}

// Wrap with error boundary for graceful error handling
export const MemoryExplorerPanel = withErrorBoundary(
  MemoryExplorerPanelComponent,
  'Memory Explorer',
);
