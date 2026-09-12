'use client';

import { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '@/lib/api';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { useSettlementOracleTelemetry } from '@/hooks/useObservabilityDashboard';
interface Settlement {
  id: string;
  claim: string;
  agent_name: string;
  debate_id: string;
  confidence: number;
  outcome?: string;
  settled_at?: string;
  created_at: string;
}

interface SettlementSummary {
  total_claims: number;
  settled: number;
  pending: number;
  accuracy_rate: number;
}

type TabType = 'pending' | 'history' | 'stats';

export default function SettlementsPage() {
  const [tab, setTab] = useState<TabType>('pending');
  const [settlements, setSettlements] = useState<Settlement[]>([]);
  const [summary, setSummary] = useState<SettlementSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { settlementReview, oracleStream } = useSettlementOracleTelemetry();

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (tab === 'pending') {
        const data = await apiFetch<{
          data?: { settlements?: Settlement[] };
          settlements?: Settlement[];
        }>('/api/v1/settlements');
        setSettlements(data.data?.settlements || data.settlements || []);
      } else if (tab === 'history') {
        const data = await apiFetch<{
          data?: { settlements?: Settlement[] };
          settlements?: Settlement[];
        }>('/api/v1/settlements/history');
        setSettlements(data.data?.settlements || data.settlements || []);
      } else if (tab === 'stats') {
        const data = await apiFetch<{ data?: SettlementSummary } & SettlementSummary>(
          '/api/v1/settlements/summary',
        );
        setSummary(data.data || data);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load settlements');
    } finally {
      setLoading(false);
    }
  }, [tab]);

  useEffect(() => {
    loadData();
  }, [loadData]);
  const settlementAvailable = settlementReview?.available === true;
  const oracleAvailable = oracleStream?.available === true;

  return (
    <div className="max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-theme-data font-bold text-[var(--text)]">
            Claim Settlements
          </h1>
          <p className="text-sm text-[var(--text-muted)] mt-1">
            Verify debate claims against real outcomes to calibrate agent accuracy
          </p>
        </div>
      </div>

      {/* Ops telemetry strip */}
      <PanelErrorBoundary panelName="Settlement Telemetry">
        <div
          className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-6"
          aria-label="Settlement ops health"
        >
          <div className="p-3 bg-[var(--surface)] border border-[var(--border)] rounded-md">
            <div className="text-xs font-theme-data text-[var(--text-muted)] uppercase tracking-wider">
              Settlement Review
            </div>
            {settlementAvailable ? (
              <>
                <div className="text-sm font-theme-data text-[var(--text)] mt-1">
                  Scheduler: {settlementReview.running ? 'RUNNING' : 'NOT RUNNING'}
                </div>
                <div className="text-xs font-theme-data text-[var(--text-muted)] mt-1">
                  Interval: {settlementReview.interval_hours ?? '-'}h
                </div>
              </>
            ) : (
              <div className="text-xs font-theme-data text-[var(--text-muted)] mt-1">
                Ops telemetry unavailable
              </div>
            )}
          </div>

          <div className="p-3 bg-[var(--surface)] border border-[var(--border)] rounded-md">
            <div className="text-xs font-theme-data text-[var(--text-muted)] uppercase tracking-wider">
              Calibration Rollup
            </div>
            {settlementAvailable ? (
              <>
                <div className="text-sm font-theme-data text-[var(--text)] mt-1">
                  Success: {((settlementReview.stats?.success_rate ?? 0) * 100).toFixed(1)}%
                </div>
                <div className="text-xs font-theme-data text-[var(--text-muted)] mt-1">
                  Updated: {settlementReview.stats?.total_receipts_updated ?? 0} | Unresolved:{' '}
                  {settlementReview.stats?.last_result?.unresolved_due ?? 0}
                </div>
              </>
            ) : (
              <div className="text-xs font-theme-data text-[var(--text-muted)] mt-1">
                No settlement rollup
              </div>
            )}
          </div>

          <div className="p-3 bg-[var(--surface)] border border-[var(--border)] rounded-md">
            <div className="text-xs font-theme-data text-[var(--text-muted)] uppercase tracking-wider">
              Oracle Streaming
            </div>
            {oracleAvailable ? (
              <>
                <div className="text-sm font-theme-data text-[var(--text)] mt-1">
                  Active: {oracleStream.active_sessions} | Stalls: {oracleStream.stalls_total}
                </div>
                <div className="text-xs font-theme-data text-[var(--text-muted)] mt-1">
                  TTFT:{' '}
                  {oracleStream.ttft_avg_ms != null
                    ? `${Math.round(oracleStream.ttft_avg_ms)}ms`
                    : '-'}
                </div>
              </>
            ) : (
              <div className="text-xs font-theme-data text-[var(--text-muted)] mt-1">
                No oracle stream telemetry
              </div>
            )}
          </div>
        </div>
      </PanelErrorBoundary>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 border-b border-[var(--border)]">
        {(['pending', 'history', 'stats'] as TabType[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-theme-data transition-colors border-b-2 -mb-px ${
              tab === t
                ? 'border-[var(--acid-green)] text-[var(--acid-green)]'
                : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text)]'
            }`}
          >
            {t === 'pending' ? 'Pending' : t === 'history' ? 'History' : 'Agent Stats'}
          </button>
        ))}
      </div>

      {/* Error */}
      {error && (
        <div className="p-4 mb-4 bg-[var(--crimson)]/10 border border-[var(--crimson)]/30 rounded-md">
          <p className="text-sm text-[var(--crimson)] font-theme-data">{error}</p>
          <button
            onClick={loadData}
            className="mt-2 text-xs text-[var(--crimson)] underline hover:no-underline"
          >
            Retry
          </button>
        </div>
      )}

      <PanelErrorBoundary panelName="Settlement Data">
        {/* Loading */}
        {loading && (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-20 bg-[var(--surface-elevated)] rounded-md animate-pulse" />
            ))}
          </div>
        )}

        {/* Stats tab */}
        {!loading && tab === 'stats' && summary && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatCard label="Total Claims" value={summary.total_claims} />
            <StatCard label="Settled" value={summary.settled} />
            <StatCard label="Pending" value={summary.pending} />
            <StatCard
              label="Accuracy"
              value={`${(summary.accuracy_rate * 100).toFixed(1)}%`}
              highlight
            />
          </div>
        )}

        {/* Settlements list */}
        {!loading && tab !== 'stats' && (
          <div className="space-y-3">
            {settlements.length === 0 ? (
              <div className="text-center py-12 text-[var(--text-muted)]">
                <p className="text-lg font-theme-data mb-2">
                  {tab === 'pending' ? 'No pending settlements' : 'No settlement history'}
                </p>
                <p className="text-sm">
                  {tab === 'pending'
                    ? 'Claims from completed debates will appear here for verification'
                    : 'Settled claims will appear here with their outcomes'}
                </p>
              </div>
            ) : (
              settlements.map((s) => (
                <SettlementCard key={s.id} settlement={s} isPending={tab === 'pending'} />
              ))
            )}
          </div>
        )}
      </PanelErrorBoundary>
    </div>
  );
}

function StatCard({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string | number;
  highlight?: boolean;
}) {
  return (
    <div className="p-4 bg-[var(--surface)] border border-[var(--border)] rounded-md">
      <p className="text-xs text-[var(--text-muted)] font-theme-data uppercase tracking-wider">
        {label}
      </p>
      <p
        className={`text-2xl font-theme-data font-bold mt-1 ${
          highlight ? 'text-[var(--acid-green)]' : 'text-[var(--text)]'
        }`}
      >
        {value}
      </p>
    </div>
  );
}

function SettlementCard({ settlement, isPending }: { settlement: Settlement; isPending: boolean }) {
  return (
    <div className="p-4 bg-[var(--surface)] border border-[var(--border)] rounded-md hover:border-[var(--acid-green)]/30 transition-colors">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-theme-data text-[var(--text)] truncate">{settlement.claim}</p>
          <div className="flex items-center gap-3 mt-2 text-xs text-[var(--text-muted)]">
            <span>Agent: {settlement.agent_name}</span>
            <span>Confidence: {(settlement.confidence * 100).toFixed(0)}%</span>
            <span>{new Date(settlement.created_at).toLocaleDateString()}</span>
          </div>
        </div>
        <div className="flex-shrink-0">
          {isPending ? (
            <span className="px-2 py-1 text-xs font-theme-data bg-acid-yellow/10 text-[var(--acid-yellow)] border border-acid-yellow/30 rounded">
              PENDING
            </span>
          ) : (
            <span
              className={`px-2 py-1 text-xs font-theme-data rounded ${
                settlement.outcome === 'correct'
                  ? 'bg-[var(--accent)]/10 text-[var(--accent)] border border-[var(--accent)]/30'
                  : 'bg-[var(--crimson)]/10 text-[var(--crimson)] border border-[var(--crimson)]/30'
              }`}
            >
              {settlement.outcome?.toUpperCase() || 'UNKNOWN'}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
