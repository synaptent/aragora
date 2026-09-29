'use client';

import { useEffect, useState, useCallback } from 'react';
import { logger } from '@/utils/logger';

interface InboxStats {
  urgent_count: number;
  high_priority_count: number;
  action_required_count: number;
  unread_count: number;
  total_count: number;
  avg_response_time_hours?: number;
  overdue_count?: number;
}

interface InboxStatsCardsProps {
  apiBase: string;
  userId: string;
  authToken?: string;
  refreshInterval?: number; // ms, default 30000
}

interface StatCardProps {
  label: string;
  value: number;
  color: string;
  bgColor: string;
  icon: string;
  subtext?: string;
}

function StatCard({ label, value, color, bgColor, icon, subtext }: StatCardProps) {
  return (
    <div className={`border rounded p-4 ${bgColor}`}>
      <div className="flex items-center justify-between">
        <span className={`text-2xl font-bold font-theme-data ${color}`}>{value}</span>
        <span className="text-xl">{icon}</span>
      </div>
      <div className={`text-xs font-theme-data mt-1 ${color}`}>{label}</div>
      {subtext && <div className="text-xs text-text-muted mt-1">{subtext}</div>}
    </div>
  );
}

export function InboxStatsCards({
  apiBase,
  userId,
  authToken,
  refreshInterval = 30000,
}: InboxStatsCardsProps) {
  const [stats, setStats] = useState<InboxStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStats = useCallback(async () => {
    try {
      // Try new stats endpoint
      const response = await fetch(`${apiBase}/api/email/stats?user_id=${userId}`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });

      if (response.ok) {
        const data = await response.json();
        setStats(data);
        setError(null);
      } else {
        // Fallback: compute from inbox data
        const inboxResponse = await fetch(
          `${apiBase}/api/email/inbox?user_id=${userId}&limit=100`,
          { headers: authToken ? { Authorization: `Bearer ${authToken}` } : {} },
        );

        if (inboxResponse.ok) {
          const inboxData = await inboxResponse.json();
          const emails = inboxData.inbox || inboxData.results || [];

          // Compute stats locally
          const computed: InboxStats = {
            urgent_count: emails.filter(
              (e: { priority?: { priority?: string } }) => e.priority?.priority === 'critical',
            ).length,
            high_priority_count: emails.filter(
              (e: { priority?: { priority?: string } }) => e.priority?.priority === 'high',
            ).length,
            action_required_count: emails.filter(
              (e: { priority?: { priority?: string } }) =>
                e.priority?.priority === 'critical' || e.priority?.priority === 'high',
            ).length,
            unread_count: emails.filter((e: { email?: { is_read?: boolean } }) => !e.email?.is_read)
              .length,
            total_count: emails.length,
          };

          setStats(computed);
          setError(null);
        }
      }
    } catch (e) {
      setError('Failed to load stats');
      logger.error('Stats fetch error:', e);
    } finally {
      setLoading(false);
    }
  }, [apiBase, userId, authToken]);

  useEffect(() => {
    fetchStats();

    const interval = setInterval(fetchStats, refreshInterval);
    return () => clearInterval(interval);
  }, [fetchStats, refreshInterval]);

  if (loading) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="border border-[var(--accent)]/20 rounded p-4 animate-pulse">
            <div className="h-8 bg-[var(--accent)]/10 rounded mb-2"></div>
            <div className="h-4 bg-[var(--accent)]/10 rounded w-2/3"></div>
          </div>
        ))}
      </div>
    );
  }

  if (error && !stats) {
    return (
      <div className="p-4 border border-red-500/30 bg-red-500/5 rounded text-sm font-theme-data text-red-400">
        {error}
      </div>
    );
  }

  if (!stats) {
    return null;
  }

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <StatCard
        label="URGENT"
        value={stats.urgent_count}
        color="text-red-400"
        bgColor="bg-red-500/10 border-red-500/40"
        icon="!"
        subtext={stats.urgent_count > 0 ? 'Needs attention now' : 'All clear'}
      />
      <StatCard
        label="HIGH PRIORITY"
        value={stats.high_priority_count}
        color="text-orange-400"
        bgColor="bg-orange-500/10 border-orange-500/40"
        icon="^"
        subtext={stats.high_priority_count > 0 ? 'Respond today' : 'On track'}
      />
      <StatCard
        label="UNREAD"
        value={stats.unread_count}
        color="text-blue-400"
        bgColor="bg-blue-500/10 border-blue-500/40"
        icon="*"
        subtext={`of ${stats.total_count} total`}
      />
      <StatCard
        label="ACTION REQUIRED"
        value={stats.action_required_count}
        color="text-yellow-400"
        bgColor="bg-yellow-500/10 border-yellow-500/40"
        icon=">"
        subtext={stats.overdue_count ? `${stats.overdue_count} overdue` : undefined}
      />
    </div>
  );
}
