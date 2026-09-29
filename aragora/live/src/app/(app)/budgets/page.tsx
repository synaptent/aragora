'use client';

import { useState, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { useSWRFetch } from '@/hooks/useSWRFetch';

// ---------------------------------------------------------------------------
// Types matching budgets.py response shapes
// ---------------------------------------------------------------------------

interface Budget {
  id: string;
  name: string;
  org_id: string;
  limit_amount: number;
  spent_amount: number;
  currency: string;
  period: string;
  status: string;
  created_at: string;
  reset_at: string | null;
  alerts_enabled: boolean;
  alert_thresholds: number[];
}

interface BudgetSummary {
  total_budgets: number;
  total_limit: number;
  total_spent: number;
  utilization_pct: number;
  budgets_at_risk: number;
  budgets_exceeded: number;
  currency: string;
}

interface BudgetAlert {
  alert_id: string;
  budget_id: string;
  threshold_pct: number;
  triggered_at: string;
  acknowledged: boolean;
  current_utilization: number;
}

interface SpendingTrend {
  date: string;
  amount: number;
  cumulative: number;
}

interface BudgetsListResponse {
  budgets: Budget[];
  total: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function UtilizationBar({ spent, limit }: { spent: number; limit: number }) {
  const pct = limit > 0 ? Math.min((spent / limit) * 100, 100) : 0;
  const color = pct >= 100 ? 'bg-red-400' : pct >= 80 ? 'bg-yellow-400' : 'bg-[var(--acid-green)]';

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-[var(--bg)] rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span
        className={`text-xs font-theme-data ${pct >= 100 ? 'text-red-400' : pct >= 80 ? 'text-yellow-400' : 'text-[var(--acid-green)]'}`}
      >
        {pct.toFixed(0)}%
      </span>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    active: 'text-[var(--acid-green)] bg-[var(--acid-green)]/10 border-[var(--acid-green)]/30',
    exceeded: 'text-red-400 bg-red-500/10 border-red-500/30',
    warning: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30',
    closed: 'text-[var(--text-muted)] bg-[var(--surface)] border-[var(--border)]',
    paused: 'text-[var(--acid-cyan)] bg-[var(--acid-cyan)]/10 border-[var(--acid-cyan)]/30',
  };

  const style = colors[status.toLowerCase()] || colors.active;

  return (
    <span className={`px-2 py-0.5 text-[10px] font-theme-data uppercase rounded border ${style}`}>
      {status}
    </span>
  );
}

function formatCurrency(amount: number, currency: string = 'USD'): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

function formatTimestamp(ts: string | null): string {
  if (!ts) return '--';
  try {
    return new Date(ts).toLocaleDateString();
  } catch {
    return ts;
  }
}

// ---------------------------------------------------------------------------
// Page Component
// ---------------------------------------------------------------------------

type ActiveTab = 'overview' | 'list' | 'alerts' | 'trends';

export default function BudgetsPage() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('overview');
  const [selectedBudget, setSelectedBudget] = useState<string | null>(null);

  // Fetch budget summary
  const {
    data: summaryData,
    isLoading: summaryLoading,
    error: summaryError,
  } = useSWRFetch<{ data: BudgetSummary }>('/api/v1/budgets/summary', { refreshInterval: 30000 });

  // Fetch budgets list
  const { data: budgetsData, isLoading: budgetsLoading } = useSWRFetch<BudgetsListResponse>(
    '/api/v1/budgets?limit=50',
    { refreshInterval: 30000 },
  );

  // Fetch alerts for selected budget
  const { data: alertsData, isLoading: alertsLoading } = useSWRFetch<{
    data: { alerts: BudgetAlert[] };
  }>(selectedBudget ? `/api/v1/budgets/${selectedBudget}/alerts` : null, {
    refreshInterval: 15000,
  });

  // Fetch org-wide trends
  const { data: trendsData, isLoading: trendsLoading } = useSWRFetch<{
    data: { trends: SpendingTrend[] };
  }>(activeTab === 'trends' ? '/api/v1/budgets/trends' : null, { refreshInterval: 60000 });

  const summary = summaryData?.data;
  const budgets = budgetsData?.budgets ?? [];
  const alerts = alertsData?.data?.alerts ?? [];
  const trends = trendsData?.data?.trends ?? [];

  // Acknowledge an alert
  const handleAcknowledgeAlert = useCallback(async (budgetId: string, alertId: string) => {
    try {
      await fetch(`/api/v1/budgets/${budgetId}/alerts/${alertId}/acknowledge`, { method: 'POST' });
    } catch {
      // acknowledgment failed silently
    }
  }, []);

  // Spending trend bar chart (simple ASCII-style)
  const maxTrendAmount = Math.max(...trends.map((t) => t.amount), 1);

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-[var(--bg)] text-[var(--text)] relative z-10">
        <div className="container mx-auto px-4 py-6">
          {/* Header */}
          <div className="mb-6">
            <div className="flex items-center gap-2 mb-2">
              <Link
                href="/costs"
                className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
              >
                Costs
              </Link>
              <span className="text-[var(--text-muted)]">/</span>
              <span className="text-xs font-theme-data text-[var(--acid-green)]">Budgets</span>
            </div>
            <h1 className="text-xl font-theme-data text-[var(--acid-green)]">
              {'>'} BUDGET MANAGEMENT
            </h1>
            <p className="text-xs text-[var(--text-muted)] font-theme-data mt-1">
              Track spending against budgets, monitor utilization, manage alerts, and view spending
              trends across the organization.
            </p>
          </div>

          {/* Error */}
          {summaryError && (
            <div className="mb-6 p-4 bg-red-500/10 border border-red-500/30 text-red-400 font-theme-data text-sm">
              Failed to load budget data. The budget management module may not be configured.
            </div>
          )}

          {/* Tabs */}
          <div className="flex gap-2 mb-6">
            {[
              { key: 'overview' as const, label: 'OVERVIEW' },
              { key: 'list' as const, label: 'BUDGETS' },
              { key: 'alerts' as const, label: 'ALERTS' },
              { key: 'trends' as const, label: 'TRENDS' },
            ].map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setActiveTab(key)}
                className={`px-4 py-2 font-theme-data text-sm border transition-colors ${
                  activeTab === key
                    ? 'border-[var(--acid-green)] bg-[var(--acid-green)]/10 text-[var(--acid-green)]'
                    : 'border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text)]'
                }`}
              >
                [{label}]
              </button>
            ))}
          </div>

          <PanelErrorBoundary panelName="Budget Management">
            {/* Overview Tab */}
            {activeTab === 'overview' && (
              <div>
                {/* Summary Cards */}
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-6">
                  <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
                    <div className="text-2xl font-theme-data text-[var(--acid-green)]">
                      {summaryLoading ? '-' : (summary?.total_budgets ?? 0)}
                    </div>
                    <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                      Budgets
                    </div>
                  </div>
                  <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
                    <div className="text-lg font-theme-data text-[var(--acid-cyan)]">
                      {summaryLoading
                        ? '-'
                        : summary
                          ? formatCurrency(summary.total_limit, summary.currency)
                          : '--'}
                    </div>
                    <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                      Total Limit
                    </div>
                  </div>
                  <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
                    <div className="text-lg font-theme-data text-purple-400">
                      {summaryLoading
                        ? '-'
                        : summary
                          ? formatCurrency(summary.total_spent, summary.currency)
                          : '--'}
                    </div>
                    <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                      Total Spent
                    </div>
                  </div>
                  <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
                    <div
                      className={`text-2xl font-theme-data ${
                        (summary?.utilization_pct ?? 0) >= 100
                          ? 'text-red-400'
                          : (summary?.utilization_pct ?? 0) >= 80
                            ? 'text-yellow-400'
                            : 'text-[var(--acid-green)]'
                      }`}
                    >
                      {summaryLoading
                        ? '-'
                        : summary?.utilization_pct != null
                          ? `${summary.utilization_pct.toFixed(0)}%`
                          : '--'}
                    </div>
                    <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                      Utilization
                    </div>
                  </div>
                  <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
                    <div
                      className={`text-2xl font-theme-data ${(summary?.budgets_at_risk ?? 0) > 0 ? 'text-yellow-400' : 'text-[var(--acid-green)]'}`}
                    >
                      {summaryLoading ? '-' : (summary?.budgets_at_risk ?? 0)}
                    </div>
                    <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                      At Risk
                    </div>
                  </div>
                  <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
                    <div
                      className={`text-2xl font-theme-data ${(summary?.budgets_exceeded ?? 0) > 0 ? 'text-red-400' : 'text-[var(--acid-green)]'}`}
                    >
                      {summaryLoading ? '-' : (summary?.budgets_exceeded ?? 0)}
                    </div>
                    <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                      Exceeded
                    </div>
                  </div>
                </div>

                {/* Budget Cards */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {budgetsLoading ? (
                    <div className="col-span-full p-8 text-center text-[var(--text-muted)] font-theme-data animate-pulse">
                      Loading budgets...
                    </div>
                  ) : budgets.length === 0 ? (
                    <div className="col-span-full p-8 text-center text-[var(--text-muted)] font-theme-data">
                      No budgets configured. Create a budget to start tracking spending.
                    </div>
                  ) : (
                    budgets.slice(0, 9).map((budget) => (
                      <div
                        key={budget.id}
                        className={`p-4 bg-[var(--surface)] border transition-colors cursor-pointer ${
                          selectedBudget === budget.id
                            ? 'border-[var(--acid-green)]'
                            : 'border-[var(--border)] hover:border-[var(--acid-green)]/30'
                        }`}
                        onClick={() =>
                          setSelectedBudget(selectedBudget === budget.id ? null : budget.id)
                        }
                      >
                        <div className="flex items-center justify-between mb-2">
                          <span className="font-theme-data text-sm text-[var(--text)] font-bold">
                            {budget.name}
                          </span>
                          <StatusBadge status={budget.status} />
                        </div>
                        <div className="mb-3">
                          <UtilizationBar spent={budget.spent_amount} limit={budget.limit_amount} />
                        </div>
                        <div className="flex justify-between text-[10px] font-theme-data text-[var(--text-muted)]">
                          <span>{formatCurrency(budget.spent_amount, budget.currency)} spent</span>
                          <span>{formatCurrency(budget.limit_amount, budget.currency)} limit</span>
                        </div>
                        <div className="flex justify-between text-[10px] font-theme-data text-[var(--text-muted)] mt-1">
                          <span>Period: {budget.period}</span>
                          {budget.reset_at && (
                            <span>Resets: {formatTimestamp(budget.reset_at)}</span>
                          )}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}

            {/* Budgets List Tab */}
            {activeTab === 'list' && (
              <div className="bg-[var(--surface)] border border-[var(--border)] overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-[10px] font-theme-data text-[var(--text-muted)] uppercase border-b border-[var(--border)]">
                        <th className="px-4 py-3">Name</th>
                        <th className="px-4 py-3">Status</th>
                        <th className="px-4 py-3">Spent / Limit</th>
                        <th className="px-4 py-3">Utilization</th>
                        <th className="px-4 py-3">Period</th>
                        <th className="px-4 py-3">Created</th>
                      </tr>
                    </thead>
                    <tbody>
                      {budgetsLoading ? (
                        <tr>
                          <td
                            colSpan={6}
                            className="px-4 py-12 text-center text-[var(--text-muted)] font-theme-data animate-pulse"
                          >
                            Loading budgets...
                          </td>
                        </tr>
                      ) : budgets.length === 0 ? (
                        <tr>
                          <td
                            colSpan={6}
                            className="px-4 py-12 text-center text-[var(--text-muted)] font-theme-data"
                          >
                            No budgets found.
                          </td>
                        </tr>
                      ) : (
                        budgets.map((budget) => (
                          <tr
                            key={budget.id}
                            className="border-b border-[var(--border)]/50 hover:bg-[var(--acid-green)]/5 transition-colors cursor-pointer"
                            onClick={() => setSelectedBudget(budget.id)}
                          >
                            <td className="px-4 py-3">
                              <span className="font-theme-data text-xs text-[var(--acid-cyan)]">
                                {budget.name}
                              </span>
                            </td>
                            <td className="px-4 py-3">
                              <StatusBadge status={budget.status} />
                            </td>
                            <td className="px-4 py-3 text-xs font-theme-data">
                              <span className="text-purple-400">
                                {formatCurrency(budget.spent_amount, budget.currency)}
                              </span>
                              <span className="text-[var(--text-muted)]"> / </span>
                              <span className="text-[var(--text)]">
                                {formatCurrency(budget.limit_amount, budget.currency)}
                              </span>
                            </td>
                            <td className="px-4 py-3 w-40">
                              <UtilizationBar
                                spent={budget.spent_amount}
                                limit={budget.limit_amount}
                              />
                            </td>
                            <td className="px-4 py-3 text-xs font-theme-data text-[var(--text-muted)]">
                              {budget.period}
                            </td>
                            <td className="px-4 py-3 text-xs font-theme-data text-[var(--text-muted)]">
                              {formatTimestamp(budget.created_at)}
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Alerts Tab */}
            {activeTab === 'alerts' && (
              <div>
                {!selectedBudget ? (
                  <div className="p-8 bg-[var(--surface)] border border-[var(--border)] text-center">
                    <p className="text-[var(--text-muted)] font-theme-data text-sm mb-4">
                      Select a budget to view its alerts.
                    </p>
                    <div className="flex flex-wrap gap-2 justify-center">
                      {budgets.map((b) => (
                        <button
                          key={b.id}
                          onClick={() => setSelectedBudget(b.id)}
                          className="px-3 py-1.5 text-xs font-theme-data border border-[var(--border)] text-[var(--text-muted)] hover:border-[var(--acid-green)]/30 transition-colors"
                        >
                          {b.name}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div>
                    <div className="flex items-center gap-3 mb-4">
                      <span className="text-sm font-theme-data text-[var(--acid-cyan)]">
                        Alerts for:{' '}
                        {budgets.find((b) => b.id === selectedBudget)?.name ?? selectedBudget}
                      </span>
                      <button
                        onClick={() => setSelectedBudget(null)}
                        className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--text)]"
                      >
                        [CLEAR]
                      </button>
                    </div>

                    {alertsLoading ? (
                      <div className="p-8 text-center text-[var(--text-muted)] font-theme-data animate-pulse">
                        Loading alerts...
                      </div>
                    ) : alerts.length === 0 ? (
                      <div className="p-8 bg-[var(--surface)] border border-[var(--border)] text-center text-[var(--text-muted)] font-theme-data">
                        No alerts triggered for this budget.
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {alerts.map((alert) => (
                          <div
                            key={alert.alert_id}
                            className={`p-4 border ${
                              alert.acknowledged
                                ? 'bg-[var(--surface)] border-[var(--border)]'
                                : 'bg-yellow-500/5 border-yellow-500/30'
                            }`}
                          >
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-3">
                                <span
                                  className={`text-sm font-theme-data font-bold ${alert.acknowledged ? 'text-[var(--text-muted)]' : 'text-yellow-400'}`}
                                >
                                  {alert.threshold_pct}% Threshold
                                </span>
                                <span className="text-xs font-theme-data text-[var(--text-muted)]">
                                  Utilization: {(alert.current_utilization * 100).toFixed(0)}%
                                </span>
                                <span className="text-xs font-theme-data text-[var(--text-muted)]">
                                  {formatTimestamp(alert.triggered_at)}
                                </span>
                              </div>
                              {!alert.acknowledged && (
                                <button
                                  onClick={() =>
                                    handleAcknowledgeAlert(selectedBudget, alert.alert_id)
                                  }
                                  className="px-3 py-1 text-[10px] font-theme-data text-[var(--acid-green)] border border-[var(--acid-green)]/30 hover:bg-[var(--acid-green)]/10 transition-colors"
                                >
                                  ACK
                                </button>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Trends Tab */}
            {activeTab === 'trends' && (
              <div>
                <h3 className="text-sm font-theme-data text-[var(--acid-green)] uppercase mb-4">
                  Organization Spending Trends
                </h3>
                {trendsLoading ? (
                  <div className="p-12 text-center text-[var(--text-muted)] font-theme-data animate-pulse">
                    Loading trends...
                  </div>
                ) : trends.length === 0 ? (
                  <div className="p-8 bg-[var(--surface)] border border-[var(--border)] text-center text-[var(--text-muted)] font-theme-data">
                    No spending trend data available yet.
                  </div>
                ) : (
                  <div className="p-4 bg-[var(--surface)] border border-[var(--border)]">
                    <div className="space-y-1">
                      {trends.map((point) => {
                        const barWidth =
                          maxTrendAmount > 0 ? (point.amount / maxTrendAmount) * 100 : 0;
                        return (
                          <div key={point.date} className="flex items-center gap-3">
                            <span className="text-[10px] font-theme-data text-[var(--text-muted)] w-20 shrink-0">
                              {point.date}
                            </span>
                            <div className="flex-1 h-4 bg-[var(--bg)] rounded overflow-hidden">
                              <div
                                className="h-full bg-[var(--acid-green)]/40 rounded transition-all"
                                style={{ width: `${barWidth}%` }}
                              />
                            </div>
                            <span className="text-[10px] font-theme-data text-[var(--text)] w-20 text-right">
                              ${point.amount.toFixed(2)}
                            </span>
                            <span className="text-[10px] font-theme-data text-[var(--text-muted)] w-24 text-right">
                              cum: ${point.cumulative.toFixed(2)}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            )}
          </PanelErrorBoundary>

          {/* Quick Links */}
          <div className="mt-8 flex flex-wrap gap-3">
            <Link
              href="/costs"
              className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              Cost Dashboard
            </Link>
            <Link
              href="/billing"
              className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              Billing
            </Link>
            <Link
              href="/usage"
              className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              Usage
            </Link>
          </div>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--acid-green)]/20 mt-8">
          <div className="text-[var(--acid-green)]/50 mb-2" aria-hidden="true">
            {'='.repeat(40)}
          </div>
          <p className="text-[var(--text-muted)]">{'>'} ARAGORA // BUDGET MANAGEMENT</p>
        </footer>
      </main>
    </>
  );
}
