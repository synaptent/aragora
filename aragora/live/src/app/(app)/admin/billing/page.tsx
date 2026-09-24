'use client';

import { useState, useEffect, useCallback } from 'react';
import { AdminLayout } from '@/components/admin/AdminLayout';
import { UsageChart, DataPoint, TimeRange } from '@/components/admin/UsageChart';
import { useBackend } from '@/components/BackendSelector';
import { useAuth } from '@/context/AuthContext';

interface UsageSummary {
  tokens_used: number;
  tokens_in: number;
  tokens_out: number;
  debates_count: number;
  api_calls: number;
  estimated_cost_usd: number;
  period_start: string;
  period_end: string;
}

interface Invoice {
  id: string;
  number: string;
  amount_due: number;
  amount_paid: number;
  currency: string;
  status: 'draft' | 'open' | 'paid' | 'void' | 'uncollectible';
  period_start: string;
  period_end: string;
  created_at: string;
  paid_at?: string;
  pdf_url?: string;
}

interface PlanInfo {
  current_tier: string;
  debates_limit: number;
  debates_used: number;
  features: string[];
  price_monthly: number;
  next_billing_date?: string;
}

const TIER_PRICES: Record<string, { monthly: number; features: string[] }> = {
  free: { monthly: 0, features: ['10 debates/month', '3 agents', 'Community support'] },
  starter: {
    monthly: 29,
    features: ['100 debates/month', '10 agents', 'Email support', 'API access'],
  },
  professional: {
    monthly: 99,
    features: [
      '1,000 debates/month',
      'All agents',
      'Priority support',
      'Advanced analytics',
      'Full API access',
    ],
  },
  enterprise: {
    monthly: 0,
    features: [
      'Unlimited debates',
      'SSO/SCIM',
      'Dedicated support',
      'SLA guarantee',
      'On-prem option',
      'Compliance',
    ],
  },
};

function formatCurrency(cents: number, currency = 'USD'): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(cents / 100);
}

function StatusBadge({ status }: { status: Invoice['status'] }) {
  const colors: Record<string, string> = {
    paid: 'bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/40',
    open: 'bg-acid-yellow/20 text-[var(--acid-yellow)] border-acid-yellow/40',
    draft: 'bg-text-muted/20 text-text-muted border-text-muted/40',
    void: 'bg-acid-red/20 text-acid-red border-acid-red/40',
    uncollectible: 'bg-acid-red/20 text-acid-red border-acid-red/40',
  };

  return (
    <span
      className={`px-2 py-0.5 text-xs font-theme-data rounded border ${colors[status] || colors.draft}`}
    >
      {status.toUpperCase()}
    </span>
  );
}

function TierCard({
  tier,
  current,
  onUpgrade,
}: {
  tier: string;
  current: boolean;
  onUpgrade: (tier: string) => void;
}) {
  const info = TIER_PRICES[tier];
  if (!info) return null;

  return (
    <div className={`card p-4 ${current ? 'border-[var(--accent)]' : ''}`}>
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-theme-data text-lg text-text capitalize">{tier.replace('_', ' ')}</h3>
        {current && (
          <span className="px-2 py-0.5 text-xs font-theme-data rounded border bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/40">
            CURRENT
          </span>
        )}
      </div>
      <div className="font-theme-data text-2xl text-[var(--acid-cyan)] mb-4">
        ${info.monthly}
        <span className="text-sm text-text-muted">/mo</span>
      </div>
      <ul className="space-y-2 mb-4">
        {info.features.map((feature, idx) => (
          <li key={idx} className="font-theme-data text-xs text-text-muted flex items-center gap-2">
            <span className="text-[var(--accent)]">*</span>
            {feature}
          </li>
        ))}
      </ul>
      {!current && (
        <button
          onClick={() => onUpgrade(tier)}
          className="w-full px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors"
        >
          {info.monthly > (TIER_PRICES[tier]?.monthly || 0) ? 'Upgrade' : 'Change Plan'}
        </button>
      )}
    </div>
  );
}

export default function BillingPage() {
  const { config: backendConfig } = useBackend();
  const { isAuthenticated, tokens } = useAuth();
  const token = tokens?.access_token;

  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [planInfo, setPlanInfo] = useState<PlanInfo | null>(null);
  const [tokenChartData, setTokenChartData] = useState<DataPoint[]>([]);
  const [debateChartData, setDebateChartData] = useState<DataPoint[]>([]);
  const [apiCallChartData, setApiCallChartData] = useState<DataPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [timeRange, setTimeRange] = useState<TimeRange>('30d');
  const [activeTab, setActiveTab] = useState<'usage' | 'invoices' | 'plans'>('usage');

  const fetchData = useCallback(async () => {
    if (!token) return;

    try {
      setLoading(true);
      setError(null);

      // Fetch usage summary
      const usageRes = await fetch(`${backendConfig.api}/api/billing/usage`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (usageRes.ok) {
        const data = await usageRes.json();
        setUsage(data.usage);
      }

      // Fetch plan info
      const planRes = await fetch(`${backendConfig.api}/api/billing/plan`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (planRes.ok) {
        const data = await planRes.json();
        setPlanInfo(data.plan);
      }

      // Fetch invoices
      const invoicesRes = await fetch(`${backendConfig.api}/api/billing/invoices`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (invoicesRes.ok) {
        const data = await invoicesRes.json();
        setInvoices(data.invoices || []);
      }

      // Fetch analytics data
      try {
        const analyticsRes = await fetch(
          `${backendConfig.api}/api/v1/analytics/usage?period=${timeRange}`,
          { headers: { Authorization: `Bearer ${token}` } },
        );
        if (analyticsRes.ok) {
          const data = await analyticsRes.json();
          if (data.daily_tokens) {
            setTokenChartData(
              data.daily_tokens.map((d: { date: string; count: number }) => ({
                label: new Date(d.date).toLocaleDateString('en-US', {
                  month: 'short',
                  day: 'numeric',
                }),
                value: d.count,
                date: d.date,
              })),
            );
          } else {
            setTokenChartData([]);
          }
          if (data.daily_debates) {
            setDebateChartData(
              data.daily_debates.map((d: { date: string; count: number }) => ({
                label: new Date(d.date).toLocaleDateString('en-US', {
                  month: 'short',
                  day: 'numeric',
                }),
                value: d.count,
                date: d.date,
              })),
            );
          } else {
            setDebateChartData([]);
          }
          if (data.daily_api_calls) {
            setApiCallChartData(
              data.daily_api_calls.map((d: { date: string; count: number }) => ({
                label: new Date(d.date).toLocaleDateString('en-US', {
                  month: 'short',
                  day: 'numeric',
                }),
                value: d.count,
                date: d.date,
              })),
            );
          } else {
            setApiCallChartData([]);
          }
        } else {
          // Clear chart data on API error - show empty state
          setTokenChartData([]);
          setDebateChartData([]);
          setApiCallChartData([]);
        }
      } catch {
        // Clear chart data on network error - show empty state
        setTokenChartData([]);
        setDebateChartData([]);
        setApiCallChartData([]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch billing data');
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api, token, timeRange]);

  useEffect(() => {
    if (isAuthenticated) {
      fetchData();
    }
  }, [fetchData, isAuthenticated]);

  const handleTimeRangeChange = (range: TimeRange) => {
    setTimeRange(range);
  };

  const handleUpgrade = async (tier: string) => {
    if (!token) return;

    try {
      const res = await fetch(`${backendConfig.api}/api/billing/checkout`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ tier }),
      });

      if (res.ok) {
        const data = await res.json();
        if (data.checkout_url) {
          window.location.href = data.checkout_url;
        }
      } else {
        throw new Error('Failed to create checkout session');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start upgrade');
    }
  };

  const usagePercent = planInfo
    ? Math.min(100, (planInfo.debates_used / planInfo.debates_limit) * 100)
    : 0;

  return (
    <AdminLayout
      title="Usage & Billing"
      description="Monitor usage metrics, view invoices, and manage your subscription."
      actions={
        <button
          onClick={fetchData}
          disabled={loading}
          className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
        >
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      }
    >
      {error && (
        <div className="card p-4 mb-6 border-acid-red/40 bg-acid-red/10">
          <p className="text-acid-red font-theme-data text-sm">{error}</p>
        </div>
      )}

      {/* Current Period Summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4 mb-6">
        <div className="card p-4">
          <div className="font-theme-data text-xs text-text-muted mb-1">Current Plan</div>
          <div className="font-theme-data text-xl text-[var(--accent)] capitalize">
            {planInfo?.current_tier?.replace('_', ' ') || '-'}
          </div>
        </div>
        <div className="card p-4">
          <div className="font-theme-data text-xs text-text-muted mb-1">Debates Used</div>
          <div className="font-theme-data text-xl text-[var(--acid-cyan)]">
            {planInfo?.debates_used || 0}/{planInfo?.debates_limit || '-'}
          </div>
          <div className="mt-2 h-1.5 bg-bg rounded overflow-hidden">
            <div
              className={`h-full transition-all ${usagePercent >= 90 ? 'bg-acid-red' : usagePercent >= 70 ? 'bg-acid-yellow' : 'bg-[var(--accent)]'}`}
              style={{ width: `${usagePercent}%` }}
            />
          </div>
        </div>
        <div className="card p-4">
          <div className="font-theme-data text-xs text-text-muted mb-1">Tokens Used</div>
          <div className="font-theme-data text-xl text-text">
            {usage?.tokens_used?.toLocaleString() || '-'}
          </div>
        </div>
        <div className="card p-4">
          <div className="font-theme-data text-xs text-text-muted mb-1">API Calls</div>
          <div className="font-theme-data text-xl text-text">
            {usage?.api_calls?.toLocaleString() || '-'}
          </div>
        </div>
        <div className="card p-4">
          <div className="font-theme-data text-xs text-text-muted mb-1">Estimated Cost</div>
          <div className="font-theme-data text-xl text-[var(--acid-yellow)]">
            ${usage?.estimated_cost_usd?.toFixed(2) || '0.00'}
          </div>
        </div>
        <div className="card p-4">
          <div className="font-theme-data text-xs text-text-muted mb-1">Next Billing</div>
          <div className="font-theme-data text-lg text-text-muted">
            {planInfo?.next_billing_date
              ? new Date(planInfo.next_billing_date).toLocaleDateString()
              : '-'}
          </div>
        </div>
      </div>

      {/* Tab Navigation */}
      <div className="flex gap-2 border-b border-[var(--accent)]/20 pb-2 mb-6">
        {(['usage', 'invoices', 'plans'] as const).map((tab) => (
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

      {/* Usage Tab */}
      {activeTab === 'usage' && (
        <div className="space-y-6">
          {/* Charts */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <UsageChart
              title="TOKEN USAGE"
              data={tokenChartData}
              type="line"
              color="acid-cyan"
              loading={loading}
              height={240}
              showTimeRangeSelector={true}
              defaultTimeRange={timeRange}
              onTimeRangeChange={handleTimeRangeChange}
              formatValue={(v) => v.toLocaleString()}
            />
            <UsageChart
              title="DEBATES"
              data={debateChartData}
              type="bar"
              color="acid-green"
              loading={loading}
              height={240}
              showTimeRangeSelector={false}
            />
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <UsageChart
              title="API CALLS"
              data={apiCallChartData}
              type="line"
              color="acid-yellow"
              loading={loading}
              height={240}
              showTimeRangeSelector={false}
              formatValue={(v) => v.toLocaleString()}
            />
            <div className="card p-6">
              <h3 className="font-theme-data text-[var(--accent)] mb-4">TOKEN BREAKDOWN</h3>
              {usage ? (
                <div className="space-y-4">
                  <div className="flex justify-between items-center">
                    <span className="font-theme-data text-sm text-text-muted">Input Tokens</span>
                    <span className="font-theme-data text-sm text-text">
                      {usage.tokens_in?.toLocaleString() || 0}
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="font-theme-data text-sm text-text-muted">Output Tokens</span>
                    <span className="font-theme-data text-sm text-text">
                      {usage.tokens_out?.toLocaleString() || 0}
                    </span>
                  </div>
                  <div className="flex justify-between items-center pt-4 border-t border-[var(--accent)]/20">
                    <span className="font-theme-data text-sm text-text-muted">Total</span>
                    <span className="font-theme-data text-sm text-[var(--acid-cyan)]">
                      {usage.tokens_used?.toLocaleString() || 0}
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="font-theme-data text-sm text-text-muted">Total Debates</span>
                    <span className="font-theme-data text-sm text-text">{usage.debates_count}</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="font-theme-data text-sm text-text-muted">Period</span>
                    <span className="font-theme-data text-xs text-text-muted">
                      {usage.period_start && new Date(usage.period_start).toLocaleDateString()} -
                      {usage.period_end && new Date(usage.period_end).toLocaleDateString()}
                    </span>
                  </div>
                </div>
              ) : (
                <div className="font-theme-data text-sm text-text-muted">Loading...</div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Invoices Tab */}
      {activeTab === 'invoices' && (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-surface border-b border-[var(--accent)]/20">
                <tr>
                  <th className="text-left px-4 py-3 font-theme-data text-xs text-text-muted">
                    INVOICE
                  </th>
                  <th className="text-left px-4 py-3 font-theme-data text-xs text-text-muted">
                    PERIOD
                  </th>
                  <th className="text-left px-4 py-3 font-theme-data text-xs text-text-muted">
                    AMOUNT
                  </th>
                  <th className="text-left px-4 py-3 font-theme-data text-xs text-text-muted">
                    STATUS
                  </th>
                  <th className="text-left px-4 py-3 font-theme-data text-xs text-text-muted">
                    DATE
                  </th>
                  <th className="text-left px-4 py-3 font-theme-data text-xs text-text-muted">
                    ACTIONS
                  </th>
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center">
                      <div className="font-theme-data text-text-muted animate-pulse">
                        Loading...
                      </div>
                    </td>
                  </tr>
                )}
                {!loading && invoices.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center">
                      <div className="font-theme-data text-text-muted">No invoices found</div>
                    </td>
                  </tr>
                )}
                {!loading &&
                  invoices.map((invoice) => (
                    <tr
                      key={invoice.id}
                      className="border-b border-[var(--accent)]/10 hover:bg-surface/50"
                    >
                      <td className="px-4 py-3">
                        <div className="font-theme-data text-sm text-[var(--acid-cyan)]">
                          {invoice.number}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-theme-data text-xs text-text-muted">
                          {new Date(invoice.period_start).toLocaleDateString()} -
                          {new Date(invoice.period_end).toLocaleDateString()}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-theme-data text-sm text-text">
                          {formatCurrency(invoice.amount_due, invoice.currency)}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={invoice.status} />
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-theme-data text-xs text-text-muted">
                          {new Date(invoice.created_at).toLocaleDateString()}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        {invoice.pdf_url && (
                          <a
                            href={invoice.pdf_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="font-theme-data text-xs text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
                          >
                            Download PDF
                          </a>
                        )}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Plans Tab */}
      {activeTab === 'plans' && (
        <div>
          <div className="mb-6">
            <p className="font-theme-data text-sm text-text-muted">
              Choose the plan that best fits your needs. Upgrade or downgrade anytime.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {Object.keys(TIER_PRICES).map((tier) => (
              <TierCard
                key={tier}
                tier={tier}
                current={planInfo?.current_tier === tier}
                onUpgrade={handleUpgrade}
              />
            ))}
          </div>

          {/* Upgrade CTA */}
          {planInfo?.current_tier && planInfo.current_tier !== 'enterprise' && (
            <div className="mt-8 card p-6 border-acid-yellow/40 bg-acid-yellow/5">
              <div className="flex items-center justify-between flex-wrap gap-4">
                <div>
                  <h3 className="font-theme-data text-lg text-[var(--acid-yellow)] mb-1">
                    Need more power?
                  </h3>
                  <p className="font-theme-data text-sm text-text-muted">
                    Contact sales for Enterprise pricing with unlimited debates, SSO, and dedicated
                    support.
                  </p>
                </div>
                <a
                  href="mailto:sales@aragora.ai?subject=Enterprise%20Inquiry"
                  className="px-6 py-3 bg-acid-yellow/20 border border-acid-yellow/40 text-[var(--acid-yellow)] font-theme-data text-sm rounded hover:bg-acid-yellow/30 transition-colors"
                >
                  Contact Sales
                </a>
              </div>
            </div>
          )}
        </div>
      )}
    </AdminLayout>
  );
}
