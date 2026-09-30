'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector } from '@/components/BackendSelector';
import { useAuth } from '@/context/AuthContext';
import { useAragoraClient, useClientAuth } from '@/hooks/useAragoraClient';
import type {
  TierRevenue,
  RevenueResponse,
  AdminStatsResponse,
  AragoraError,
} from '@/lib/aragora-client';

function formatCurrency(cents: number): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(cents / 100);
}

function TierBar({ tier, data }: { tier: string; data: TierRevenue }) {
  const tierColors: Record<string, string> = {
    free: 'bg-text-muted',
    starter: 'bg-[var(--acid-cyan)]',
    professional: 'bg-[var(--accent)]',
    enterprise: 'bg-acid-yellow',
  };

  return (
    <div className="flex items-center gap-4 py-2">
      <div className="w-32 font-theme-data text-sm text-text">
        {tier.replace('_', ' ').toUpperCase()}
      </div>
      <div className="flex-1">
        <div className="h-6 bg-bg rounded overflow-hidden flex items-center">
          <div
            className={`h-full ${tierColors[tier] || 'bg-[var(--accent)]'} transition-all duration-500`}
            style={{ width: `${Math.min(100, data.count * 10)}%` }}
          />
        </div>
      </div>
      <div className="w-16 text-right font-theme-data text-sm text-[var(--acid-cyan)]">
        {data.count}
      </div>
      <div className="w-24 text-right font-theme-data text-sm text-[var(--accent)]">
        {formatCurrency(data.mrr_cents)}
      </div>
    </div>
  );
}

export default function RevenueAdminPage() {
  // Use SDK client hook instead of manual fetch
  const client = useAragoraClient();
  const { isAuthenticated } = useAuth();
  const { isAdmin } = useClientAuth();

  const [revenue, setRevenue] = useState<RevenueResponse['revenue'] | null>(null);
  const [stats, setStats] = useState<AdminStatsResponse['stats'] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    if (!isAuthenticated) return;

    try {
      setLoading(true);
      setError(null);

      // Fetch revenue data using SDK client
      const revenueData = await client.admin.revenue();
      setRevenue(revenueData.revenue);

      // Fetch admin stats using SDK client
      try {
        const statsData = await client.admin.stats();
        setStats(statsData.stats);
      } catch {
        // Stats endpoint may fail independently, don't block revenue display
      }
    } catch (err) {
      // Handle SDK errors with user-friendly messages
      if (err && typeof err === 'object' && 'toUserMessage' in err) {
        setError((err as AragoraError).toUserMessage());
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Failed to fetch data');
      }
    } finally {
      setLoading(false);
    }
  }, [client, isAuthenticated]);

  useEffect(() => {
    if (isAuthenticated) {
      fetchData();
    }
  }, [fetchData, isAuthenticated]);

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
                href="/admin"
                className="text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
              >
                [ADMIN]
              </Link>
              <BackendSelector compact />
              <ThemeToggle />
            </div>
          </div>
        </header>

        {/* Sub Navigation */}
        <div className="border-b border-[var(--accent)]/20 bg-surface/40">
          <div className="container mx-auto px-4">
            <div className="flex gap-4 overflow-x-auto">
              <Link
                href="/admin"
                className="px-4 py-2 font-theme-data text-sm text-text-muted hover:text-text transition-colors"
              >
                SYSTEM
              </Link>
              <Link
                href="/admin/organizations"
                className="px-4 py-2 font-theme-data text-sm text-text-muted hover:text-text transition-colors"
              >
                ORGANIZATIONS
              </Link>
              <Link
                href="/admin/users"
                className="px-4 py-2 font-theme-data text-sm text-text-muted hover:text-text transition-colors"
              >
                USERS
              </Link>
              <Link
                href="/admin/personas"
                className="px-4 py-2 font-theme-data text-sm text-text-muted hover:text-text transition-colors"
              >
                PERSONAS
              </Link>
              <Link
                href="/admin/audit"
                className="px-4 py-2 font-theme-data text-sm text-text-muted hover:text-text transition-colors"
              >
                AUDIT
              </Link>
              <Link
                href="/admin/revenue"
                className="px-4 py-2 font-theme-data text-sm text-[var(--accent)] border-b-2 border-[var(--accent)]"
              >
                REVENUE
              </Link>
              <Link
                href="/admin/training"
                className="px-4 py-2 font-theme-data text-sm text-text-muted hover:text-text transition-colors"
              >
                TRAINING
              </Link>
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="container mx-auto px-4 py-6">
          <div className="mb-6 flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">
                Revenue Dashboard
              </h1>
              <p className="text-text-muted font-theme-data text-sm">
                Monthly recurring revenue and subscription metrics.
              </p>
            </div>
            <button
              onClick={fetchData}
              disabled={loading}
              className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
            >
              {loading ? 'Loading...' : 'Refresh'}
            </button>
          </div>

          {!isAdmin && (
            <div className="card p-6 mb-6 border-acid-yellow/40">
              <div className="flex items-center gap-2 text-[var(--acid-yellow)] font-theme-data text-sm">
                <span>!</span>
                <span>Admin access required. Please sign in with an admin account.</span>
              </div>
            </div>
          )}

          {error && (
            <div className="card p-4 mb-6 border-acid-red/40 bg-acid-red/10">
              <p className="text-acid-red font-theme-data text-sm">{error}</p>
            </div>
          )}

          {loading ? (
            <div className="card p-8 text-center">
              <div className="font-theme-data text-text-muted animate-pulse">
                Loading revenue data...
              </div>
            </div>
          ) : (
            revenue && (
              <>
                {/* Key Metrics */}
                <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
                  <div className="card p-6">
                    <div className="font-theme-data text-xs text-text-muted mb-2">
                      Monthly Recurring Revenue
                    </div>
                    <div className="font-theme-data text-3xl text-[var(--accent)]">
                      ${revenue.mrr_dollars.toLocaleString()}
                    </div>
                    <div className="font-theme-data text-xs text-text-muted mt-1">MRR</div>
                  </div>
                  <div className="card p-6">
                    <div className="font-theme-data text-xs text-text-muted mb-2">
                      Annual Recurring Revenue
                    </div>
                    <div className="font-theme-data text-3xl text-[var(--acid-cyan)]">
                      ${revenue.arr_dollars.toLocaleString()}
                    </div>
                    <div className="font-theme-data text-xs text-text-muted mt-1">ARR</div>
                  </div>
                  <div className="card p-6">
                    <div className="font-theme-data text-xs text-text-muted mb-2">
                      Paying Organizations
                    </div>
                    <div className="font-theme-data text-3xl text-[var(--acid-yellow)]">
                      {revenue.paying_organizations}
                    </div>
                    <div className="font-theme-data text-xs text-text-muted mt-1">
                      of {revenue.total_organizations} total
                    </div>
                  </div>
                  <div className="card p-6">
                    <div className="font-theme-data text-xs text-text-muted mb-2">
                      Conversion Rate
                    </div>
                    <div className="font-theme-data text-3xl text-[var(--acid-magenta)]">
                      {revenue.total_organizations > 0
                        ? (
                            (revenue.paying_organizations / revenue.total_organizations) *
                            100
                          ).toFixed(1)
                        : 0}
                      %
                    </div>
                    <div className="font-theme-data text-xs text-text-muted mt-1">paying</div>
                  </div>
                </div>

                {/* Revenue by Tier */}
                <div className="card p-6 mb-6">
                  <h2 className="font-theme-data text-[var(--accent)] mb-4">Revenue by Tier</h2>
                  <div className="space-y-2">
                    <div className="flex items-center gap-4 py-2 border-b border-[var(--accent)]/20">
                      <div className="w-32 font-theme-data text-xs text-text-muted">TIER</div>
                      <div className="flex-1 font-theme-data text-xs text-text-muted">
                        SUBSCRIBERS
                      </div>
                      <div className="w-16 text-right font-theme-data text-xs text-text-muted">
                        COUNT
                      </div>
                      <div className="w-24 text-right font-theme-data text-xs text-text-muted">
                        MRR
                      </div>
                    </div>
                    {Object.entries(revenue.tier_breakdown)
                      .sort(([, a], [, b]) => b.mrr_cents - a.mrr_cents)
                      .map(([tier, data]) => (
                        <TierBar key={tier} tier={tier} data={data} />
                      ))}
                  </div>
                  <div className="flex items-center justify-end gap-4 mt-4 pt-4 border-t border-[var(--accent)]/20">
                    <div className="font-theme-data text-sm text-text-muted">Total MRR:</div>
                    <div className="font-theme-data text-lg text-[var(--accent)]">
                      {formatCurrency(revenue.mrr_cents)}
                    </div>
                  </div>
                </div>

                {/* Activity Stats */}
                {stats && (
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="card p-4">
                      <div className="font-theme-data text-xs text-text-muted">Total Users</div>
                      <div className="font-theme-data text-2xl text-[var(--accent)]">
                        {stats.total_users}
                      </div>
                    </div>
                    <div className="card p-4">
                      <div className="font-theme-data text-xs text-text-muted">Active (24h)</div>
                      <div className="font-theme-data text-2xl text-[var(--acid-cyan)]">
                        {stats.users_active_24h}
                      </div>
                    </div>
                    <div className="card p-4">
                      <div className="font-theme-data text-xs text-text-muted">New Users (7d)</div>
                      <div className="font-theme-data text-2xl text-[var(--acid-yellow)]">
                        {stats.new_users_7d}
                      </div>
                    </div>
                    <div className="card p-4">
                      <div className="font-theme-data text-xs text-text-muted">
                        Debates This Month
                      </div>
                      <div className="font-theme-data text-2xl text-text">
                        {stats.total_debates_this_month}
                      </div>
                    </div>
                  </div>
                )}
              </>
            )
          )}
        </div>
      </main>
    </>
  );
}
