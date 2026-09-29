'use client';

import { useState, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { useSWRFetch } from '@/hooks/useSWRFetch';

// ---------------------------------------------------------------------------
// Types matching feature_flags.py and admin/feature_flags.py response shapes
// ---------------------------------------------------------------------------

interface FeatureFlag {
  name: string;
  value: unknown;
  default?: unknown;
  type?: string;
  description: string;
  category: string;
  status: string;
  env_var?: string;
  deprecated_since?: string;
  removed_in?: string;
  replacement?: string;
  usage?: {
    access_count: number;
    last_accessed: string | null;
    access_locations: Record<string, number>;
  };
}

interface FlagStats {
  total_flags: number;
  active_flags: number;
  beta_flags: number;
  deprecated_flags: number;
  categories: Record<string, number>;
}

interface FlagsResponse {
  flags: FeatureFlag[];
  total: number;
  stats?: FlagStats;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    active: 'text-[var(--acid-green)] bg-[var(--acid-green)]/10 border-[var(--acid-green)]/30',
    beta: 'text-[var(--acid-cyan)] bg-[var(--acid-cyan)]/10 border-[var(--acid-cyan)]/30',
    deprecated: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30',
    removed: 'text-red-400 bg-red-500/10 border-red-500/30',
    experimental: 'text-purple-400 bg-purple-500/10 border-purple-500/30',
  };

  const style =
    colors[status.toLowerCase()] ||
    'text-[var(--text-muted)] bg-[var(--surface)] border-[var(--border)]';

  return (
    <span className={`px-2 py-0.5 text-[10px] font-theme-data uppercase rounded border ${style}`}>
      {status}
    </span>
  );
}

function CategoryBadge({ category }: { category: string }) {
  const colors: Record<string, string> = {
    core: 'text-[var(--acid-green)]',
    knowledge: 'text-blue-400',
    memory: 'text-purple-400',
    debate: 'text-[var(--acid-cyan)]',
    enterprise: 'text-yellow-400',
    security: 'text-red-400',
    experimental: 'text-pink-400',
  };

  const color = colors[category.toLowerCase()] || 'text-[var(--text-muted)]';

  return <span className={`text-[10px] font-theme-data uppercase ${color}`}>{category}</span>;
}

function ValueDisplay({ value, type: _type }: { value: unknown; type?: string }) {
  if (typeof value === 'boolean') {
    return (
      <span
        className={`font-theme-data text-sm font-bold ${value ? 'text-[var(--acid-green)]' : 'text-red-400'}`}
      >
        {value ? 'ON' : 'OFF'}
      </span>
    );
  }

  if (typeof value === 'number') {
    return <span className="font-theme-data text-sm text-purple-400">{value}</span>;
  }

  if (typeof value === 'string') {
    return (
      <span className="font-theme-data text-xs text-[var(--acid-cyan)]" title={value}>
        {value.length > 30 ? `${value.substring(0, 30)}...` : value}
      </span>
    );
  }

  return (
    <span className="font-theme-data text-xs text-[var(--text-muted)]">
      {JSON.stringify(value)}
    </span>
  );
}

function ToggleSwitch({
  enabled,
  onToggle,
  disabled,
}: {
  enabled: boolean;
  onToggle: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onToggle}
      disabled={disabled}
      className={`relative w-10 h-5 rounded-full transition-colors disabled:opacity-50 ${
        enabled
          ? 'bg-[var(--acid-green)]/30 border border-[var(--acid-green)]/50'
          : 'bg-[var(--surface)] border border-[var(--border)]'
      }`}
    >
      <span
        className={`absolute top-0.5 w-4 h-4 rounded-full transition-all ${
          enabled ? 'left-5 bg-[var(--acid-green)]' : 'left-0.5 bg-[var(--text-muted)]'
        }`}
      />
    </button>
  );
}

// ---------------------------------------------------------------------------
// Page Component
// ---------------------------------------------------------------------------

export default function FeatureFlagsPage() {
  const [categoryFilter, setCategoryFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedFlag, setExpandedFlag] = useState<string | null>(null);
  const [togglingFlag, setTogglingFlag] = useState<string | null>(null);

  // Build query params
  const params = new URLSearchParams();
  if (categoryFilter) params.set('category', categoryFilter);
  if (statusFilter) params.set('status', statusFilter);
  const queryString = params.toString();

  // Fetch from admin endpoint for richer data (value + default + type + stats)
  const {
    data: flagsData,
    isLoading,
    error,
    mutate: refreshFlags,
  } = useSWRFetch<FlagsResponse>(
    `/api/v1/admin/feature-flags${queryString ? `?${queryString}` : ''}`,
    { refreshInterval: 30000 },
  );

  const allFlags = flagsData?.flags ?? [];
  const stats = flagsData?.stats;

  // Client-side search filter
  const flags = searchQuery.trim()
    ? allFlags.filter(
        (f) =>
          f.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
          f.description.toLowerCase().includes(searchQuery.toLowerCase()),
      )
    : allFlags;

  // Get unique categories from flags for filter dropdown
  const categories = Array.from(new Set(allFlags.map((f) => f.category))).sort();

  // Toggle a boolean flag
  const handleToggle = useCallback(
    async (flag: FeatureFlag) => {
      if (typeof flag.value !== 'boolean') return;

      setTogglingFlag(flag.name);
      try {
        const response = await fetch(`/api/v1/admin/feature-flags/${flag.name}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ value: !flag.value }),
        });
        if (response.ok) {
          refreshFlags();
        }
      } catch {
        // toggle failed silently
      } finally {
        setTogglingFlag(null);
      }
    },
    [refreshFlags],
  );

  // Count by status
  const activeCount = allFlags.filter((f) => f.status === 'active').length;
  const betaCount = allFlags.filter((f) => f.status === 'beta').length;
  const deprecatedCount = allFlags.filter((f) => f.status === 'deprecated').length;
  const booleanOnCount = allFlags.filter((f) => typeof f.value === 'boolean' && f.value).length;
  const booleanTotal = allFlags.filter((f) => typeof f.value === 'boolean').length;

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
                href="/admin"
                className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
              >
                Admin
              </Link>
              <span className="text-[var(--text-muted)]">/</span>
              <span className="text-xs font-theme-data text-[var(--acid-green)]">
                Feature Flags
              </span>
            </div>
            <h1 className="text-xl font-theme-data text-[var(--acid-green)]">
              {'>'} FEATURE FLAGS
            </h1>
            <p className="text-xs text-[var(--text-muted)] font-theme-data mt-1">
              View and manage feature flags across the platform. Toggle boolean flags, filter by
              category or status, and monitor usage.
            </p>
          </div>

          {/* Error State */}
          {error && (
            <div className="mb-6 p-4 bg-red-500/10 border border-red-500/30 text-red-400 font-theme-data text-sm">
              Failed to load feature flags. The feature flag system may not be available.
            </div>
          )}

          {/* Summary Stats */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
            <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
              <div className="text-2xl font-theme-data text-[var(--acid-green)]">
                {allFlags.length}
              </div>
              <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                Total Flags
              </div>
            </div>
            <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
              <div className="text-2xl font-theme-data text-[var(--acid-green)]">{activeCount}</div>
              <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                Active
              </div>
            </div>
            <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
              <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">{betaCount}</div>
              <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                Beta
              </div>
            </div>
            <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
              <div className="text-2xl font-theme-data text-yellow-400">{deprecatedCount}</div>
              <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                Deprecated
              </div>
            </div>
            <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
              <div className="text-2xl font-theme-data text-purple-400">
                {booleanOnCount}/{booleanTotal}
              </div>
              <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                Enabled
              </div>
            </div>
          </div>

          {/* Category Distribution */}
          {stats?.categories && Object.keys(stats.categories).length > 0 && (
            <div className="mb-6 p-4 bg-[var(--surface)] border border-[var(--border)]">
              <h2 className="text-sm font-theme-data text-[var(--acid-green)] uppercase mb-3">
                Category Distribution
              </h2>
              <div className="flex flex-wrap gap-3">
                {Object.entries(stats.categories)
                  .sort(([, a], [, b]) => b - a)
                  .map(([cat, count]) => (
                    <button
                      key={cat}
                      onClick={() => setCategoryFilter(categoryFilter === cat ? '' : cat)}
                      className={`px-3 py-1.5 text-xs font-theme-data border rounded transition-colors ${
                        categoryFilter === cat
                          ? 'border-[var(--acid-green)] bg-[var(--acid-green)]/10 text-[var(--acid-green)]'
                          : 'border-[var(--border)] text-[var(--text-muted)] hover:border-[var(--acid-green)]/30'
                      }`}
                    >
                      {cat} <span className="text-[var(--text-muted)]">({count})</span>
                    </button>
                  ))}
              </div>
            </div>
          )}

          {/* Filters */}
          <div className="flex flex-wrap items-center gap-3 mb-4">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search flags..."
              className="px-3 py-1.5 bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] text-xs font-theme-data rounded focus:outline-none focus:border-[var(--acid-green)]/50 w-64"
            />
            <select
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              className="px-3 py-1.5 bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] text-xs font-theme-data rounded focus:outline-none focus:border-[var(--acid-green)]/50"
            >
              <option value="">All Categories</option>
              {categories.map((cat) => (
                <option key={cat} value={cat}>
                  {cat}
                </option>
              ))}
            </select>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="px-3 py-1.5 bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] text-xs font-theme-data rounded focus:outline-none focus:border-[var(--acid-green)]/50"
            >
              <option value="">All Statuses</option>
              <option value="active">Active</option>
              <option value="beta">Beta</option>
              <option value="deprecated">Deprecated</option>
              <option value="experimental">Experimental</option>
            </select>
            <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
              {flags.length} of {allFlags.length} flags
            </span>
          </div>

          {/* Flags List */}
          <PanelErrorBoundary panelName="Feature Flags List">
            <div className="space-y-2">
              {isLoading ? (
                <div className="p-12 text-center text-[var(--text-muted)] font-theme-data animate-pulse">
                  Loading feature flags...
                </div>
              ) : flags.length === 0 ? (
                <div className="p-12 text-center text-[var(--text-muted)] font-theme-data">
                  {allFlags.length === 0
                    ? 'No feature flags registered. The flag system may not be initialized.'
                    : 'No flags match the current filters.'}
                </div>
              ) : (
                flags.map((flag) => {
                  const isExpanded = expandedFlag === flag.name;
                  const isBooleanFlag = typeof flag.value === 'boolean';

                  return (
                    <div
                      key={flag.name}
                      className={`bg-[var(--surface)] border transition-colors ${
                        isExpanded ? 'border-[var(--acid-green)]/50' : 'border-[var(--border)]'
                      }`}
                    >
                      {/* Flag Row */}
                      <div
                        className="flex items-center gap-4 px-4 py-3 cursor-pointer hover:bg-[var(--acid-green)]/5 transition-colors"
                        onClick={() => setExpandedFlag(isExpanded ? null : flag.name)}
                      >
                        {/* Toggle (for boolean flags) */}
                        <div className="w-12 shrink-0">
                          {isBooleanFlag ? (
                            <ToggleSwitch
                              enabled={flag.value as boolean}
                              onToggle={() => handleToggle(flag)}
                              disabled={togglingFlag === flag.name}
                            />
                          ) : (
                            <ValueDisplay value={flag.value} type={flag.type} />
                          )}
                        </div>

                        {/* Name & Description */}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="font-theme-data text-xs text-[var(--text)] font-bold">
                              {flag.name}
                            </span>
                            <StatusBadge status={flag.status} />
                            <CategoryBadge category={flag.category} />
                          </div>
                          <p className="text-[10px] text-[var(--text-muted)] font-theme-data mt-0.5 truncate">
                            {flag.description}
                          </p>
                        </div>

                        {/* Value display for non-boolean */}
                        {!isBooleanFlag && (
                          <div className="shrink-0">
                            <ValueDisplay value={flag.value} type={flag.type} />
                          </div>
                        )}

                        {/* Expand indicator */}
                        <span className="text-xs text-[var(--text-muted)] font-theme-data shrink-0">
                          {isExpanded ? '[-]' : '[+]'}
                        </span>
                      </div>

                      {/* Expanded Details */}
                      {isExpanded && (
                        <div className="px-4 py-3 border-t border-[var(--border)] bg-[var(--bg)]/50">
                          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
                            <div>
                              <span className="text-[var(--text-muted)] font-theme-data block">
                                Type
                              </span>
                              <span className="text-[var(--text)] font-theme-data">
                                {flag.type || 'unknown'}
                              </span>
                            </div>
                            <div>
                              <span className="text-[var(--text-muted)] font-theme-data block">
                                Default
                              </span>
                              <span className="text-purple-400 font-theme-data">
                                {String(flag.default ?? '--')}
                              </span>
                            </div>
                            <div>
                              <span className="text-[var(--text-muted)] font-theme-data block">
                                Current
                              </span>
                              <span className="text-[var(--acid-cyan)] font-theme-data">
                                {String(flag.value)}
                              </span>
                            </div>
                            {flag.env_var && (
                              <div>
                                <span className="text-[var(--text-muted)] font-theme-data block">
                                  Env Var
                                </span>
                                <span className="text-yellow-400 font-theme-data text-[10px]">
                                  {flag.env_var}
                                </span>
                              </div>
                            )}
                          </div>

                          {flag.deprecated_since && (
                            <div className="mt-3 p-2 bg-yellow-500/5 border border-yellow-500/20 rounded text-xs font-theme-data">
                              <span className="text-yellow-400">
                                Deprecated since {flag.deprecated_since}
                              </span>
                              {flag.removed_in && (
                                <span className="text-[var(--text-muted)]">
                                  {' '}
                                  (removal in {flag.removed_in})
                                </span>
                              )}
                              {flag.replacement && (
                                <span className="text-[var(--acid-cyan)]">
                                  {' '}
                                  - replace with: {flag.replacement}
                                </span>
                              )}
                            </div>
                          )}

                          {flag.usage && (
                            <div className="mt-3 pt-3 border-t border-[var(--border)]">
                              <h4 className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase mb-2">
                                Usage Stats
                              </h4>
                              <div className="grid grid-cols-2 gap-2 text-xs">
                                <div>
                                  <span className="text-[var(--text-muted)] font-theme-data">
                                    Accesses:{' '}
                                  </span>
                                  <span className="text-[var(--acid-green)] font-theme-data">
                                    {flag.usage.access_count}
                                  </span>
                                </div>
                                <div>
                                  <span className="text-[var(--text-muted)] font-theme-data">
                                    Last:{' '}
                                  </span>
                                  <span className="text-[var(--text)] font-theme-data">
                                    {flag.usage.last_accessed
                                      ? new Date(flag.usage.last_accessed).toLocaleString()
                                      : 'Never'}
                                  </span>
                                </div>
                              </div>
                              {flag.usage.access_locations &&
                                Object.keys(flag.usage.access_locations).length > 0 && (
                                  <div className="mt-2">
                                    <span className="text-[10px] text-[var(--text-muted)] font-theme-data">
                                      Access Locations:
                                    </span>
                                    <div className="flex flex-wrap gap-1 mt-1">
                                      {Object.entries(flag.usage.access_locations)
                                        .sort(([, a], [, b]) => b - a)
                                        .slice(0, 10)
                                        .map(([loc, count]) => (
                                          <span
                                            key={loc}
                                            className="px-1.5 py-0.5 text-[10px] font-theme-data bg-[var(--surface)] text-[var(--text-muted)] rounded"
                                          >
                                            {loc} ({count})
                                          </span>
                                        ))}
                                    </div>
                                  </div>
                                )}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </PanelErrorBoundary>

          {/* Quick Links */}
          <div className="mt-8 flex flex-wrap gap-3">
            <Link
              href="/admin"
              className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              Admin Panel
            </Link>
            <Link
              href="/settings"
              className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              Settings
            </Link>
            <Link
              href="/observability"
              className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              Observability
            </Link>
          </div>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--acid-green)]/20 mt-8">
          <div className="text-[var(--acid-green)]/50 mb-2" aria-hidden="true">
            {'='.repeat(40)}
          </div>
          <p className="text-[var(--text-muted)]">{'>'} ARAGORA // FEATURE FLAGS</p>
        </footer>
      </main>
    </>
  );
}
