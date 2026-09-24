'use client';

import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL } from '@/config';
import { useAuth } from '@/context/AuthContext';
import { logger } from '@/utils/logger';
import {
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Area,
  ComposedChart,
  ReferenceLine,
} from 'recharts';

interface DailyForecast {
  date: string;
  predicted_cost: string;
  lower_bound: string;
  upper_bound: string;
  confidence: number;
}

interface TrendAnalysis {
  direction: 'increasing' | 'decreasing' | 'stable';
  change_rate_daily: number;
  change_rate_weekly: number;
  r_squared: number;
  description: string;
}

interface ForecastAlert {
  id: string;
  severity: 'info' | 'warning' | 'critical';
  title: string;
  message: string;
  metric: string;
}

interface ForecastData {
  workspace_id: string;
  predictions: { monthly_cost: string; daily_average: string; confidence_interval: number };
  trend: TrendAnalysis | null;
  seasonal_pattern: string;
  daily_forecasts: DailyForecast[];
  alerts: ForecastAlert[];
  budget: {
    limit: string | null;
    projected_usage_percent: number | null;
    days_until_exceeded: number | null;
  };
}

interface Props {
  workspaceId?: string;
  forecastDays?: number;
}

const SEVERITY_COLORS = {
  info: 'border-blue-500 bg-blue-500/10 text-blue-400',
  warning: 'border-yellow-500 bg-yellow-500/10 text-yellow-400',
  critical: 'border-red-500 bg-red-500/10 text-red-400',
};

export function BudgetForecast({ workspaceId = 'default', forecastDays = 30 }: Props) {
  const { isAuthenticated, tokens } = useAuth();
  const [data, setData] = useState<ForecastData | null>(null);
  const [loading, setLoading] = useState(true);
  const [showSimulation, setShowSimulation] = useState(false);

  const fetchForecast = useCallback(async () => {
    if (!isAuthenticated) {
      setLoading(false);
      return;
    }

    setLoading(true);
    try {
      const headers: HeadersInit = { 'Content-Type': 'application/json' };
      if (tokens?.access_token) {
        headers['Authorization'] = `Bearer ${tokens.access_token}`;
      }

      const response = await fetch(
        `/api/costs/forecast?workspace_id=${workspaceId}&days=${forecastDays}`,
        { headers },
      );

      if (response.ok) {
        const result = await response.json();
        setData(result);
      }
    } catch (error) {
      logger.error('Failed to fetch forecast:', error);
    } finally {
      setLoading(false);
    }
  }, [isAuthenticated, tokens?.access_token, workspaceId, forecastDays]);

  useEffect(() => {
    fetchForecast();
  }, [fetchForecast]);

  if (loading) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
        <div className="animate-pulse space-y-4">
          <div className="h-6 bg-[var(--bg)] rounded w-1/3" />
          <div className="h-64 bg-[var(--bg)] rounded" />
        </div>
      </div>
    );
  }

  if (!data || data.daily_forecasts.length === 0) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)] mb-4">
          {'>'} COST FORECAST
        </h3>
        <div className="text-center py-8 text-[var(--text-muted)]">
          <div className="text-2xl mb-2">📊</div>
          <div className="text-sm">Insufficient data for forecasting</div>
          <div className="text-xs mt-1">Need at least 3 days of usage data</div>
        </div>
      </div>
    );
  }

  const chartData = data.daily_forecasts.map((f) => ({
    date: f.date,
    predicted: parseFloat(f.predicted_cost),
    lower: parseFloat(f.lower_bound),
    upper: parseFloat(f.upper_bound),
    confidence: f.confidence,
  }));

  const budgetLimit = data.budget.limit ? parseFloat(data.budget.limit) / forecastDays : null;

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)]">
          {'>'} COST FORECAST ({forecastDays} days)
        </h3>
        <button
          onClick={() => setShowSimulation(!showSimulation)}
          className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
        >
          {showSimulation ? 'Hide' : 'Show'} Simulation
        </button>
      </div>

      {/* Alerts */}
      {data.alerts.length > 0 && (
        <div className="space-y-2">
          {data.alerts.slice(0, 2).map((alert) => (
            <div key={alert.id} className={`border rounded p-3 ${SEVERITY_COLORS[alert.severity]}`}>
              <div className="flex items-center gap-2">
                <span className="text-sm font-theme-data">{alert.title}</span>
              </div>
              <div className="text-xs mt-1 opacity-80">{alert.message}</div>
            </div>
          ))}
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-[var(--bg)] rounded p-3">
          <div className="text-lg font-theme-data text-[var(--acid-green)]">
            ${parseFloat(data.predictions.monthly_cost).toFixed(2)}
          </div>
          <div className="text-xs text-[var(--text-muted)]">Projected Monthly</div>
        </div>
        <div className="bg-[var(--bg)] rounded p-3">
          <div className="text-lg font-theme-data text-[var(--acid-cyan)]">
            ${parseFloat(data.predictions.daily_average).toFixed(2)}
          </div>
          <div className="text-xs text-[var(--text-muted)]">Daily Average</div>
        </div>
        <div className="bg-[var(--bg)] rounded p-3">
          <div
            className={`text-lg font-theme-data ${
              data.budget.projected_usage_percent && data.budget.projected_usage_percent >= 100
                ? 'text-red-400'
                : data.budget.projected_usage_percent && data.budget.projected_usage_percent >= 80
                  ? 'text-yellow-400'
                  : 'text-green-400'
            }`}
          >
            {data.budget.projected_usage_percent
              ? `${data.budget.projected_usage_percent.toFixed(0)}%`
              : 'N/A'}
          </div>
          <div className="text-xs text-[var(--text-muted)]">Budget Usage</div>
        </div>
      </div>

      {/* Trend Analysis */}
      {data.trend && (
        <div className="flex items-center gap-4 text-xs text-[var(--text-muted)]">
          <span
            className={`font-theme-data ${
              data.trend.direction === 'increasing'
                ? 'text-red-400'
                : data.trend.direction === 'decreasing'
                  ? 'text-green-400'
                  : 'text-gray-400'
            }`}
          >
            {data.trend.direction === 'increasing'
              ? '↑'
              : data.trend.direction === 'decreasing'
                ? '↓'
                : '→'}{' '}
            {Math.abs(data.trend.change_rate_weekly).toFixed(1)}%/week
          </span>
          <span>{data.trend.description}</span>
        </div>
      )}

      {/* Forecast Chart */}
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.3} />
            <XAxis
              dataKey="date"
              tick={{ fill: 'var(--text-muted)', fontSize: 10 }}
              tickFormatter={(value) => {
                const date = new Date(value);
                return `${date.getMonth() + 1}/${date.getDate()}`;
              }}
            />
            <YAxis
              tick={{ fill: 'var(--text-muted)', fontSize: 10 }}
              tickFormatter={(value) => `$${value}`}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: 'var(--surface)',
                border: '1px solid var(--border)',
                borderRadius: '4px',
              }}
              labelStyle={{ color: 'var(--text)' }}
              formatter={(value, name) => {
                if (typeof value !== 'number') return ['-', String(name)];
                const labels: Record<string, string> = {
                  predicted: 'Predicted',
                  upper: 'Upper Bound',
                  lower: 'Lower Bound',
                };
                return [`$${value.toFixed(2)}`, labels[String(name)] || String(name)];
              }}
            />

            {/* Confidence Interval */}
            <Area type="monotone" dataKey="upper" stroke="none" fill="#00ff9d" fillOpacity={0.1} />
            <Area type="monotone" dataKey="lower" stroke="none" fill="var(--bg)" fillOpacity={1} />

            {/* Budget Line */}
            {budgetLimit && (
              <ReferenceLine
                y={budgetLimit}
                stroke="#ff6b6b"
                strokeDasharray="5 5"
                label={{ value: 'Budget', fill: '#ff6b6b', fontSize: 10, position: 'right' }}
              />
            )}

            {/* Predicted Line */}
            <Line
              type="monotone"
              dataKey="predicted"
              stroke="#00ff9d"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, fill: '#00ff9d' }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Simulation Panel */}
      {showSimulation && <SimulationPanel workspaceId={workspaceId} />}

      {/* Budget Runway */}
      {data.budget.days_until_exceeded !== null && (
        <div
          className={`text-center py-2 rounded ${
            data.budget.days_until_exceeded <= 5
              ? 'bg-red-500/10 text-red-400'
              : data.budget.days_until_exceeded <= 10
                ? 'bg-yellow-500/10 text-yellow-400'
                : 'bg-green-500/10 text-green-400'
          }`}
        >
          <span className="text-sm font-theme-data">
            {data.budget.days_until_exceeded === 0
              ? 'Budget exhausted!'
              : `${data.budget.days_until_exceeded} days until budget exhausted`}
          </span>
        </div>
      )}
    </div>
  );
}

interface SimulationPanelProps {
  workspaceId: string;
}

function SimulationPanel({ workspaceId }: SimulationPanelProps) {
  const { tokens } = useAuth();
  const apiBase = API_BASE_URL;
  const [scenario, setScenario] = useState({
    name: 'Custom Scenario',
    changes: { model_change: '', request_reduction: 0 },
  });
  const [result, setResult] = useState<{
    baseline_cost: string;
    simulated_cost: string;
    percentage_change: number;
  } | null>(null);
  const [simulating, setSimulating] = useState(false);

  const runSimulation = async () => {
    setSimulating(true);
    try {
      const headers: HeadersInit = { 'Content-Type': 'application/json' };
      if (tokens?.access_token) {
        headers['Authorization'] = `Bearer ${tokens.access_token}`;
      }

      const changes: Record<string, unknown> = {};
      if (scenario.changes.model_change) {
        changes.model_change = scenario.changes.model_change;
      }
      if (scenario.changes.request_reduction > 0) {
        changes.request_reduction = scenario.changes.request_reduction / 100;
      }

      const response = await fetch(`${apiBase}/api/costs/forecast/simulate`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          workspace_id: workspaceId,
          scenario: { name: scenario.name, description: 'Custom what-if scenario', changes },
          days: 30,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        setResult({
          baseline_cost: data.baseline_cost,
          simulated_cost: data.simulated_cost,
          percentage_change: data.percentage_change,
        });
      }
    } catch (error) {
      logger.error('Simulation failed:', error);
    } finally {
      setSimulating(false);
    }
  };

  return (
    <div className="border-t border-[var(--border)] pt-4 space-y-4">
      <h4 className="text-xs font-theme-data text-[var(--text-muted)]">WHAT-IF SIMULATION</h4>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-xs text-[var(--text-muted)] block mb-1">Model Change</label>
          <select
            value={scenario.changes.model_change}
            onChange={(e) =>
              setScenario((s) => ({
                ...s,
                changes: { ...s.changes, model_change: e.target.value },
              }))
            }
            className="w-full bg-[var(--bg)] border border-[var(--border)] rounded px-2 py-1 text-xs font-theme-data text-[var(--text)]"
          >
            <option value="">No change</option>
            <option value="haiku">Switch to Haiku</option>
            <option value="mini">Switch to GPT-4o-mini</option>
            <option value="sonnet">Switch to Sonnet</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-[var(--text-muted)] block mb-1">
            Request Reduction: {scenario.changes.request_reduction}%
          </label>
          <input
            type="range"
            min="0"
            max="50"
            value={scenario.changes.request_reduction}
            onChange={(e) =>
              setScenario((s) => ({
                ...s,
                changes: { ...s.changes, request_reduction: parseInt(e.target.value) },
              }))
            }
            className="w-full"
          />
        </div>
      </div>

      <button
        onClick={runSimulation}
        disabled={simulating}
        className="w-full py-2 text-xs font-theme-data bg-[var(--acid-green)]/20 text-[var(--acid-green)] border border-[var(--acid-green)]/30 rounded hover:bg-[var(--acid-green)]/30 disabled:opacity-50 transition-colors"
      >
        {simulating ? 'Simulating...' : 'Run Simulation'}
      </button>

      {result && (
        <div className="bg-[var(--bg)] rounded p-3">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs text-[var(--text-muted)]">Baseline</div>
              <div className="text-sm font-theme-data text-[var(--text)]">
                ${parseFloat(result.baseline_cost).toFixed(2)}
              </div>
            </div>
            <div className="text-xl">→</div>
            <div>
              <div className="text-xs text-[var(--text-muted)]">Simulated</div>
              <div className="text-sm font-theme-data text-[var(--acid-green)]">
                ${parseFloat(result.simulated_cost).toFixed(2)}
              </div>
            </div>
            <div
              className={`text-lg font-theme-data ${
                result.percentage_change > 0 ? 'text-green-400' : 'text-red-400'
              }`}
            >
              {result.percentage_change > 0 ? '-' : '+'}
              {Math.abs(result.percentage_change).toFixed(0)}%
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default BudgetForecast;
