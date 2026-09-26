'use client';

interface ErrorRetryProps {
  /** Error message to display */
  message?: string;
  /** Callback when retry is clicked */
  onRetry?: () => void;
  /** Whether currently retrying */
  retrying?: boolean;
  /** Current retry attempt (for display) */
  retryAttempt?: number;
  /** Max retry attempts (for display) */
  maxRetries?: number;
  /** Size variant */
  size?: 'sm' | 'md' | 'lg';
  /** Show as inline or block */
  inline?: boolean;
}

export function ErrorRetry({
  message = 'Something went wrong',
  onRetry,
  retrying = false,
  retryAttempt = 0,
  maxRetries = 3,
  size = 'md',
  inline = false,
}: ErrorRetryProps) {
  const sizeClasses = { sm: 'text-xs p-2', md: 'text-sm p-3', lg: 'text-base p-4' };

  const buttonSizeClasses = {
    sm: 'px-2 py-0.5 text-xs',
    md: 'px-3 py-1 text-sm',
    lg: 'px-4 py-2 text-base',
  };

  if (inline) {
    return (
      <span className="inline-flex items-center gap-2 text-warning font-theme-data text-sm">
        <span>⚠</span>
        <span>{message}</span>
        {onRetry && (
          <button
            onClick={onRetry}
            disabled={retrying}
            className="text-[var(--accent)] hover:underline disabled:opacity-50"
          >
            {retrying ? 'Retrying...' : '[Retry]'}
          </button>
        )}
      </span>
    );
  }

  return (
    <div
      className={`bg-warning/10 border border-warning/30 rounded ${sizeClasses[size]} font-theme-data`}
    >
      <div className="flex items-center gap-3">
        <span className="text-warning text-lg">⚠</span>
        <div className="flex-1">
          <p className="text-text">{message}</p>
          {retrying && retryAttempt > 0 && (
            <p className="text-xs text-text-muted mt-1">
              Retry attempt {retryAttempt}/{maxRetries}...
            </p>
          )}
        </div>
        {onRetry && (
          <button
            onClick={onRetry}
            disabled={retrying}
            className={`
              ${buttonSizeClasses[size]}
              bg-warning/20 border border-warning/40
              text-warning hover:bg-warning/30
              transition-colors disabled:opacity-50 disabled:cursor-not-allowed
              font-theme-data
            `}
          >
            {retrying ? (
              <span className="flex items-center gap-2">
                <span className="animate-spin">↻</span>
                Retrying
              </span>
            ) : (
              '[RETRY]'
            )}
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * Simple loading/error/empty state wrapper
 */
interface DataStateProps<T> {
  data: T | null | undefined;
  loading: boolean;
  error: Error | null;
  onRetry?: () => void;
  retrying?: boolean;
  loadingText?: string;
  emptyText?: string;
  children: (data: T) => React.ReactNode;
}

export function DataState<T>({
  data,
  loading,
  error,
  onRetry,
  retrying,
  loadingText = 'Loading...',
  emptyText = 'No data available',
  children,
}: DataStateProps<T>) {
  if (loading && !data) {
    return (
      <div className="flex items-center justify-center p-8 text-text-muted font-theme-data">
        <span className="animate-pulse">{loadingText}</span>
      </div>
    );
  }

  if (error) {
    return (
      <ErrorRetry
        message={error.message || 'Failed to load data'}
        onRetry={onRetry}
        retrying={retrying}
      />
    );
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center p-8 text-text-muted font-theme-data">
        {emptyText}
      </div>
    );
  }

  return <>{children(data)}</>;
}
