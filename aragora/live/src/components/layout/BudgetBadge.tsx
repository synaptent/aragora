'use client';

import Link from 'next/link';
import { useAuth } from '@/context/AuthContext';
import { useCostSummary } from '@/hooks/useCosts';

/**
 * Compact budget usage indicator for the TopBar.
 * Shows current budget utilization percentage with color coding.
 */
export function BudgetBadge() {
  const { isAuthenticated } = useAuth();
  // Only fetch costs when authenticated to avoid 401 retry storms
  const { summary, isLoading, error } = useCostSummary('30d', { enabled: isAuthenticated });

  if (!isAuthenticated || isLoading || error || !summary || summary.budget_usd <= 0) {
    return null;
  }

  const percent = Math.min(Math.round((summary.total_cost_usd / summary.budget_usd) * 100), 100);

  const colorClass =
    percent > 90
      ? 'text-red-400 border-red-400/30 bg-red-400/10'
      : percent > 75
        ? 'text-yellow-400 border-yellow-400/30 bg-yellow-400/10'
        : 'text-[var(--acid-green)] border-[var(--acid-green)]/30 bg-[var(--acid-green)]/10';

  return (
    <Link
      href="/usage"
      className={`hidden sm:flex items-center gap-1 px-2 py-1 text-xs font-theme-data border rounded transition-opacity hover:opacity-80 ${colorClass}`}
      title={`Budget: ${percent}% used ($${summary.total_cost_usd.toFixed(2)} / $${summary.budget_usd.toFixed(2)})`}
    >
      <span>$</span>
      <span>{percent}%</span>
    </Link>
  );
}
