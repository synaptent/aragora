'use client';

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import { useAuth } from '@/context/AuthContext';
import { API_BASE_URL } from '@/config';
import { logger } from '@/utils/logger';

const API_BASE = API_BASE_URL;

interface PlanStatus {
  tier: string;
  is_trial: boolean;
  trial_days_remaining: number | null;
  debates_used: number;
  debates_limit: number;
  is_expired: boolean;
}

export function TrialStatusWidget() {
  const { isAuthenticated, tokens } = useAuth();
  const [plan, setPlan] = useState<PlanStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const accessToken = tokens?.access_token;

  const fetchPlan = useCallback(async () => {
    if (!accessToken) return;
    try {
      const res = await fetch(`${API_BASE}/api/billing/plan`, {
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (res.ok) {
        const data = await res.json();
        setPlan(data.plan);
      }
    } catch (err) {
      logger.error('Failed to fetch plan status:', err);
    } finally {
      setLoading(false);
    }
  }, [accessToken]);

  useEffect(() => {
    if (isAuthenticated) {
      fetchPlan();
    }
  }, [fetchPlan, isAuthenticated]);

  if (loading || !plan) return null;

  // Don't show for paid tiers (non-trial)
  if (!plan.is_trial && plan.tier !== 'free') return null;

  const usagePercent =
    plan.debates_limit > 0 ? Math.min(100, (plan.debates_used / plan.debates_limit) * 100) : 0;

  const isNearLimit = usagePercent >= 80;
  const isAtLimit = usagePercent >= 100;

  return (
    <div
      className={`bg-[var(--surface)] border ${
        plan.is_expired || isAtLimit
          ? 'border-red-500/40 bg-red-500/5'
          : isNearLimit
            ? 'border-yellow-500/40 bg-yellow-500/5'
            : 'border-[var(--acid-cyan)]/30'
      } p-4`}
    >
      <div className="flex items-center justify-between flex-wrap gap-4">
        {/* Left: Status info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 mb-2">
            <span className="text-xs font-theme-data text-[var(--text-muted)]">
              {'>'} SUBSCRIPTION
            </span>
            <span className="px-2 py-0.5 text-[10px] font-theme-data uppercase bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/30">
              {plan.tier.replace('_', ' ')}
              {plan.is_trial ? ' TRIAL' : ''}
            </span>
            {plan.is_expired && (
              <span className="px-2 py-0.5 text-[10px] font-theme-data bg-red-500/20 text-red-400 border border-red-500/30">
                EXPIRED
              </span>
            )}
          </div>

          {/* Usage bar */}
          <div className="flex items-center gap-3">
            <div className="flex-1 max-w-xs">
              <div className="h-2 bg-[var(--bg)] rounded overflow-hidden">
                <div
                  className={`h-full transition-all duration-500 ${
                    isAtLimit
                      ? 'bg-red-500'
                      : isNearLimit
                        ? 'bg-yellow-500'
                        : 'bg-[var(--acid-green)]'
                  }`}
                  style={{ width: `${usagePercent}%` }}
                />
              </div>
            </div>
            <span className="text-xs font-theme-data text-[var(--text-muted)] whitespace-nowrap">
              {plan.debates_used}/{plan.debates_limit} debates
            </span>
            {plan.is_trial && plan.trial_days_remaining !== null && (
              <span
                className={`text-xs font-theme-data whitespace-nowrap ${
                  plan.trial_days_remaining <= 3 ? 'text-red-400' : 'text-[var(--acid-cyan)]'
                }`}
              >
                {plan.trial_days_remaining}d remaining
              </span>
            )}
          </div>
        </div>

        {/* Right: Upgrade CTA */}
        <Link
          href="/pricing"
          className="px-4 py-2 text-xs font-theme-data font-bold bg-[var(--acid-green)] text-[var(--bg)] hover:brightness-110 transition-all whitespace-nowrap"
        >
          UPGRADE TO PRO
        </Link>
      </div>

      {/* Warning messages */}
      {plan.is_expired && (
        <div className="mt-3 pt-3 border-t border-red-500/20">
          <p className="text-xs font-theme-data text-red-400">
            Your trial has expired. Upgrade to continue using Aragora with full features.
          </p>
        </div>
      )}
      {isAtLimit && !plan.is_expired && (
        <div className="mt-3 pt-3 border-t border-red-500/20">
          <p className="text-xs font-theme-data text-red-400">
            You&apos;ve reached your monthly debate limit. Upgrade for more debates.
          </p>
        </div>
      )}
    </div>
  );
}
