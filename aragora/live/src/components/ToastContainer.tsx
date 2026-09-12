'use client';

import { useEffect, useState } from 'react';
import type { Toast, ToastType } from '@/hooks/useToast';

interface ToastContainerProps {
  toasts: Toast[];
  onRemove: (id: string) => void;
}

const TOAST_STYLES: Record<ToastType, { bg: string; border: string; icon: string }> = {
  error: { bg: 'bg-red-500/10', border: 'border-red-500/50', icon: '✕' },
  success: { bg: 'bg-green-500/10', border: 'border-green-500/50', icon: '✓' },
  warning: { bg: 'bg-yellow-500/10', border: 'border-yellow-500/50', icon: '⚠' },
  info: { bg: 'bg-[var(--acid-cyan)]/10', border: 'border-[var(--acid-cyan)]/50', icon: 'ℹ' },
};

export function ToastContainer({ toasts, onRemove }: ToastContainerProps) {
  if (toasts.length === 0) return null;

  return (
    <div
      className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2 max-w-sm"
      role="region"
      aria-label="Notifications"
      aria-live="polite"
      aria-atomic="false"
    >
      {toasts.map((toast) => (
        <ToastItem key={toast.id} toast={toast} onRemove={onRemove} />
      ))}
    </div>
  );
}

interface ToastItemProps {
  toast: Toast;
  onRemove: (id: string) => void;
}

function ToastItem({ toast, onRemove }: ToastItemProps) {
  const [isExiting, setIsExiting] = useState(false);
  const styles = TOAST_STYLES[toast.type];

  // Handle exit animation
  useEffect(() => {
    if (toast.duration && toast.duration > 0) {
      const exitTimer = setTimeout(() => {
        setIsExiting(true);
      }, toast.duration - 300); // Start exit animation 300ms before removal

      return () => clearTimeout(exitTimer);
    }
  }, [toast.duration]);

  const handleClose = () => {
    setIsExiting(true);
    setTimeout(() => onRemove(toast.id), 200);
  };

  return (
    <div
      role={toast.type === 'error' ? 'alert' : 'status'}
      aria-live={toast.type === 'error' ? 'assertive' : 'polite'}
      className={`
        ${styles.bg} ${styles.border} border
        p-3 rounded font-theme-data text-sm text-text
        shadow-lg backdrop-blur-sm
        transition-all duration-200
        ${isExiting ? 'opacity-0 translate-x-4' : 'opacity-100 translate-x-0'}
        animate-in slide-in-from-right-4
      `}
    >
      <div className="flex items-start gap-2">
        <span className="text-lg leading-none">{styles.icon}</span>
        <p className="flex-1 break-words">{toast.message}</p>
        <button
          onClick={handleClose}
          className="text-text-muted hover:text-text transition-colors text-xs"
          aria-label="Close"
        >
          [×]
        </button>
      </div>
    </div>
  );
}
