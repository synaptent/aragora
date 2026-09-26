'use client';

interface LoadingSpinnerProps {
  /** Loading message to display */
  message?: string;
  /** Use compact inline style */
  compact?: boolean;
  /** Custom class name */
  className?: string;
}

/**
 * Terminal-styled loading indicator
 *
 * Matches the Aragora CRT/terminal aesthetic with animated blocks.
 */
export function LoadingSpinner({
  message = 'Loading...',
  compact = false,
  className = '',
}: LoadingSpinnerProps) {
  if (compact) {
    return (
      <div
        className={`text-accent text-xs font-theme-data animate-pulse ${className}`}
        role="status"
        aria-live="polite"
        aria-label={message}
      >
        <span aria-hidden="true">{'>'}</span> {message}
      </div>
    );
  }

  return (
    <div
      className={`flex items-center justify-center p-8 ${className}`}
      role="status"
      aria-live="polite"
      aria-label={message}
    >
      <div className="text-accent font-theme-data text-center">
        <div className="text-lg mb-2 flex items-center justify-center gap-2">
          <span className="animate-pulse" aria-hidden="true">
            {'>'}
          </span>
          <span>{message}</span>
        </div>
        <div className="flex gap-1 justify-center" aria-hidden="true">
          <span className="animate-pulse" style={{ animationDelay: '0ms' }}>
            █
          </span>
          <span className="animate-pulse" style={{ animationDelay: '150ms' }}>
            █
          </span>
          <span className="animate-pulse" style={{ animationDelay: '300ms' }}>
            █
          </span>
        </div>
      </div>
    </div>
  );
}
