'use client';

import { useState, useEffect, useCallback } from 'react';
import { logger } from '@/utils/logger';
import { API_BASE_URL } from '@/config';

interface MemoryEntry {
  id: string;
  tier: 'fast' | 'medium' | 'slow' | 'glacial';
  content: string;
  importance: number;
  surprise_score: number;
  consolidation_score: number;
  update_count: number;
  created_at: string;
  updated_at: string;
}

interface TierStats {
  count: number;
  avg_importance: number;
  avg_consolidation: number;
  oldest_entry: string | null;
  newest_entry: string | null;
}

interface ConsolidationResult {
  success: boolean;
  entries_processed: number;
  entries_promoted: number;
  entries_consolidated: number;
  duration_seconds: number;
}

interface MemoryInspectorProps {
  apiBase?: string;
}

const DEFAULT_API_BASE = API_BASE_URL;

const TIER_CONFIG = {
  fast: {
    label: 'FAST',
    description: 'Updates on every event (1h half-life)',
    color: 'acid-cyan',
    bgColor: 'bg-[var(--acid-cyan)]/20',
    borderColor: 'border-[var(--acid-cyan)]/30',
    textColor: 'text-[var(--acid-cyan)]',
  },
  medium: {
    label: 'MEDIUM',
    description: 'Updates per debate round (24h half-life)',
    color: 'yellow-400',
    bgColor: 'bg-yellow-400/20',
    borderColor: 'border-yellow-400/30',
    textColor: 'text-yellow-400',
  },
  slow: {
    label: 'SLOW',
    description: 'Updates per nomic cycle (7d half-life)',
    color: 'purple-400',
    bgColor: 'bg-purple-400/20',
    borderColor: 'border-purple-400/30',
    textColor: 'text-purple-400',
  },
  glacial: {
    label: 'GLACIAL',
    description: 'Updates monthly (30d half-life)',
    color: 'blue-400',
    bgColor: 'bg-blue-400/20',
    borderColor: 'border-blue-400/30',
    textColor: 'text-blue-400',
  },
};

export function MemoryInspector({ apiBase = DEFAULT_API_BASE }: MemoryInspectorProps) {
  const [query, setQuery] = useState('');
  const [memories, setMemories] = useState<MemoryEntry[]>([]);
  const [tierStats, setTierStats] = useState<Record<string, TierStats>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedTiers, setSelectedTiers] = useState<string[]>(['fast', 'medium']);
  const [expanded, setExpanded] = useState(true); // Show by default
  const [consolidating, setConsolidating] = useState(false);
  const [consolidationResult, setConsolidationResult] = useState<ConsolidationResult | null>(null);

  const fetchTierStats = useCallback(async () => {
    try {
      const response = await fetch(`${apiBase}/api/memory/tier-stats`);
      if (response.ok) {
        const data = await response.json();
        setTierStats(data.tiers || {});
      }
    } catch (err) {
      logger.error('Failed to fetch tier stats:', err);
    }
  }, [apiBase]);

  useEffect(() => {
    fetchTierStats();
  }, [fetchTierStats]);

  const searchMemories = useCallback(async () => {
    if (!query.trim()) {
      setError('Enter a search query');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const tiersParam = selectedTiers.join(',');
      const response = await fetch(
        `${apiBase}/api/memory/continuum/retrieve?query=${encodeURIComponent(query)}&tiers=${tiersParam}&limit=10`,
      );

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || `HTTP ${response.status}`);
      }

      const data = await response.json();
      setMemories(data.memories || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to search memories');
      setMemories([]);
    } finally {
      setLoading(false);
    }
  }, [apiBase, query, selectedTiers]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    searchMemories();
  };

  const triggerConsolidation = useCallback(async () => {
    setConsolidating(true);
    setConsolidationResult(null);

    try {
      const response = await fetch(`${apiBase}/api/memory/continuum/consolidate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || `HTTP ${response.status}`);
      }

      const data = await response.json();
      setConsolidationResult(data);
      // Refresh tier stats after consolidation
      fetchTierStats();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Consolidation failed');
    } finally {
      setConsolidating(false);
    }
  }, [apiBase, fetchTierStats]);

  const toggleTier = (tier: string) => {
    setSelectedTiers((prev) =>
      prev.includes(tier) ? prev.filter((t) => t !== tier) : [...prev, tier],
    );
  };

  const getTotalMemories = () => {
    return Object.values(tierStats).reduce((sum, stats) => sum + (stats.count || 0), 0);
  };

  return (
    <div className="panel">
      <div className="panel-header mb-4">
        <h3 className="panel-title font-theme-data">Continuum Memory</h3>
        <button onClick={() => setExpanded(!expanded)} className="panel-toggle hover:text-text">
          [{expanded ? '-' : '+'}]
        </button>
      </div>

      {/* Tier Overview */}
      <div className="grid grid-cols-4 gap-2 mb-4">
        {(Object.keys(TIER_CONFIG) as Array<keyof typeof TIER_CONFIG>).map((tier) => {
          const config = TIER_CONFIG[tier];
          const stats = tierStats[tier];
          const isSelected = selectedTiers.includes(tier);

          return (
            <button
              key={tier}
              onClick={() => toggleTier(tier)}
              className={`p-2 rounded border text-xs font-theme-data transition-all ${
                isSelected
                  ? `${config.bgColor} ${config.borderColor} ${config.textColor}`
                  : 'bg-bg border-border text-text-muted hover:border-text-muted'
              }`}
            >
              <div className="font-bold">{config.label}</div>
              <div className="text-[10px] opacity-70">{stats?.count ?? 0} entries</div>
            </button>
          );
        })}
      </div>

      {/* Summary Stats */}
      <div className="flex items-center justify-between text-xs font-theme-data text-text-muted mb-4 border-b border-border pb-3">
        <div className="flex items-center gap-4">
          <span>
            Total: <span className="text-text">{getTotalMemories()}</span> memories
          </span>
          <span>
            Selected: <span className="text-[var(--accent)]">{selectedTiers.length}</span> tiers
          </span>
        </div>
        <button
          onClick={triggerConsolidation}
          disabled={consolidating}
          className="px-2 py-1 bg-purple-500/20 border border-purple-500/30 text-purple-400 hover:bg-purple-500/30 disabled:opacity-50 transition-colors"
          title="Consolidate memories across tiers"
        >
          {consolidating ? 'CONSOLIDATING...' : 'CONSOLIDATE'}
        </button>
      </div>

      {/* Consolidation Result */}
      {consolidationResult && (
        <div className="mb-4 p-2 bg-[var(--accent)]/10 border border-[var(--accent)]/30 rounded text-xs font-theme-data">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[var(--accent)] font-bold">✓ CONSOLIDATED</span>
            <span className="text-text-muted">
              ({consolidationResult.duration_seconds.toFixed(2)}s)
            </span>
          </div>
          <div className="flex gap-4 text-text-muted">
            <span>
              Processed: <span className="text-text">{consolidationResult.entries_processed}</span>
            </span>
            <span>
              Promoted:{' '}
              <span className="text-[var(--acid-cyan)]">
                {consolidationResult.entries_promoted}
              </span>
            </span>
            <span>
              Merged:{' '}
              <span className="text-purple-400">{consolidationResult.entries_consolidated}</span>
            </span>
          </div>
        </div>
      )}

      {expanded && (
        <>
          {/* Search Form */}
          <form onSubmit={handleSubmit} className="mb-4">
            <div className="flex gap-2">
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search memories..."
                className="flex-1 px-3 py-2 bg-bg border border-border rounded text-sm font-theme-data text-text focus:border-[var(--accent)] focus:outline-none"
              />
              <button
                type="submit"
                disabled={loading}
                className="px-4 py-2 bg-[var(--accent)] text-bg font-theme-data text-sm font-bold hover:bg-[var(--accent)]/80 disabled:bg-text-muted transition-colors"
              >
                {loading ? '...' : 'SEARCH'}
              </button>
            </div>
          </form>

          {error && (
            <div className="mb-4 p-2 bg-warning/10 border border-warning/30 rounded text-sm text-warning font-theme-data">
              {error}
            </div>
          )}

          {/* Memory Results */}
          <div className="space-y-3 max-h-80 overflow-y-auto">
            {memories.length === 0 && !loading && !error && (
              <div className="text-center text-text-muted py-4 font-theme-data text-sm">
                Search the continuum memory system across selected tiers.
              </div>
            )}

            {memories.map((memory) => {
              const tierConfig = TIER_CONFIG[memory.tier];
              return (
                <div
                  key={memory.id}
                  className="p-3 bg-bg border border-border rounded-lg hover:border-text-muted/50 transition-colors"
                >
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <span
                      className={`px-2 py-0.5 text-xs rounded border font-theme-data ${tierConfig.bgColor} ${tierConfig.borderColor} ${tierConfig.textColor}`}
                    >
                      {tierConfig.label}
                    </span>
                    <div className="flex gap-2 text-xs font-theme-data text-text-muted">
                      <span title="Importance">IMP: {(memory.importance * 100).toFixed(0)}%</span>
                      <span title="Consolidation">
                        CON: {(memory.consolidation_score * 100).toFixed(0)}%
                      </span>
                    </div>
                  </div>

                  <p className="text-sm text-text mb-2 line-clamp-3">{memory.content}</p>

                  <div className="flex items-center justify-between text-xs font-theme-data text-text-muted">
                    <span>Updates: {memory.update_count}</span>
                    <span>
                      {memory.updated_at ? new Date(memory.updated_at).toLocaleDateString() : 'N/A'}
                    </span>
                  </div>

                  {/* Progress bars */}
                  <div className="mt-2 space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-theme-data text-text-muted w-12">IMP</span>
                      <div className="flex-1 h-1 bg-bg rounded-full overflow-hidden">
                        <div
                          className="h-full bg-[var(--accent)]"
                          style={{ width: `${memory.importance * 100}%` }}
                        />
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-theme-data text-text-muted w-12">CON</span>
                      <div className="flex-1 h-1 bg-bg rounded-full overflow-hidden">
                        <div
                          className="h-full bg-[var(--acid-cyan)]"
                          style={{ width: `${memory.consolidation_score * 100}%` }}
                        />
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}

      {/* Tier Legend */}
      {!expanded && (
        <div className="text-xs font-theme-data text-text-muted space-y-1">
          {(Object.keys(TIER_CONFIG) as Array<keyof typeof TIER_CONFIG>).map((tier) => {
            const config = TIER_CONFIG[tier];
            return (
              <div key={tier} className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full ${config.bgColor}`} />
                <span className={config.textColor}>{config.label}:</span>
                <span>{config.description}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
