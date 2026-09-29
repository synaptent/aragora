'use client';

interface ApiErrorProps {
  /** Error message or Error object */
  error: string | Error | null;
  /** Callback when retry button is clicked */
  onRetry?: () => void;
  /** Use compact inline style */
  compact?: boolean;
  /** Custom class name */
  className?: string;
}

/**
 * Terminal-styled error display component with optional retry button
 *
 * Matches the Aragora CRT/terminal aesthetic with warning colors.
 */
export function ApiError({ error, onRetry, compact = false, className = '' }: ApiErrorProps) {
  if (!error) return null;

  const errorMessage = typeof error === 'string' ? error : error.message;

  if (compact) {
    return (
      <div
        className={`bg-warning/10 border border-warning/30 p-2 text-warning text-xs font-theme-data ${className}`}
        role="alert"
        aria-live="assertive"
      >
        <span className="font-bold" aria-hidden="true">
          {'>'}
        </span>
        <span className="font-bold"> ERROR:</span> {errorMessage}
        {onRetry && (
          <button
            onClick={onRetry}
            className="ml-2 underline hover:text-warning/80 transition-colors"
            aria-label={`Retry after error: ${errorMessage}`}
          >
            RETRY
          </button>
        )}
      </div>
    );
  }

  return (
    <div
      className={`bg-warning/10 border border-warning/30 p-4 font-theme-data ${className}`}
      role="alert"
      aria-live="assertive"
    >
      <div className="flex items-start gap-2 mb-3">
        <div className="text-warning text-xl" aria-hidden="true">
          {'>'}
        </div>
        <div>
          <div className="text-warning font-bold mb-1">ERROR</div>
          <div className="text-text text-sm">{errorMessage}</div>
        </div>
      </div>

      {onRetry && (
        <button
          onClick={onRetry}
          className="w-full border border-warning text-warning py-2 px-4 hover:bg-warning hover:text-bg transition-colors font-bold"
          aria-label={`Retry after error: ${errorMessage}`}
        >
          <span aria-hidden="true">{'>'}</span> RETRY_REQUEST
        </button>
      )}
    </div>
  );
}
