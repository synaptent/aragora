'use client';

import { useState, useEffect, useCallback } from 'react';
import { useBackend } from '@/components/BackendSelector';
import { useAuth } from '@/context/AuthContext';

interface CostSummary {
  totalCost: number;
  budget: number;
  tokensUsed: number;
  apiCalls: number;
  lastUpdated: string;
  costByProvider: { name: string; cost: number; percentage: number }[];
  costByFeature: { name: string; cost: number; percentage: number }[];
  dailyCosts: { date: string; cost: number }[];
  alerts: { id: string; type: string; message: string; severity: string }[];
}

const PERIOD_TO_RANGE = { day: '24h', week: '7d', month: '30d' } as const;

function UsageChart({ data, label }: { data: { date: string; cost: number }[]; label: string }) {
  if (!data || data.length === 0) {
    return (
      <div className="space-y-1">
        <div className="text-sm font-medium text-gray-700">{label}</div>
        <div className="flex items-center justify-center h-20 text-gray-400 text-sm">
          No data available
        </div>
      </div>
    );
  }
  const max = Math.max(...data.map((d) => d.cost), 1);
  return (
    <div className="space-y-1">
      <div className="text-sm font-medium text-gray-700">{label}</div>
      <div className="flex items-end gap-1 h-20">
        {data.map((item, i) => (
          <div
            key={i}
            className="flex-1 bg-blue-500 rounded-t transition-all hover:bg-blue-600"
            style={{ height: `${(item.cost / max) * 100}%` }}
            title={`${item.date}: $${item.cost.toFixed(2)}`}
          />
        ))}
      </div>
    </div>
  );
}

function MetricCard({
  title,
  value,
  unit,
  loading,
}: {
  title: string;
  value: number;
  unit?: string;
  loading?: boolean;
}) {
  return (
    <div className="bg-white p-4 rounded-lg border">
      <div className="text-sm text-gray-500">{title}</div>
      {loading ? (
        <div className="h-8 bg-gray-200 rounded animate-pulse mt-1" />
      ) : (
        <div className="text-2xl font-bold">
          {unit === 'USD' ? `$${value.toFixed(2)}` : value.toLocaleString()}
          {unit && unit !== 'USD' && (
            <span className="text-sm font-normal text-gray-500 ml-1">{unit}</span>
          )}
        </div>
      )}
    </div>
  );
}

function BreakdownTable({
  data,
  title,
}: {
  data: { name: string; cost: number; percentage: number }[];
  title: string;
}) {
  if (!data || data.length === 0) {
    return (
      <div className="bg-white rounded-lg border p-6">
        <h2 className="text-lg font-semibold mb-4">{title}</h2>
        <div className="text-gray-400 text-sm text-center py-4">No data available</div>
      </div>
    );
  }
  return (
    <div className="bg-white rounded-lg border p-6">
      <h2 className="text-lg font-semibold mb-4">{title}</h2>
      <table className="w-full">
        <thead>
          <tr className="border-b text-left text-sm text-gray-500">
            <th className="pb-3">Name</th>
            <th className="pb-3 text-right">Cost</th>
            <th className="pb-3 text-right">%</th>
          </tr>
        </thead>
        <tbody>
          {data.map((item, idx) => (
            <tr key={idx} className="border-b last:border-b-0">
              <td className="py-3 font-medium">{item.name}</td>
              <td className="py-3 text-right">${item.cost.toFixed(2)}</td>
              <td className="py-3 text-right text-gray-500">{item.percentage.toFixed(1)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function UsageDashboard() {
  const { config: backendConfig } = useBackend();
  const { tokens } = useAuth();
  const token = tokens?.access_token;

  const [period, setPeriod] = useState<'day' | 'week' | 'month'>('month');
  const [data, setData] = useState<CostSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      const range = PERIOD_TO_RANGE[period];
      const res = await fetch(`${backendConfig.api}/api/v1/costs?range=${range}`, { headers });

      if (!res.ok) {
        throw new Error(`Failed to fetch cost data: ${res.status}`);
      }

      const json = await res.json();
      setData(json);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch data');
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api, token, period]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const budgetUsedPercent = data && data.budget > 0 ? (data.totalCost / data.budget) * 100 : 0;

  return (
    <div className="max-w-7xl mx-auto p-6">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-2xl font-bold">Usage Dashboard</h1>
          <p className="text-gray-500">Monitor platform usage and costs</p>
        </div>
        <div className="flex items-center gap-4">
          <select
            value={period}
            onChange={(e) => setPeriod(e.target.value as typeof period)}
            className="px-4 py-2 border rounded-md"
          >
            <option value="day">Last 24 Hours</option>
            <option value="week">Last 7 Days</option>
            <option value="month">Last 30 Days</option>
          </select>
          <button
            onClick={fetchData}
            disabled={loading}
            className="px-4 py-2 bg-blue-500 text-white rounded-md hover:bg-blue-600 disabled:opacity-50"
          >
            {loading ? 'Loading...' : 'Refresh'}
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-6">
          {error}
        </div>
      )}

      {/* Alerts */}
      {data?.alerts && data.alerts.length > 0 && (
        <div className="mb-6 space-y-2">
          {data.alerts.map((alert) => (
            <div
              key={alert.id}
              className={`px-4 py-3 rounded border ${
                alert.severity === 'critical'
                  ? 'bg-red-50 border-red-200 text-red-700'
                  : alert.severity === 'warning'
                    ? 'bg-yellow-50 border-yellow-200 text-yellow-700'
                    : 'bg-blue-50 border-blue-200 text-blue-700'
              }`}
            >
              <span className="font-medium">{alert.type}:</span> {alert.message}
            </div>
          ))}
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
        <MetricCard title="Total Cost" value={data?.totalCost ?? 0} unit="USD" loading={loading} />
        <MetricCard title="API Calls" value={data?.apiCalls ?? 0} loading={loading} />
        <MetricCard title="Tokens Used" value={data?.tokensUsed ?? 0} loading={loading} />
        <div className="bg-white p-4 rounded-lg border">
          <div className="text-sm text-gray-500">Budget Usage</div>
          {loading ? (
            <div className="h-8 bg-gray-200 rounded animate-pulse mt-1" />
          ) : (
            <>
              <div className="text-2xl font-bold">
                ${data?.totalCost?.toFixed(2) ?? '0.00'} / ${data?.budget?.toFixed(2) ?? '0.00'}
              </div>
              <div className="mt-2 h-2 bg-gray-200 rounded overflow-hidden">
                <div
                  className={`h-full transition-all ${
                    budgetUsedPercent >= 90
                      ? 'bg-red-500'
                      : budgetUsedPercent >= 70
                        ? 'bg-yellow-500'
                        : 'bg-green-500'
                  }`}
                  style={{ width: `${Math.min(budgetUsedPercent, 100)}%` }}
                />
              </div>
            </>
          )}
        </div>
      </div>

      {/* Cost Trends */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
        <div className="bg-white rounded-lg border p-6">
          <h2 className="text-lg font-semibold mb-4">Daily Cost Trend</h2>
          <UsageChart data={data?.dailyCosts ?? []} label="" />
        </div>
        <div className="bg-white rounded-lg border p-6">
          <h2 className="text-lg font-semibold mb-4">Cost Summary</h2>
          {loading ? (
            <div className="space-y-3">
              <div className="h-4 bg-gray-200 rounded animate-pulse" />
              <div className="h-4 bg-gray-200 rounded animate-pulse w-3/4" />
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-gray-500">Total Cost</span>
                <span className="font-medium">${data?.totalCost?.toFixed(2) ?? '0.00'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Monthly Budget</span>
                <span className="font-medium">${data?.budget?.toFixed(2) ?? '0.00'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">API Calls</span>
                <span className="font-medium">{data?.apiCalls?.toLocaleString() ?? 0}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Tokens Used</span>
                <span className="font-medium">{data?.tokensUsed?.toLocaleString() ?? 0}</span>
              </div>
              <div className="flex justify-between text-sm text-gray-400">
                <span>Last Updated</span>
                <span>{data?.lastUpdated ? new Date(data.lastUpdated).toLocaleString() : '-'}</span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Breakdowns */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <BreakdownTable data={data?.costByProvider ?? []} title="Cost by Provider" />
        <BreakdownTable data={data?.costByFeature ?? []} title="Cost by Feature" />
      </div>
    </div>
  );
}
