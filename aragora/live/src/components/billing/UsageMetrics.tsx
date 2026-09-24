'use client';

import { useEffect, useState, useCallback } from 'react';
import { useAuth } from '@/context/AuthContext';
import { API_BASE_URL } from '@/config';
import { logger } from '@/utils/logger';

const API_BASE = API_BASE_URL;

interface UsageData {
  debates_used: number;
  debates_limit: number;
  debates_remaining: number;
  tokens_used: number;
  tokens_in?: number;
  tokens_out?: number;
  estimated_cost_usd: number;
  cost_breakdown?: { input_cost: number; output_cost: number; total: number };
  period_start: string | null;
}

interface UsageMetricsProps {
  compact?: boolean;
  className?: string;
}

export function UsageMetrics({ compact = false, className = '' }: UsageMetricsProps) {
  const { isAuthenticated, tokens } = useAuth();
  const [usage, setUsage] = useState<UsageData | null>(null);
  const [loading, setLoading] = useState(true);
  const accessToken = tokens?.access_token;

  const fetchUsage = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/billing/usage`, {
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (res.ok) {
        const data = await res.json();
        setUsage(data.usage);
      }
    } catch (err) {
      logger.error('Failed to fetch usage:', err);
    } finally {
      setLoading(false);
    }
  }, [accessToken]);

  useEffect(() => {
    if (isAuthenticated && accessToken) {
      fetchUsage();
    } else {
      setLoading(false);
    }
  }, [isAuthenticated, accessToken, fetchUsage]);

  if (!isAuthenticated) return null;

  const usagePercent = usage ? Math.min(100, (usage.debates_used / usage.debates_limit) * 100) : 0;

  const getBarColor = () => {
    if (usagePercent >= 90) return 'bg-warning';
    if (usagePercent >= 75) return 'bg-[var(--acid-cyan)]';
    return 'bg-[var(--accent)]';
  };

  if (compact) {
    return (
      <div className={`font-theme-data text-xs ${className}`}>
        <div className="flex items-center gap-2">
          <div className="w-16 h-1.5 bg-surface border border-[var(--accent)]/20">
            <div
              className={`h-full transition-all ${getBarColor()}`}
              style={{ width: `${usagePercent}%` }}
            />
          </div>
          <span className="text-text-muted">
            {usage?.debates_used ?? '-'}/{usage?.debates_limit ?? '-'}
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className={`border border-[var(--accent)]/30 bg-surface/30 p-4 ${className}`}>
      <h3 className="text-sm font-theme-data text-[var(--acid-cyan)] mb-3">USAGE THIS MONTH</h3>

      {loading ? (
        <div className="text-xs font-theme-data text-text-muted">Loading...</div>
      ) : usage ? (
        <div className="space-y-3">
          {/* Debates usage bar */}
          <div>
            <div className="flex justify-between text-xs font-theme-data mb-1">
              <span className="text-text-muted">Debates</span>
              <span className="text-text">
                {usage.debates_used} / {usage.debates_limit}
              </span>
            </div>
            <div className="h-2 bg-surface border border-[var(--accent)]/20">
              <div
                className={`h-full transition-all ${getBarColor()}`}
                style={{ width: `${usagePercent}%` }}
              />
            </div>
            <div className="text-xs font-theme-data text-text-muted mt-1">
              {usage.debates_remaining} remaining
            </div>
          </div>

          {/* Token usage */}
          {usage.tokens_used > 0 && (
            <div className="pt-2 border-t border-[var(--accent)]/10">
              <div className="flex justify-between text-xs font-theme-data">
                <span className="text-text-muted">Total Tokens</span>
                <span className="text-text">{usage.tokens_used.toLocaleString()}</span>
              </div>

              {/* Detailed token breakdown */}
              {(usage.tokens_in !== undefined || usage.tokens_out !== undefined) && (
                <div className="mt-2 space-y-1 pl-2 border-l border-[var(--accent)]/10">
                  <div className="flex justify-between text-xs font-theme-data">
                    <span className="text-text-muted">Input</span>
                    <span className="text-text-muted">
                      {(usage.tokens_in ?? 0).toLocaleString()}
                    </span>
                  </div>
                  <div className="flex justify-between text-xs font-theme-data">
                    <span className="text-text-muted">Output</span>
                    <span className="text-text-muted">
                      {(usage.tokens_out ?? 0).toLocaleString()}
                    </span>
                  </div>
                </div>
              )}

              {/* Cost breakdown */}
              <div className="mt-2">
                {usage.cost_breakdown ? (
                  <div className="space-y-1">
                    <div className="flex justify-between text-xs font-theme-data">
                      <span className="text-text-muted">Input Cost</span>
                      <span className="text-text-muted">
                        ${usage.cost_breakdown.input_cost.toFixed(4)}
                      </span>
                    </div>
                    <div className="flex justify-between text-xs font-theme-data">
                      <span className="text-text-muted">Output Cost</span>
                      <span className="text-text-muted">
                        ${usage.cost_breakdown.output_cost.toFixed(4)}
                      </span>
                    </div>
                    <div className="flex justify-between text-xs font-theme-data pt-1 border-t border-[var(--accent)]/10">
                      <span className="text-text-muted">Total Cost</span>
                      <span className="text-[var(--acid-cyan)]">
                        ${usage.cost_breakdown.total.toFixed(2)}
                      </span>
                    </div>
                  </div>
                ) : (
                  <div className="flex justify-between text-xs font-theme-data">
                    <span className="text-text-muted">Est. Cost</span>
                    <span className="text-[var(--acid-cyan)]">
                      ${usage.estimated_cost_usd.toFixed(2)}
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="text-xs font-theme-data text-text-muted">No usage data</div>
      )}
    </div>
  );
}

export default UsageMetrics;
