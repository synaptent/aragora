'use client';

import React, { createContext, useContext, useEffect, useMemo, ReactNode } from 'react';
import { useToast, type ToastType } from '@/hooks/useToast';
import { ToastContainer } from '@/components/ToastContainer';

interface ToastContextType {
  showToast: (message: string, type?: ToastType, duration?: number) => void;
  showError: (message: string, duration?: number) => void;
  showSuccess: (message: string, duration?: number) => void;
  clearToasts: () => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const { toasts, showToast, showError, showSuccess, removeToast, clearToasts } = useToast();

  // Bridge: listen for auth session expiry events from AuthContext (which sits above us in the tree)
  useEffect(() => {
    const handleSessionExpired = () => {
      showError('Your session has expired. Please sign in again.', 8000);
    };
    window.addEventListener('auth:session-expired', handleSessionExpired);
    return () => window.removeEventListener('auth:session-expired', handleSessionExpired);
  }, [showError]);

  const value = useMemo<ToastContextType>(
    () => ({ showToast, showError, showSuccess, clearToasts }),
    [showToast, showError, showSuccess, clearToasts],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastContainer toasts={toasts} onRemove={removeToast} />
    </ToastContext.Provider>
  );
}

export function useToastContext(): ToastContextType {
  const context = useContext(ToastContext);
  if (context === undefined) {
    throw new Error('useToastContext must be used within a ToastProvider');
  }
  return context;
}

// Alias for backward compatibility
export { useToastContext as useToast };
