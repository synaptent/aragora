'use client';

import { useState } from 'react';

interface RetryButtonProps {
  onRetry: () => Promise<void> | void;
  className?: string;
  children?: React.ReactNode;
}

export function RetryButton({ onRetry, className = '', children = 'Retry' }: RetryButtonProps) {
  const [isRetrying, setIsRetrying] = useState(false);

  const handleRetry = async () => {
    setIsRetrying(true);
    try {
      await onRetry();
    } finally {
      setIsRetrying(false);
    }
  };

  return (
    <button
      onClick={handleRetry}
      disabled={isRetrying}
      className={`px-3 py-1 bg-accent/20 hover:bg-accent/30 text-accent border border-accent/30 rounded text-sm transition-colors disabled:opacity-50 ${className}`}
    >
      {isRetrying ? 'Retrying...' : children}
    </button>
  );
}

interface ErrorWithRetryProps {
  error: string;
  onRetry: () => Promise<void> | void;
  className?: string;
}

export function ErrorWithRetry({ error, onRetry, className = '' }: ErrorWithRetryProps) {
  return (
    <div
      className={`flex items-center justify-between gap-3 p-3 bg-red-900/20 border border-red-800/50 rounded ${className}`}
    >
      <span className="text-red-400 text-sm">{error}</span>
      <RetryButton onRetry={onRetry} />
    </div>
  );
}
