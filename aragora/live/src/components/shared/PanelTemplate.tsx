'use client';

import { ReactNode, useState, useCallback } from 'react';

export interface Tab {
  id: string;
  label: string;
  content: ReactNode;
  disabled?: boolean;
  badge?: string | number;
}

export interface PanelTemplateProps {
  /** Panel title displayed in header */
  title: string;
  /** Optional icon (emoji or text) displayed before title */
  icon?: string;
  /** Whether data is currently loading */
  loading?: boolean;
  /** Error message to display (null = no error) */
  error?: string | null;
  /** Callback when refresh button is clicked */
  onRefresh?: () => void;
  /** Callback when retry is clicked (defaults to onRefresh) */
  onRetry?: () => void;
  /** Tab configuration - if provided, renders tabbed interface */
  tabs?: Tab[];
  /** Currently active tab ID */
  activeTab?: string;
  /** Callback when tab changes */
  onTabChange?: (tabId: string) => void;
  /** Main content (used when not using tabs) */
  children?: ReactNode;
  /** Whether panel can be collapsed */
  collapsible?: boolean;
  /** Initial collapsed state */
  defaultCollapsed?: boolean;
  /** Header actions (right side) - rendered before refresh button */
  headerActions?: ReactNode;
  /** Badge/count to show in header */
  badge?: string | number;
  /** Additional CSS classes for the panel */
  className?: string;
  /** Custom loading skeleton */
  loadingSkeleton?: ReactNode;
  /** Empty state content when no data */
  emptyState?: ReactNode;
  /** Whether to show empty state */
  isEmpty?: boolean;
}

/**
 * Standardized panel template for dashboard components.
 * Provides consistent loading, error, and tab handling.
 */
export function PanelTemplate({
  title,
  icon,
  loading = false,
  error = null,
  onRefresh,
  onRetry,
  tabs,
  activeTab,
  onTabChange,
  children,
  collapsible = false,
  defaultCollapsed = false,
  headerActions,
  badge,
  className = '',
  loadingSkeleton,
  emptyState,
  isEmpty = false,
}: PanelTemplateProps) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);

  const handleRetry = useCallback(() => {
    if (onRetry) {
      onRetry();
    } else if (onRefresh) {
      onRefresh();
    }
  }, [onRetry, onRefresh]);

  // Default loading skeleton
  const defaultSkeleton = (
    <div className="animate-pulse space-y-3">
      <div className="h-4 bg-surface rounded w-3/4" />
      <div className="h-4 bg-surface rounded w-1/2" />
      <div className="h-4 bg-surface rounded w-2/3" />
    </div>
  );

  // Default empty state
  const defaultEmptyState = (
    <div className="text-center text-text-muted py-8">No data available.</div>
  );

  return (
    <div className={`card ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-border">
        <div className="flex items-center gap-2">
          {/* Collapse toggle */}
          {collapsible && (
            <button
              onClick={() => setCollapsed(!collapsed)}
              className="text-text-muted hover:text-text transition-colors"
              aria-label={collapsed ? 'Expand' : 'Collapse'}
            >
              {collapsed ? '▶' : '▼'}
            </button>
          )}

          {/* Icon */}
          {icon && <span className="text-[var(--accent)]">{icon}</span>}

          {/* Title */}
          <h3 className="text-sm font-theme-data text-text-muted uppercase tracking-wide">
            {title}
          </h3>

          {/* Badge */}
          {badge !== undefined && (
            <span className="text-xs bg-accent/20 text-accent px-1.5 py-0.5 rounded">{badge}</span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {/* Custom header actions */}
          {headerActions}

          {/* Refresh button */}
          {onRefresh && (
            <button
              onClick={onRefresh}
              disabled={loading}
              className="text-xs text-text-muted hover:text-accent transition-colors disabled:opacity-50"
              title="Refresh"
            >
              {loading ? '...' : '↻'}
            </button>
          )}
        </div>
      </div>

      {/* Collapsible content */}
      {!collapsed && (
        <div className="p-4">
          {/* Error state */}
          {error && (
            <div className="mb-4 p-3 bg-red-900/20 border border-red-800/30 rounded">
              <div className="flex items-center justify-between">
                <span className="text-red-400 text-sm">{error}</span>
                <button
                  onClick={handleRetry}
                  className="text-xs text-red-400 hover:text-red-300 underline"
                >
                  Retry
                </button>
              </div>
            </div>
          )}

          {/* Loading state */}
          {loading && !error && (loadingSkeleton || defaultSkeleton)}

          {/* Empty state */}
          {!loading && !error && isEmpty && (emptyState || defaultEmptyState)}

          {/* Tab navigation */}
          {!loading && !error && !isEmpty && tabs && tabs.length > 0 && (
            <>
              <div className="flex flex-wrap gap-1 mb-4 border-b border-border pb-2">
                {tabs.map((tab) => (
                  <button
                    key={tab.id}
                    onClick={() => onTabChange?.(tab.id)}
                    disabled={tab.disabled}
                    className={`px-3 py-1.5 text-xs font-theme-data rounded transition-colors ${
                      activeTab === tab.id
                        ? 'bg-accent text-bg'
                        : tab.disabled
                          ? 'text-text-muted/50 cursor-not-allowed'
                          : 'text-text-muted hover:text-text hover:bg-surface'
                    }`}
                  >
                    {tab.label}
                    {tab.badge !== undefined && (
                      <span className="ml-1 text-xs opacity-70">({tab.badge})</span>
                    )}
                  </button>
                ))}
              </div>

              {/* Tab content */}
              {tabs.find((t) => t.id === activeTab)?.content}
            </>
          )}

          {/* Direct children (when not using tabs) */}
          {!loading && !error && !isEmpty && !tabs && children}
        </div>
      )}
    </div>
  );
}

/**
 * Hook to manage panel state (loading, error, data fetching).
 */
export function usePanelState<T>(
  fetchFn: () => Promise<T>,
  options: { initialData?: T; autoFetch?: boolean; refreshInterval?: number } = {},
) {
  const { initialData, autoFetch = true, refreshInterval } = options;
  const [data, setData] = useState<T | undefined>(initialData);
  const [loading, setLoading] = useState(autoFetch);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await fetchFn();
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch data');
    } finally {
      setLoading(false);
    }
  }, [fetchFn]);

  // Auto-fetch on mount
  if (autoFetch && data === undefined && !loading && !error) {
    fetch();
  }

  // Refresh interval
  if (refreshInterval && refreshInterval > 0) {
    // Note: In a real implementation, this would use useEffect
    // This is a simplified version for demonstration
  }

  return { data, setData, loading, error, fetch, refresh: fetch };
}

export default PanelTemplate;
