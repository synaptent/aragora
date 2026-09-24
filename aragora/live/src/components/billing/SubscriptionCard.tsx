'use client';

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import { useAuth } from '@/context/AuthContext';
import { API_BASE_URL } from '@/config';
import { logger } from '@/utils/logger';

const API_BASE = API_BASE_URL;

interface SubscriptionData {
  tier: string;
  status: string;
  is_active: boolean;
  current_period_end?: string;
  cancel_at_period_end?: boolean;
}

interface SubscriptionCardProps {
  compact?: boolean;
  showActions?: boolean;
  className?: string;
}

export function SubscriptionCard({
  compact = false,
  showActions = true,
  className = '',
}: SubscriptionCardProps) {
  const { isAuthenticated, tokens } = useAuth();
  const [subscription, setSubscription] = useState<SubscriptionData | null>(null);
  const [loading, setLoading] = useState(true);
  const accessToken = tokens?.access_token;

  const fetchSubscription = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/billing/subscription`, {
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (res.ok) {
        const data = await res.json();
        setSubscription(data.subscription);
      }
    } catch (err) {
      logger.error('Failed to fetch subscription:', err);
    } finally {
      setLoading(false);
    }
  }, [accessToken]);

  useEffect(() => {
    if (isAuthenticated && accessToken) {
      fetchSubscription();
    } else {
      setLoading(false);
    }
  }, [isAuthenticated, accessToken, fetchSubscription]);

  if (!isAuthenticated) return null;

  const tierColors: Record<string, string> = {
    free: 'text-text-muted',
    starter: 'text-[var(--acid-cyan)]',
    professional: 'text-[var(--accent)]',
    enterprise: 'text-[var(--acid-magenta)]',
  };

  if (compact) {
    return (
      <div className={`font-theme-data text-xs flex items-center gap-2 ${className}`}>
        <span className="text-text-muted">Plan:</span>
        <span className={tierColors[subscription?.tier || 'free'] || 'text-text'}>
          {(subscription?.tier || 'FREE').toUpperCase()}
        </span>
        {subscription?.cancel_at_period_end && <span className="text-warning">(canceling)</span>}
      </div>
    );
  }

  return (
    <div className={`border border-[var(--accent)]/30 bg-surface/30 p-4 ${className}`}>
      <h3 className="text-sm font-theme-data text-[var(--acid-cyan)] mb-3">SUBSCRIPTION</h3>

      {loading ? (
        <div className="text-xs font-theme-data text-text-muted">Loading...</div>
      ) : (
        <div className="space-y-3">
          {/* Tier display */}
          <div>
            <div
              className={`text-lg font-theme-data uppercase ${tierColors[subscription?.tier || 'free']}`}
            >
              {subscription?.tier || 'FREE'}
            </div>
            <div className="text-xs font-theme-data text-text-muted">
              Status:{' '}
              {subscription?.is_active ? (
                <span className="text-[var(--accent)]">Active</span>
              ) : (
                <span className="text-warning">Inactive</span>
              )}
            </div>
          </div>

          {/* Cancellation notice */}
          {subscription?.cancel_at_period_end && (
            <div className="text-xs font-theme-data text-warning bg-warning/10 p-2 border border-warning/30">
              Subscription will cancel at period end
            </div>
          )}

          {/* Actions */}
          {showActions && (
            <div className="pt-2 space-y-2">
              <Link
                href="/billing"
                className="block text-center py-2 text-xs font-theme-data border border-[var(--accent)]/50 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors"
              >
                MANAGE BILLING
              </Link>
              {subscription?.tier === 'free' && (
                <Link
                  href="/pricing"
                  className="block text-center py-2 text-xs font-theme-data bg-[var(--accent)] text-bg hover:bg-[var(--accent)]/80 transition-colors"
                >
                  UPGRADE
                </Link>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default SubscriptionCard;
