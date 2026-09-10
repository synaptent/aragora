'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';

interface TierStats {
  tier: string;
  entries: number;
  total_hits: number;
  avg_hits: number;
  total_quality_impact: number;
  avg_quality_impact: number;
  promotions_in: number;
  promotions_out: number;
  demotions_in: number;
  demotions_out: number;
}

interface MemoryAnalytics {
  tier_stats: Record<string, TierStats>;
  promotion_effectiveness: number;
  learning_velocity: number;
  total_entries: number;
  total_hits: number;
  overall_quality_impact: number;
  recommendations: string[];
  generated_at: string;
}

interface TierInfo {
  id: string;
  name: string;
  description: string;
  ttl_seconds: number;
  ttl_human: string;
  count: number;
  limit: number;
  utilization: number;
  avg_importance: number;
  avg_surprise: number;
}

interface MemoryPressure {
  pressure: number;
  status: 'normal' | 'elevated' | 'high' | 'critical';
  tier_utilization: Record<string, { count: number; limit: number; utilization: number }>;
  total_memories: number;
  cleanup_recommended: boolean;
}

const TIER_COLORS: Record<string, string> = {
  fast: 'text-[var(--accent)]',
  medium: 'text-[var(--acid-cyan)]',
  slow: 'text-[var(--acid-yellow)]',
  glacial: 'text-purple-400',
};

const TIER_BG_COLORS: Record<string, string> = {
  fast: 'bg-[var(--accent)]/20',
  medium: 'bg-[var(--acid-cyan)]/20',
  slow: 'bg-acid-yellow/20',
  glacial: 'bg-purple-400/20',
};

export default function MemoryAnalyticsPage() {
  const { config: backendConfig } = useBackend();
  const [analytics, setAnalytics] = useState<MemoryAnalytics | null>(null);
  const [tiers, setTiers] = useState<TierInfo[]>([]);
  const [pressure, setPressure] = useState<MemoryPressure | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [selectedTier, setSelectedTier] = useState<string | null>(null);
  const [consolidating, setConsolidating] = useState(false);
  const [cleaning, setCleaning] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const [analyticsRes, tiersRes, pressureRes] = await Promise.all([
        fetch(`${backendConfig.api}/api/memory/analytics`),
        fetch(`${backendConfig.api}/api/memory/tiers`),
        fetch(`${backendConfig.api}/api/memory/pressure`),
      ]);

      if (analyticsRes.ok) {
        setAnalytics(await analyticsRes.json());
      }
      if (tiersRes.ok) {
        const tiersData = await tiersRes.json();
        setTiers(tiersData.tiers || []);
      }
      if (pressureRes.ok) {
        setPressure(await pressureRes.json());
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch memory data');
      // Demo data
      setAnalytics({
        tier_stats: {
          fast: {
            tier: 'fast',
            entries: 42,
            total_hits: 156,
            avg_hits: 3.71,
            total_quality_impact: 8.42,
            avg_quality_impact: 0.054,
            promotions_in: 5,
            promotions_out: 2,
            demotions_in: 1,
            demotions_out: 0,
          },
          medium: {
            tier: 'medium',
            entries: 256,
            total_hits: 892,
            avg_hits: 3.48,
            total_quality_impact: 45.3,
            avg_quality_impact: 0.051,
            promotions_in: 12,
            promotions_out: 8,
            demotions_in: 2,
            demotions_out: 5,
          },
          slow: {
            tier: 'slow',
            entries: 847,
            total_hits: 2341,
            avg_hits: 2.76,
            total_quality_impact: 98.7,
            avg_quality_impact: 0.042,
            promotions_in: 8,
            promotions_out: 15,
            demotions_in: 8,
            demotions_out: 12,
          },
          glacial: {
            tier: 'glacial',
            entries: 3972,
            total_hits: 5123,
            avg_hits: 1.29,
            total_quality_impact: 35.2,
            avg_quality_impact: 0.007,
            promotions_in: 15,
            promotions_out: 0,
            demotions_in: 15,
            demotions_out: 0,
          },
        },
        promotion_effectiveness: 0.756,
        learning_velocity: 2.143,
        total_entries: 5117,
        total_hits: 8512,
        overall_quality_impact: 187.62,
        recommendations: [
          'High promotion effectiveness. Consider more aggressive promotion.',
          'Memory tiers are balanced. No action needed.',
        ],
        generated_at: new Date().toISOString(),
      });
      setTiers([
        {
          id: 'fast',
          name: 'Fast',
          description: 'Immediate context, very short-term',
          ttl_seconds: 60,
          ttl_human: '1m',
          count: 42,
          limit: 100,
          utilization: 0.42,
          avg_importance: 0.82,
          avg_surprise: 0.51,
        },
        {
          id: 'medium',
          name: 'Medium',
          description: 'Session memory, short-term',
          ttl_seconds: 3600,
          ttl_human: '1h',
          count: 256,
          limit: 500,
          utilization: 0.51,
          avg_importance: 0.68,
          avg_surprise: 0.32,
        },
        {
          id: 'slow',
          name: 'Slow',
          description: 'Cross-session learning, medium-term',
          ttl_seconds: 86400,
          ttl_human: '1d',
          count: 847,
          limit: 1000,
          utilization: 0.85,
          avg_importance: 0.54,
          avg_surprise: 0.22,
        },
        {
          id: 'glacial',
          name: 'Glacial',
          description: 'Long-term patterns and insights',
          ttl_seconds: 604800,
          ttl_human: '7d',
          count: 3972,
          limit: 5000,
          utilization: 0.79,
          avg_importance: 0.41,
          avg_surprise: 0.1,
        },
      ]);
      setPressure({
        pressure: 0.725,
        status: 'elevated',
        tier_utilization: {
          fast: { count: 42, limit: 100, utilization: 0.42 },
          medium: { count: 256, limit: 500, utilization: 0.51 },
          slow: { count: 847, limit: 1000, utilization: 0.85 },
          glacial: { count: 3972, limit: 5000, utilization: 0.79 },
        },
        total_memories: 5117,
        cleanup_recommended: false,
      });
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, [autoRefresh, fetchData]);

  const triggerConsolidation = async () => {
    setConsolidating(true);
    try {
      await fetch(`${backendConfig.api}/api/memory/continuum/consolidate`, { method: 'POST' });
      fetchData();
    } catch {
      setError('Failed to trigger consolidation');
    } finally {
      setConsolidating(false);
    }
  };

  const triggerCleanup = async (tier?: string) => {
    setCleaning(true);
    try {
      const params = new URLSearchParams();
      if (tier) params.set('tier', tier);
      await fetch(`${backendConfig.api}/api/memory/continuum/cleanup?${params}`, {
        method: 'POST',
      });
      fetchData();
    } catch {
      setError('Failed to trigger cleanup');
    } finally {
      setCleaning(false);
    }
  };

  const getPressureColor = (status: string) => {
    switch (status) {
      case 'normal':
        return 'text-success';
      case 'elevated':
        return 'text-[var(--acid-yellow)]';
      case 'high':
        return 'text-orange-400';
      case 'critical':
        return 'text-[var(--crimson)]';
      default:
        return 'text-text-muted';
    }
  };

  const getUtilizationColor = (util: number) => {
    if (util >= 0.9) return 'bg-[var(--crimson)]';
    if (util >= 0.7) return 'bg-acid-yellow';
    return 'bg-[var(--accent)]';
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
              <div className="flex items-center gap-2">
                <span
                  className={`w-2 h-2 rounded-full ${autoRefresh ? 'bg-success animate-pulse' : 'bg-text-muted'}`}
                />
                <button
                  onClick={() => setAutoRefresh(!autoRefresh)}
                  className="text-xs font-theme-data text-text-muted hover:text-text"
                >
                  {autoRefresh ? 'AUTO' : 'PAUSED'}
                </button>
              </div>
              <Link
                href="/admin"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)]"
              >
                [ADMIN]
              </Link>
              <BackendSelector compact />
              <ThemeToggle />
            </div>
          </div>
        </header>

        <div className="container mx-auto px-4 py-6">
          <PanelErrorBoundary panelName="MemoryAnalytics">
            {/* Page Header */}
            <div className="flex items-center justify-between mb-6">
              <div>
                <div className="text-xs font-theme-data text-text-muted mb-1">
                  <Link href="/admin" className="hover:text-[var(--accent)]">
                    Admin
                  </Link>
                  <span className="mx-2">/</span>
                  <span className="text-[var(--accent)]">Memory Analytics</span>
                </div>
                <h1 className="text-2xl font-theme-data text-[var(--accent)]">
                  Memory Tier Analytics
                </h1>
                <p className="text-text-muted font-theme-data text-sm mt-1">
                  Continuum memory system monitoring and tier management
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={triggerConsolidation}
                  disabled={consolidating}
                  className="px-3 py-1.5 bg-[var(--acid-cyan)]/20 border border-[var(--acid-cyan)] text-[var(--acid-cyan)] font-theme-data text-xs rounded hover:bg-[var(--acid-cyan)]/30 disabled:opacity-50"
                >
                  {consolidating ? 'Consolidating...' : 'Consolidate'}
                </button>
                <button
                  onClick={() => triggerCleanup()}
                  disabled={cleaning}
                  className="px-3 py-1.5 bg-acid-yellow/20 border border-acid-yellow text-[var(--acid-yellow)] font-theme-data text-xs rounded hover:bg-acid-yellow/30 disabled:opacity-50"
                >
                  {cleaning ? 'Cleaning...' : 'Cleanup'}
                </button>
              </div>
            </div>

            {error && (
              <div className="mb-4 p-3 bg-[var(--crimson)]/20 border border-[var(--crimson)]/30 rounded text-[var(--crimson)] font-theme-data text-sm">
                {error}
                <span className="ml-2 text-text-muted">(showing demo data)</span>
              </div>
            )}

            {loading ? (
              <div className="card p-8 text-center">
                <div className="animate-pulse font-theme-data text-text-muted">
                  Loading memory analytics...
                </div>
              </div>
            ) : (
              <>
                {/* System Overview */}
                {pressure && analytics && (
                  <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
                    <div className="card p-4">
                      <div className="text-xs font-theme-data text-text-muted mb-1">PRESSURE</div>
                      <div
                        className={`text-2xl font-theme-data ${getPressureColor(pressure.status)}`}
                      >
                        {(pressure.pressure * 100).toFixed(1)}%
                      </div>
                      <div
                        className={`text-xs font-theme-data ${getPressureColor(pressure.status)}`}
                      >
                        {pressure.status.toUpperCase()}
                      </div>
                    </div>
                    <div className="card p-4">
                      <div className="text-xs font-theme-data text-text-muted mb-1">
                        TOTAL MEMORIES
                      </div>
                      <div className="text-2xl font-theme-data text-[var(--accent)]">
                        {analytics.total_entries.toLocaleString()}
                      </div>
                    </div>
                    <div className="card p-4">
                      <div className="text-xs font-theme-data text-text-muted mb-1">TOTAL HITS</div>
                      <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">
                        {analytics.total_hits.toLocaleString()}
                      </div>
                    </div>
                    <div className="card p-4">
                      <div className="text-xs font-theme-data text-text-muted mb-1">
                        PROMO EFFECTIVENESS
                      </div>
                      <div className="text-2xl font-theme-data text-purple-400">
                        {(analytics.promotion_effectiveness * 100).toFixed(1)}%
                      </div>
                    </div>
                    <div className="card p-4">
                      <div className="text-xs font-theme-data text-text-muted mb-1">
                        LEARNING VELOCITY
                      </div>
                      <div className="text-2xl font-theme-data text-[var(--acid-yellow)]">
                        {analytics.learning_velocity.toFixed(2)}/day
                      </div>
                    </div>
                  </div>
                )}

                {/* Tier Cards */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
                  {tiers.map((tier) => {
                    const stats = analytics?.tier_stats[tier.id];
                    const isSelected = selectedTier === tier.id;
                    return (
                      <div
                        key={tier.id}
                        className={`card p-4 cursor-pointer transition-colors ${
                          isSelected ? 'border-[var(--accent)]' : 'hover:border-[var(--accent)]/50'
                        }`}
                        onClick={() => setSelectedTier(isSelected ? null : tier.id)}
                      >
                        <div className="flex items-center justify-between mb-3">
                          <div className={`font-theme-data font-bold ${TIER_COLORS[tier.id]}`}>
                            {tier.name.toUpperCase()}
                          </div>
                          <span
                            className={`text-xs font-theme-data px-2 py-0.5 rounded ${TIER_BG_COLORS[tier.id]} ${TIER_COLORS[tier.id]}`}
                          >
                            TTL: {tier.ttl_human}
                          </span>
                        </div>
                        <div className="text-xs font-theme-data text-text-muted mb-3">
                          {tier.description}
                        </div>

                        {/* Utilization Bar */}
                        <div className="mb-3">
                          <div className="flex justify-between text-xs font-theme-data text-text-muted mb-1">
                            <span>
                              {tier.count} / {tier.limit}
                            </span>
                            <span>{(tier.utilization * 100).toFixed(0)}%</span>
                          </div>
                          <div className="h-2 bg-surface rounded overflow-hidden">
                            <div
                              className={`h-full ${getUtilizationColor(tier.utilization)} transition-all`}
                              style={{ width: `${tier.utilization * 100}%` }}
                            />
                          </div>
                        </div>

                        {/* Tier Stats */}
                        <div className="grid grid-cols-2 gap-2 text-xs font-theme-data">
                          <div>
                            <span className="text-text-muted">Avg Importance:</span>
                            <span className="ml-1">{tier.avg_importance.toFixed(2)}</span>
                          </div>
                          <div>
                            <span className="text-text-muted">Avg Surprise:</span>
                            <span className="ml-1">{tier.avg_surprise.toFixed(2)}</span>
                          </div>
                          {stats && (
                            <>
                              <div>
                                <span className="text-text-muted">Hits:</span>
                                <span className="ml-1">{stats.total_hits}</span>
                              </div>
                              <div>
                                <span className="text-text-muted">Quality:</span>
                                <span className="ml-1">{stats.avg_quality_impact.toFixed(3)}</span>
                              </div>
                            </>
                          )}
                        </div>

                        {/* Promotions/Demotions */}
                        {stats && isSelected && (
                          <div className="mt-4 pt-3 border-t border-border">
                            <div className="grid grid-cols-2 gap-2 text-xs font-theme-data">
                              <div className="text-success">
                                Promotions In: {stats.promotions_in}
                              </div>
                              <div className="text-[var(--crimson)]">
                                Promotions Out: {stats.promotions_out}
                              </div>
                              <div className="text-[var(--acid-yellow)]">
                                Demotions In: {stats.demotions_in}
                              </div>
                              <div className="text-text-muted">
                                Demotions Out: {stats.demotions_out}
                              </div>
                            </div>
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                triggerCleanup(tier.id);
                              }}
                              disabled={cleaning}
                              className="mt-3 w-full px-2 py-1 bg-surface border border-border text-text-muted font-theme-data text-xs rounded hover:border-acid-yellow hover:text-[var(--acid-yellow)]"
                            >
                              Cleanup This Tier
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>

                {/* Tier Flow Visualization */}
                <div className="card p-4 mb-6">
                  <h3 className="font-theme-data text-sm text-[var(--accent)] mb-4">
                    Memory Tier Flow
                  </h3>
                  <div className="flex items-center justify-between">
                    {tiers.map((tier, idx) => (
                      <div key={tier.id} className="flex items-center">
                        <div className={`text-center px-4 py-3 rounded ${TIER_BG_COLORS[tier.id]}`}>
                          <div className={`font-theme-data font-bold ${TIER_COLORS[tier.id]}`}>
                            {tier.name}
                          </div>
                          <div className="text-2xl font-theme-data">{tier.count}</div>
                          <div className="text-xs text-text-muted">{tier.ttl_human}</div>
                        </div>
                        {idx < tiers.length - 1 && (
                          <div className="mx-2 flex flex-col items-center">
                            <div className="text-xs font-theme-data text-text-muted">
                              {analytics?.tier_stats[tier.id]?.promotions_out || 0}
                            </div>
                            <div className="text-[var(--accent)]">→</div>
                            <div className="text-xs font-theme-data text-text-muted">
                              {analytics?.tier_stats[tiers[idx + 1].id]?.demotions_out || 0}
                            </div>
                            <div className="text-[var(--crimson)]">←</div>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>

                {/* Recommendations */}
                {analytics && analytics.recommendations.length > 0 && (
                  <div className="card p-4">
                    <h3 className="font-theme-data text-sm text-[var(--accent)] mb-3">
                      Recommendations
                    </h3>
                    <ul className="space-y-2">
                      {analytics.recommendations.map((rec, idx) => (
                        <li key={idx} className="flex items-start gap-2 text-sm font-theme-data">
                          <span className="text-[var(--acid-cyan)]">•</span>
                          <span className="text-text-muted">{rec}</span>
                        </li>
                      ))}
                    </ul>
                    <div className="mt-4 text-xs font-theme-data text-text-muted">
                      Generated:{' '}
                      {analytics.generated_at
                        ? new Date(analytics.generated_at).toLocaleString()
                        : 'N/A'}
                    </div>
                  </div>
                )}
              </>
            )}
          </PanelErrorBoundary>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // MEMORY ANALYTICS</p>
        </footer>
      </main>
    </>
  );
}
