'use client';

import { useState, useEffect } from 'react';
import dynamic from 'next/dynamic';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { UnifiedMemorySearch } from '@/components/memory/UnifiedMemorySearch';
import { RetentionDecisions } from '@/components/memory/RetentionDecisions';
import { DedupClusters } from '@/components/memory/DedupClusters';
import { CrossDebateLearning } from '@/components/memory/CrossDebateLearning';
import { MemoryTiersPanel } from '@/components/memory/MemoryTiersPanel';

const MemoryExplorerPanel = dynamic(
  () =>
    import('@/components/MemoryExplorerPanel').then((m) => ({ default: m.MemoryExplorerPanel })),
  {
    ssr: false,
    loading: () => (
      <div className="card p-4 animate-pulse">
        <div className="h-96 bg-surface rounded" />
      </div>
    ),
  },
);

const MemoryAnalyticsPanel = dynamic(
  () =>
    import('@/components/MemoryAnalyticsPanel').then((m) => ({ default: m.MemoryAnalyticsPanel })),
  {
    ssr: false,
    loading: () => (
      <div className="card p-4 animate-pulse">
        <div className="h-48 bg-surface rounded" />
      </div>
    ),
  },
);

interface MemoryPressure {
  overall_pressure: number;
  tier_pressure: { fast: number; medium: number; slow: number; glacial: number };
  alerts: string[];
  recommendation?: string;
}

const DEFAULT_TIER_PRESSURE = { fast: 0, medium: 0, slow: 0, glacial: 0 };

function _asNumber(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function normalizeMemoryPressure(data: unknown): MemoryPressure | null {
  if (!data || typeof data !== 'object') {
    return null;
  }

  const payload = data as Record<string, unknown>;
  const rawTierPressure =
    payload.tier_pressure && typeof payload.tier_pressure === 'object'
      ? (payload.tier_pressure as Record<string, unknown>)
      : null;
  const rawTierUtilization =
    payload.tier_utilization && typeof payload.tier_utilization === 'object'
      ? (payload.tier_utilization as Record<string, unknown>)
      : null;

  const getTierValue = (tier: keyof typeof DEFAULT_TIER_PRESSURE) => {
    const tierPressureValue = rawTierPressure?.[tier];
    if (typeof tierPressureValue === 'number' && Number.isFinite(tierPressureValue)) {
      return tierPressureValue;
    }

    const tierKey = tier.toUpperCase();
    const tierUtilizationEntry = rawTierUtilization?.[tierKey] ?? rawTierUtilization?.[tier];
    if (tierUtilizationEntry && typeof tierUtilizationEntry === 'object') {
      return _asNumber(
        (tierUtilizationEntry as { utilization?: unknown }).utilization,
        DEFAULT_TIER_PRESSURE[tier],
      );
    }

    return DEFAULT_TIER_PRESSURE[tier];
  };

  const tier_pressure = {
    fast: getTierValue('fast'),
    medium: getTierValue('medium'),
    slow: getTierValue('slow'),
    glacial: getTierValue('glacial'),
  };

  const overall_pressure = _asNumber(
    payload.overall_pressure ?? payload.pressure,
    Math.max(...Object.values(tier_pressure)),
  );

  const alerts = Array.isArray(payload.alerts)
    ? payload.alerts.filter((alert): alert is string => typeof alert === 'string')
    : [];

  return {
    overall_pressure,
    tier_pressure,
    alerts,
    recommendation: typeof payload.recommendation === 'string' ? payload.recommendation : undefined,
  };
}

function PressureGauge({ value, label, color }: { value: number; label: string; color: string }) {
  const percentage = Math.min(100, Math.max(0, value * 100));
  const barColor = percentage > 80 ? 'bg-warning' : percentage > 60 ? 'bg-acid-yellow' : color;

  return (
    <div className="flex-1">
      <div className="flex justify-between text-xs font-theme-data mb-1">
        <span className="text-text-muted">{label}</span>
        <span className={percentage > 80 ? 'text-warning' : 'text-text'}>
          {percentage.toFixed(0)}%
        </span>
      </div>
      <div className="h-2 bg-bg rounded overflow-hidden">
        <div className={`h-full transition-all ${barColor}`} style={{ width: `${percentage}%` }} />
      </div>
    </div>
  );
}

export default function MemoryPage() {
  const { config: backendConfig } = useBackend();
  const [pressure, setPressure] = useState<MemoryPressure | null>(null);
  const [activeTab, setActiveTab] = useState<
    'explorer' | 'analytics' | 'tiers' | 'unified' | 'retention' | 'dedup' | 'learning'
  >('explorer');

  // Fetch memory pressure data
  useEffect(() => {
    const fetchPressure = async () => {
      try {
        const res = await fetch(`${backendConfig.api}/api/memory/pressure`);
        if (res.ok) {
          const data = await res.json();
          setPressure(normalizeMemoryPressure(data));
        }
      } catch {
        // Pressure endpoint may not exist
      }
    };

    fetchPressure();
    const interval = setInterval(fetchPressure, 30000);
    return () => clearInterval(interval);
  }, [backendConfig.api]);

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        {/* Content */}
        <div className="container mx-auto px-4 py-6">
          <div className="mb-6">
            <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">
              {'>'} CONTINUUM MEMORY
            </h1>
            <p className="text-text-muted font-theme-data text-sm">
              Explore the multi-tier memory system: fast, medium, slow, and glacial storage.
            </p>
          </div>

          {/* Memory Pressure Section */}
          {pressure && (
            <div className="mb-6 p-4 border border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/5 rounded">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-theme-data text-[var(--acid-cyan)]">Memory Pressure</h3>
                <span
                  className={`text-xs font-theme-data px-2 py-0.5 rounded ${
                    pressure.overall_pressure > 0.8
                      ? 'bg-warning/20 text-warning'
                      : pressure.overall_pressure > 0.6
                        ? 'bg-acid-yellow/20 text-[var(--acid-yellow)]'
                        : 'bg-[var(--accent)]/20 text-[var(--accent)]'
                  }`}
                >
                  {pressure.overall_pressure > 0.8
                    ? 'HIGH'
                    : pressure.overall_pressure > 0.6
                      ? 'MODERATE'
                      : 'NORMAL'}
                </span>
              </div>
              <div className="flex gap-4">
                <PressureGauge
                  value={pressure.tier_pressure.fast}
                  label="Fast"
                  color="bg-[var(--accent)]"
                />
                <PressureGauge
                  value={pressure.tier_pressure.medium}
                  label="Medium"
                  color="bg-[var(--acid-cyan)]"
                />
                <PressureGauge value={pressure.tier_pressure.slow} label="Slow" color="bg-gold" />
                <PressureGauge
                  value={pressure.tier_pressure.glacial}
                  label="Glacial"
                  color="bg-acid-purple"
                />
              </div>
              {pressure.alerts && pressure.alerts.length > 0 && (
                <div className="mt-3 pt-3 border-t border-[var(--acid-cyan)]/20">
                  {pressure.alerts.map((alert, i) => (
                    <div
                      key={i}
                      className="text-xs font-theme-data text-warning flex items-center gap-2"
                    >
                      <span>!</span> {alert}
                    </div>
                  ))}
                </div>
              )}
              {pressure.recommendation && (
                <div className="mt-2 text-xs font-theme-data text-text-muted">
                  Recommendation: {pressure.recommendation}
                </div>
              )}
            </div>
          )}

          {/* Tab Navigation */}
          <div className="flex gap-2 mb-6">
            {(
              [
                { key: 'explorer', label: 'EXPLORER' },
                { key: 'analytics', label: 'ANALYTICS' },
                { key: 'tiers', label: 'TIERS' },
                { key: 'unified', label: 'UNIFIED' },
                { key: 'retention', label: 'RETENTION' },
                { key: 'dedup', label: 'DEDUP' },
                { key: 'learning', label: 'LEARNING' },
              ] as const
            ).map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setActiveTab(key)}
                className={`px-4 py-2 font-theme-data text-sm border transition-colors ${
                  activeTab === key
                    ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]'
                    : 'border-[var(--accent)]/30 text-text-muted hover:text-text'
                }`}
              >
                [{label}]
              </button>
            ))}
          </div>

          {activeTab === 'explorer' && (
            <PanelErrorBoundary panelName="Memory Explorer">
              <MemoryExplorerPanel
                backendConfig={{ apiUrl: backendConfig.api, wsUrl: backendConfig.ws }}
              />
            </PanelErrorBoundary>
          )}
          {activeTab === 'analytics' && (
            <PanelErrorBoundary panelName="Memory Analytics">
              <MemoryAnalyticsPanel apiBase={backendConfig.api} />
            </PanelErrorBoundary>
          )}
          {activeTab === 'tiers' && (
            <PanelErrorBoundary panelName="Memory Tiers">
              <MemoryTiersPanel />
            </PanelErrorBoundary>
          )}
          {activeTab === 'unified' && <UnifiedMemorySearch />}
          {activeTab === 'retention' && <RetentionDecisions />}
          {activeTab === 'dedup' && <DedupClusters />}
          {activeTab === 'learning' && <CrossDebateLearning />}
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // MEMORY EXPLORER</p>
        </footer>
      </main>
    </>
  );
}
